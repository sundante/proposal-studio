"""RFP digest: map-reduce extraction of ``digest.json`` from an opportunity's indexed chunks.

Map: one schema-constrained worker call per group of chunks (< ~2k tokens), citing excerpt
numbers. Reduce (plain Python): map numbers to citations, de-duplicate by normalised text and
embedding similarity, merge citations, flag conflicting opportunity facts.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, TypeVar

import numpy as np
from pydantic import BaseModel, ConfigDict, Field

from studio.config import RagConfig
from studio.ingest import CHARS_PER_TOKEN
from studio.llm import LLMClient, Message, StructuredOutputError
from studio.models import Chunk, Cite
from studio.rag import VectorIndex

StatusFn = Callable[[str], None]
T = TypeVar("T")

DIGEST_FILE = "digest.json"
META_FILE = "digest.meta.json"
ReqType = Literal["functional", "nonfunctional", "compliance"]


class DigestError(ValueError):
    """The digest could not be built. The message is user-facing."""


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --- digest.json (spec §8) ------------------------------------------------------------------


class OpportunityInfo(_Strict):
    """Headline facts about the opportunity."""

    client: str | None = None
    title: str | None = None
    due_date: str | None = None
    submission_format: str | None = None
    page_or_slide_limits: str | None = None


class Problem(_Strict):
    """A business or technical problem the client describes."""

    statement: str
    evidence: list[Cite]


class StateItem(_Strict):
    """A current-state ("Before") or desired-outcome ("After") item."""

    item: str
    evidence: list[Cite]


class Requirement(_Strict):
    """A requirement the vendor must or should meet."""

    id: str
    text: str
    type: ReqType
    mandatory: bool
    cite: list[Cite]


class EvaluationCriterion(_Strict):
    """How proposals are scored."""

    criterion: str
    weight: str | None = None
    cite: list[Cite]


class ComplianceItem(_Strict):
    """A compliance framework and what the RFP says about it."""

    framework: str
    detail: str
    cite: list[Cite]


class SystemMentioned(_Strict):
    """A named system or platform in the client's environment."""

    name: str
    role: str = ""


class RiskItem(_Strict):
    """A risk or red flag for the bid."""

    item: str
    cite: list[Cite]


class Digest(_Strict):
    """Structured RFP digest. Every item carries the citations it was drawn from."""

    opportunity: OpportunityInfo = Field(default_factory=OpportunityInfo)
    business_problems: list[Problem] = Field(default_factory=list)
    technical_problems: list[Problem] = Field(default_factory=list)
    current_state: list[StateItem] = Field(default_factory=list)
    desired_outcomes: list[StateItem] = Field(default_factory=list)
    requirements: list[Requirement] = Field(default_factory=list)
    evaluation_criteria: list[EvaluationCriterion] = Field(default_factory=list)
    compliance: list[ComplianceItem] = Field(default_factory=list)
    systems_mentioned: list[SystemMentioned] = Field(default_factory=list)
    risks_and_red_flags: list[RiskItem] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)


# --- map-step schema (what the LLM fills; cites are excerpt numbers) ------------------------


class PartOpportunity(BaseModel):
    """Opportunity facts stated in these excerpts (null when not stated)."""

    client: str | None = None
    title: str | None = None
    due_date: str | None = None
    submission_format: str | None = None
    page_or_slide_limits: str | None = None
    excerpts: list[int] = Field(default_factory=list)


class PartProblem(BaseModel):
    statement: str
    excerpts: list[int]


class PartItem(BaseModel):
    item: str
    excerpts: list[int]


class PartRequirement(BaseModel):
    rfp_id: str | None = None
    text: str
    type: ReqType
    mandatory: bool
    excerpts: list[int]


class PartCriterion(BaseModel):
    criterion: str
    weight: str | None = None
    excerpts: list[int]


class PartCompliance(BaseModel):
    framework: str
    detail: str
    excerpts: list[int]


class PartSystem(BaseModel):
    name: str
    role: str = ""


class DigestPart(BaseModel):
    """Facts extracted from one group of RFP excerpts."""

    opportunity: PartOpportunity = Field(default_factory=PartOpportunity)
    business_problems: list[PartProblem] = Field(default_factory=list)
    technical_problems: list[PartProblem] = Field(default_factory=list)
    current_state: list[PartItem] = Field(default_factory=list)
    desired_outcomes: list[PartItem] = Field(default_factory=list)
    requirements: list[PartRequirement] = Field(default_factory=list)
    evaluation_criteria: list[PartCriterion] = Field(default_factory=list)
    compliance: list[PartCompliance] = Field(default_factory=list)
    systems_mentioned: list[PartSystem] = Field(default_factory=list)
    risks_and_red_flags: list[PartItem] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)


_SYSTEM = """You extract facts from RFP excerpts into JSON for a proposal team.
Rules:
- Use ONLY the excerpts. Never invent facts, names, dates or numbers.
- For every item, put the number(s) of the excerpt(s) it came from in "excerpts".
- Leave a list empty when the excerpts say nothing about it; leave opportunity fields null.
Field guide:
- opportunity: fill whenever stated: client (organisation issuing the RFP), title (RFP title),
  due_date (proposal deadline, as written), submission_format (how/where to submit),
  page_or_slide_limits (e.g. "30 slides"). List the excerpt numbers you used.
- business_problems / technical_problems: pains or challenges the client describes.
- current_state: how things work today. desired_outcomes: what the client wants afterwards.
- requirements: what the vendor must or should provide. mandatory=true for must/shall/required
  wording or a "Mandatory: Yes" column. type: functional (features), nonfunctional (security,
  performance, operations), compliance (laws, standards). rfp_id: the identifier printed
  next to that requirement in the RFP (e.g. "3.2.1" or "REQ-7"), or null if none is printed.
- evaluation_criteria: how proposals are scored; weight as written (e.g. "40 percent").
- compliance: frameworks such as HIPAA, HITRUST, SOC2, FHIR, CMS-0057 and what is required.
- systems_mentioned: named systems or platforms in the client's environment and their role.
- risks_and_red_flags: tight deadlines, vague scope, unusual terms or conflicts.
- open_questions: clarifications the vendor should ask the client."""


# --- grouping -------------------------------------------------------------------------------


def group_chunks(chunks: Sequence[Chunk], max_tokens: int = 2000) -> list[list[Chunk]]:
    """Consecutive chunks of the same file, packed up to ``max_tokens`` (chars / 4) per group."""
    max_chars = max_tokens * CHARS_PER_TOKEN
    groups: list[list[Chunk]] = []
    current: list[Chunk] = []
    size = 0
    for chunk in chunks:
        new_file = bool(current) and chunk.file != current[-1].file
        if current and (new_file or size + len(chunk.text) > max_chars):
            groups.append(current)
            current, size = [], 0
        current.append(chunk)
        size += len(chunk.text)
    if current:
        groups.append(current)
    return groups


def build_messages(group: Sequence[Chunk]) -> list[Message]:
    """Prompt for one map call: numbered, labelled excerpts."""
    excerpts = "\n\n".join(f"[{n}] {c.cite}\n{c.text}" for n, c in enumerate(group, start=1))
    return [
        {"role": "system", "content": _SYSTEM},
        {"role": "user", "content": f"Excerpts:\n\n{excerpts}\n\nReturn the JSON."},
    ]


# --- reduce ---------------------------------------------------------------------------------


@dataclass
class _Stats:
    invalid_refs: int = 0
    dropped: int = 0


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s%-]", " ", text.lower())).strip()


def _union(*lists: Sequence[Cite]) -> list[Cite]:
    """Merge citation lists in order. One section cited with and without a page (e.g. the PDF
    and DOCX of the same RFP) keeps only the paged citation."""
    by_section: dict[str, list[Cite]] = {}
    for cites in lists:
        for c in cites:
            group = by_section.setdefault(c.section, [])
            if c not in group:
                group.append(c)
    out: list[Cite] = []
    for group in by_section.values():
        paged = [c for c in group if c.page is not None]
        out.extend(paged or group[:1])
    return out


def _words(text: str) -> set[str]:
    return {w for w in _norm(text).split() if len(w) > 2}


_ID_FIELD = re.compile(
    r"\b(?:ID|Req(?:uirement)?\s*(?:ID|No\.?|#))\s*[:#]\s*([A-Za-z0-9][\w.-]{0,15})"
)
_ID_LEAD = re.compile(r"^\s*([A-Z]{1,6}-?\d+(?:\.\d+)*)\b")


def _requirement_id(
    rfp_id: str | None, text: str, numbers: Sequence[int], group: Sequence[Chunk]
) -> str:
    """The RFP's own id for a requirement, checked against the cited excerpt lines.

    The model's id is kept only if a cited line prints it and is about this requirement (small
    models copy one id onto every requirement). Otherwise the id is read from the best-matching
    cited line: an ``ID: R-01`` table field or a leading ``R-01`` / ``3.2.1`` label.
    """
    want = _words(text)
    claimed = (rfp_id or "").strip().lower()
    best, best_overlap = "", 0.5
    for n in numbers:
        if not 1 <= n <= len(group):
            continue
        for line in group[n - 1].text.splitlines():
            overlap = len(want & _words(line)) / max(len(want), 1)
            if overlap < best_overlap:
                continue
            if claimed and claimed in line.lower():
                return (rfp_id or "").strip()
            match = _ID_FIELD.search(line) or _ID_LEAD.match(line)
            if match:
                best, best_overlap = match.group(1), overlap
    return best


def _cites(numbers: Sequence[int], group: Sequence[Chunk], stats: _Stats) -> list[Cite]:
    out = []
    for n in numbers:
        if 1 <= n <= len(group):
            out.append(group[n - 1].cite)
        else:
            stats.invalid_refs += 1
    return _union(out)


def _dedupe(
    items: list[T],
    key: Callable[[T], str],
    merge: Callable[[T, T], T],
    llm: LLMClient,
    threshold: float,
    compatible: Callable[[T, T], bool] = lambda _a, _b: True,
) -> list[T]:
    """Merge items with equal normalised keys, then items whose key embeddings are similar."""
    exact: dict[str, T] = {}
    for item in items:
        k = _norm(key(item))
        if k in exact and compatible(exact[k], item):
            exact[k] = merge(exact[k], item)
        elif k in exact:
            exact[f"{k}\x00{len(exact)}"] = item
        else:
            exact[k] = item
    unique = list(exact.values())
    if len(unique) < 2:
        return unique

    vectors = np.asarray(llm.embed([key(i) for i in unique]), dtype="float32")
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    vectors = vectors / np.where(norms == 0, 1, norms)
    kept: list[int] = []
    merged: dict[int, T] = {}
    for idx, item in enumerate(unique):
        target = None
        for k in kept:
            if float(vectors[idx] @ vectors[k]) >= threshold and compatible(merged[k], item):
                target = k
                break
        if target is None:
            kept.append(idx)
            merged[idx] = item
        else:
            merged[target] = merge(merged[target], item)
    return [merged[k] for k in kept]


def _id_compatible(a: Requirement, b: Requirement) -> bool:
    return not a.id or not b.id or _norm(a.id) == _norm(b.id)


@dataclass
class _Acc:
    """Items collected across groups before de-duplication (``Requirement.id`` = RFP id)."""

    opportunity: dict[str, list[tuple[str, list[Cite]]]] = field(default_factory=dict)
    business_problems: list[Problem] = field(default_factory=list)
    technical_problems: list[Problem] = field(default_factory=list)
    current_state: list[StateItem] = field(default_factory=list)
    desired_outcomes: list[StateItem] = field(default_factory=list)
    requirements: list[Requirement] = field(default_factory=list)
    evaluation_criteria: list[EvaluationCriterion] = field(default_factory=list)
    compliance: list[ComplianceItem] = field(default_factory=list)
    systems_mentioned: list[SystemMentioned] = field(default_factory=list)
    risks_and_red_flags: list[RiskItem] = field(default_factory=list)
    open_questions: list[str] = field(default_factory=list)


def _collect(part: DigestPart, group: Sequence[Chunk], acc: _Acc, stats: _Stats) -> None:
    """Convert one map result into cited items, dropping any item left without a citation."""

    def cited(numbers: Sequence[int]) -> list[Cite] | None:
        cites = _cites(numbers, group, stats)
        if not cites:
            stats.dropped += 1
            return None
        return cites

    opp_cites = _cites(part.opportunity.excerpts, group, stats) or [group[0].cite]
    for name in OpportunityInfo.model_fields:
        value = getattr(part.opportunity, name)
        if value and str(value).strip():
            acc.opportunity.setdefault(name, []).append((str(value).strip(), opp_cites))

    for src, dest in (
        (part.business_problems, acc.business_problems),
        (part.technical_problems, acc.technical_problems),
    ):
        for p in src:
            if p.statement.strip() and (c := cited(p.excerpts)):
                dest.append(Problem(statement=p.statement.strip(), evidence=c))
    for src2, dest2 in (
        (part.current_state, acc.current_state),
        (part.desired_outcomes, acc.desired_outcomes),
    ):
        for s in src2:
            if s.item.strip() and (c := cited(s.excerpts)):
                dest2.append(StateItem(item=s.item.strip(), evidence=c))
    for r in part.requirements:
        if r.text.strip() and (c := cited(r.excerpts)):
            acc.requirements.append(
                Requirement(
                    id=_requirement_id(r.rfp_id, r.text, r.excerpts, group),
                    text=r.text.strip(),
                    type=r.type,
                    mandatory=r.mandatory,
                    cite=c,
                )
            )
    for e in part.evaluation_criteria:
        if e.criterion.strip() and (c := cited(e.excerpts)):
            acc.evaluation_criteria.append(
                EvaluationCriterion(criterion=e.criterion.strip(), weight=e.weight, cite=c)
            )
    for x in part.compliance:
        if x.framework.strip() and (c := cited(x.excerpts)):
            acc.compliance.append(
                ComplianceItem(framework=x.framework.strip(), detail=x.detail.strip(), cite=c)
            )
    for r2 in part.risks_and_red_flags:
        if r2.item.strip() and (c := cited(r2.excerpts)):
            acc.risks_and_red_flags.append(RiskItem(item=r2.item.strip(), cite=c))
    acc.systems_mentioned.extend(
        SystemMentioned(name=s.name.strip(), role=s.role.strip())
        for s in part.systems_mentioned
        if s.name.strip()
    )
    acc.open_questions.extend(q.strip() for q in part.open_questions if q.strip())


def _reduce(acc: _Acc, llm: LLMClient, threshold: float) -> Digest:
    def dd(items, key, merge, compatible=lambda _a, _b: True):
        return _dedupe(items, key, merge, llm, threshold, compatible)

    def problem_merge(a, b):
        return a.model_copy(update={"evidence": _union(a.evidence, b.evidence)})

    opportunity = OpportunityInfo()
    conflicts: list[RiskItem] = []
    for name, values in acc.opportunity.items():
        setattr(opportunity, name, values[0][0])
        distinct: dict[str, tuple[str, list[Cite]]] = {}
        for value, cites in values:
            distinct.setdefault(_norm(value), (value, cites))
        if len(distinct) > 1:
            label = name.replace("_", " ")
            shown = " vs ".join(f"'{v}'" for v, _ in distinct.values())
            conflicts.append(
                RiskItem(
                    item=f"Conflicting {label} in the RFP: {shown}",
                    cite=_union(*(c for _, c in distinct.values())),
                )
            )

    requirements = dd(
        acc.requirements,
        lambda r: r.text,
        lambda a, b: a.model_copy(
            update={
                "id": a.id or b.id,
                "mandatory": a.mandatory or b.mandatory,
                "cite": _union(a.cite, b.cite),
            }
        ),
        _id_compatible,
    )
    # Requirements sharing an RFP id are one requirement if their wording overlaps; otherwise the
    # id was copied onto the wrong requirement, so the later one loses it.
    position: dict[str, int] = {}
    ordered: list[Requirement] = []
    for r in requirements:
        rid = _norm(r.id)
        if rid and rid in position:
            first = ordered[position[rid]]
            shared = _words(first.text) & _words(r.text)
            if len(shared) / max(min(len(_words(first.text)), len(_words(r.text))), 1) < 0.3:
                ordered.append(r.model_copy(update={"id": ""}))
                continue
            ordered[position[rid]] = first.model_copy(
                update={
                    "mandatory": first.mandatory or r.mandatory,
                    "cite": _union(first.cite, r.cite),
                }
            )
            continue
        if rid:
            position[rid] = len(ordered)
        ordered.append(r)
    used = {r.id for r in ordered if r.id}
    counter = 0
    final_reqs = []
    for r in ordered:
        if not r.id:
            counter += 1
            while f"REQ-{counter:03d}" in used:
                counter += 1
            r = r.model_copy(update={"id": f"REQ-{counter:03d}"})
        final_reqs.append(r)

    return Digest(
        opportunity=opportunity,
        business_problems=dd(acc.business_problems, lambda p: p.statement, problem_merge),
        technical_problems=dd(acc.technical_problems, lambda p: p.statement, problem_merge),
        current_state=dd(acc.current_state, lambda s: s.item, problem_merge),
        desired_outcomes=dd(acc.desired_outcomes, lambda s: s.item, problem_merge),
        requirements=final_reqs,
        evaluation_criteria=dd(
            acc.evaluation_criteria,
            lambda e: e.criterion,
            lambda a, b: a.model_copy(
                update={"weight": a.weight or b.weight, "cite": _union(a.cite, b.cite)}
            ),
        ),
        compliance=dd(
            acc.compliance,
            lambda x: f"{x.framework}: {x.detail}",
            lambda a, b: a.model_copy(update={"cite": _union(a.cite, b.cite)}),
            lambda a, b: _norm(a.framework) == _norm(b.framework),
        ),
        systems_mentioned=dd(
            acc.systems_mentioned,
            lambda s: s.name,
            lambda a, b: a if len(a.role) >= len(b.role) else a.model_copy(update={"role": b.role}),
        ),
        risks_and_red_flags=conflicts
        + dd(
            acc.risks_and_red_flags,
            lambda r: r.item,
            lambda a, b: a.model_copy(update={"cite": _union(a.cite, b.cite)}),
        ),
        open_questions=dd(acc.open_questions, lambda q: q, lambda a, _b: a),
    )


# --- build / load ---------------------------------------------------------------------------


@dataclass
class DigestReport:
    """Result of a digest run."""

    digest: Digest
    path: Path
    groups: int
    failed_groups: int = 0
    warnings: list[str] = field(default_factory=list)


def build_digest(
    opp_dir: Path, llm: LLMClient, cfg: RagConfig, *, on_status: StatusFn | None = None
) -> DigestReport:
    """Build ``digest.json`` for the opportunity at ``opp_dir`` from its indexed chunks."""
    status = on_status or (lambda _msg: None)
    index = VectorIndex(opp_dir / "index")
    chunks = index.iter_chunks()
    if not chunks:
        raise DigestError("Nothing ingested yet. Run `/ingest` with the RFP files first.")

    groups = group_chunks(chunks, cfg.digest_group_tokens)
    acc, stats = _Acc(), _Stats()
    warnings: list[str] = []
    failed = 0
    for n, group in enumerate(groups, start=1):
        status(f"Reading section group {n}/{len(groups)}…")
        try:
            part = llm.generate_structured("worker", build_messages(group), DigestPart)
        except StructuredOutputError:
            failed += 1
            warnings.append(f"Skipped section group {n} ({group[0].cite}…): invalid model output.")
            continue
        _collect(part, group, acc, stats)
    if failed == len(groups):
        raise DigestError(
            "The model returned invalid output for every section. Try again, or set a larger "
            "worker model with `/config set worker.model <model>`."
        )

    status("Merging and de-duplicating…")
    digest = _reduce(acc, llm, cfg.dedupe_similarity)
    if stats.invalid_refs:
        warnings.append(f"Ignored {stats.invalid_refs} invalid excerpt references.")
    if stats.dropped:
        warnings.append(f"Dropped {stats.dropped} items that had no valid citation.")

    path = opp_dir / DIGEST_FILE
    path.write_text(digest.model_dump_json(indent=2), encoding="utf-8")
    meta = {
        "generated": datetime.now(UTC).isoformat(timespec="seconds"),
        "sources": index.manifest_hashes(),
        "groups": len(groups),
        "failed_groups": failed,
        "warnings": warnings,
    }
    (opp_dir / META_FILE).write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return DigestReport(digest, path, len(groups), failed, warnings)


def load_digest(opp_dir: Path) -> Digest | None:
    """The saved digest, or None if there isn't one."""
    path = opp_dir / DIGEST_FILE
    if not path.exists():
        return None
    return Digest.model_validate_json(path.read_text(encoding="utf-8"))


def is_stale(opp_dir: Path) -> bool:
    """True if files were ingested, changed or removed since the digest was built."""
    meta_path = opp_dir / META_FILE
    if not meta_path.exists():
        return (opp_dir / DIGEST_FILE).exists()
    sources = json.loads(meta_path.read_text(encoding="utf-8")).get("sources", {})
    return sources != VectorIndex(opp_dir / "index").manifest_hashes()


# --- presentation ---------------------------------------------------------------------------


def _c(cites: Sequence[Cite]) -> str:
    return " " + "".join(str(c) for c in cites) if cites else ""


def render_summary(digest: Digest, warnings: Sequence[str] = ()) -> str:
    """Readable Markdown summary of a digest for chat or the terminal."""
    o = digest.opportunity
    lines = [f"## RFP digest — {o.title or 'untitled opportunity'}", ""]
    facts = [
        ("Client", o.client),
        ("Due", o.due_date),
        ("Submission", o.submission_format),
        ("Limits", o.page_or_slide_limits),
    ]
    lines += [f"- **{k}:** {v}" for k, v in facts if v] or ["- (no headline facts found)"]

    def block(title: str, rows: list[str]) -> None:
        if rows:
            lines.extend(["", f"### {title}", *rows])

    block(
        "Business problems", [f"- {p.statement}{_c(p.evidence)}" for p in digest.business_problems]
    )
    block(
        "Technical problems",
        [f"- {p.statement}{_c(p.evidence)}" for p in digest.technical_problems],
    )
    block("Today (before)", [f"- {s.item}{_c(s.evidence)}" for s in digest.current_state])
    block("Wanted (after)", [f"- {s.item}{_c(s.evidence)}" for s in digest.desired_outcomes])

    reqs = digest.requirements
    if reqs:
        mandatory = [r for r in reqs if r.mandatory]
        by_type = {
            t: sum(r.type == t for r in reqs) for t in ("functional", "nonfunctional", "compliance")
        }
        counts = ", ".join(f"{n} {t}" for t, n in by_type.items() if n)
        block(
            f"Requirements — {len(mandatory)} mandatory of {len(reqs)} ({counts})",
            [f"- **{r.id}** {r.text}{_c(r.cite)}" for r in mandatory]
            + (
                [f"- …plus {len(reqs) - len(mandatory)} optional"]
                if len(reqs) > len(mandatory)
                else []
            ),
        )
    block(
        "Evaluation criteria",
        [
            f"- {e.criterion}" + (f" — {e.weight}" if e.weight else "") + _c(e.cite)
            for e in digest.evaluation_criteria
        ],
    )
    block("Compliance", [f"- **{x.framework}:** {x.detail}{_c(x.cite)}" for x in digest.compliance])
    block(
        "Systems mentioned",
        [f"- {s.name}" + (f" — {s.role}" if s.role else "") for s in digest.systems_mentioned],
    )
    block("Risks and red flags", [f"- {r.item}{_c(r.cite)}" for r in digest.risks_and_red_flags])
    block("Questions to ask the client", [f"- {q}" for q in digest.open_questions])
    block("Warnings", [f"- {w}" for w in warnings])
    lines += ["", "Next: `/outline` (or `/digest --xlsx` for a requirements compliance matrix)"]
    return "\n".join(lines)


MATRIX_COLUMNS = ("ID", "Requirement", "Type", "Mandatory", "Source", "Response", "Owner", "Status")


def export_matrix(digest: Digest, out_dir: Path, opp_id: str) -> Path:
    """Write ``out/<opp>-requirements-v<N>.xlsx`` (never overwrites) and return its path."""
    import openpyxl
    from openpyxl.styles import Alignment, Font

    out_dir.mkdir(parents=True, exist_ok=True)
    version = 1
    while (path := out_dir / f"{opp_id}-requirements-v{version}.xlsx").exists():
        version += 1

    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "Requirements"
    sheet.append(list(MATRIX_COLUMNS))
    for cell in sheet[1]:
        cell.font = Font(bold=True)
    for r in digest.requirements:
        sheet.append(
            [
                r.id,
                r.text,
                r.type,
                "Yes" if r.mandatory else "No",
                " ".join(map(str, r.cite)),
                "",
                "",
                "",
            ]
        )
    for col, width in zip("ABCDEFGH", (12, 60, 14, 11, 40, 50, 16, 12), strict=True):
        sheet.column_dimensions[col].width = width
    for row in sheet.iter_rows(min_row=2):
        for cell in row:
            cell.alignment = Alignment(wrap_text=True, vertical="top")
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = sheet.dimensions
    workbook.save(path)
    return path

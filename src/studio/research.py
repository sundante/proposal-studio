"""Offline multi-step research over ``library/`` and the active RFP (``/research``).

A small explicit loop (no agent framework):

1. **Plan**: the router model splits the question into sub-questions, each with 2 rephrasings.
2. **Retrieve**: multi-query search over the RFP index and the library indexes (no LLM).
3. **Draft**: one worker call per sub-question; points cite excerpt numbers, which Python maps
   to ``[file, p.N]`` / ``[file, slide N]``.
4. **Gap check**: weakly evidenced sub-questions get new queries (one router call), a second
   retrieval, and a redraft.
5. **Synthesise**: summary, implications for this RFP, and gaps; the markdown is assembled here.

Every run has a hard cap on LLM calls; one call is always reserved for synthesis. No web
access — sources are pluggable (``config/research.yaml``) for future local collections.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from studio.config import StudioConfig
from studio.llm import LLMClient, Message, StructuredOutputError
from studio.models import Chunk
from studio.rag import VectorIndex, library_index

StatusFn = Callable[[str], None]
SOURCE_LABELS = {"rfp": "RFP", "proposals": "Past proposals", "reference": "Reference"}


class ResearchError(ValueError):
    """Research could not run. User-facing."""


# --- schemas the models fill ----------------------------------------------------------------


class SubQuestion(BaseModel):
    question: str
    rephrasings: list[str]


class ResearchPlan(BaseModel):
    """Sub-questions that together answer the research question."""

    sub_questions: list[SubQuestion]


class FindingPoint(BaseModel):
    text: str
    excerpts: list[int]


class FindingDraft(BaseModel):
    """Answer to one sub-question from numbered excerpts."""

    points: list[FindingPoint]
    evidence: Literal["strong", "partial", "none"]
    missing: str


class GapItem(BaseModel):
    sub_question: int
    queries: list[str]


class GapPlan(BaseModel):
    """New search queries for weakly evidenced sub-questions."""

    items: list[GapItem]


class Synthesis(BaseModel):
    """Final report text built only from the findings."""

    summary: list[str]
    implications: list[str]
    gaps: list[str]


_PLAN_SYSTEM = """You plan offline research for a proposal team. Split the question into
{n_min}-{n_max} focused sub-questions that together answer it. For each, give 2 alternative
phrasings using different words (synonyms, related terms) to help a search engine."""

_FINDING_SYSTEM = """You answer one research sub-question using ONLY the numbered excerpts.
- Each point is one short, factual statement; list the excerpt numbers it came from.
- Do not use outside knowledge. Do not invent figures, names or certifications.
- evidence: strong if the excerpts answer it directly, partial if only in part, none if not.
- missing: what the excerpts do not cover (empty string if nothing)."""

_GAP_SYSTEM = """Some research sub-questions had weak evidence. For each one listed, suggest 2
new search queries with different keywords that might find better excerpts."""

_SYNTH_SYSTEM = """You write the conclusion of a research report for a proposal team, using
ONLY the findings given (do not add facts). summary: 2-4 bullet sentences answering the main
question. implications: 2-4 concrete implications for the proposal/RFP. gaps: what the
library does not cover (short phrases)."""


# --- budget, sources, citations -------------------------------------------------------------


class Budget:
    """Hard cap on LLM calls, with calls reserved for later steps."""

    def __init__(self, limit: int) -> None:
        self.limit = limit
        self.used = 0

    @property
    def remaining(self) -> int:
        return self.limit - self.used

    def can(self, calls: int = 1, reserve: int = 0) -> bool:
        """True if ``calls`` fit while keeping ``reserve`` calls for later."""
        return self.remaining - reserve >= calls

    def spend(self) -> None:
        if self.remaining <= 0:
            raise ResearchError("LLM call budget exhausted.")
        self.used += 1


@dataclass(frozen=True)
class Excerpt:
    """A retrieved chunk with the source it came from."""

    source: str
    chunk: Chunk
    score: float

    @property
    def cite(self) -> str:
        """``[file, p.N]`` or ``[file, slide N]``."""
        c = self.chunk
        if c.page is None:
            return f"[{c.file}]"
        if c.file.lower().endswith(".pptx"):
            return f"[{c.file}, slide {c.page}]"
        return f"[{c.file}, p.{c.page}]"


def open_sources(root: Path, cfg: StudioConfig, opp_dir: Path | None) -> dict[str, VectorIndex]:
    """Non-empty indexes for the configured sources (the RFP only if an opportunity is active)."""
    sources: dict[str, VectorIndex] = {}
    for name in cfg.research.sources:
        if name == "rfp":
            if opp_dir is None:
                continue
            index = VectorIndex(opp_dir / "index")
        else:
            index = library_index(root, name)
        if len(index):
            sources[name] = index
    return sources


def retrieve_multi(
    queries: Sequence[str],
    sources: dict[str, VectorIndex],
    llm: LLMClient,
    k_per_query: int,
    keep: int,
) -> list[Excerpt]:
    """Search every source with every query; keep the best score per chunk, top ``keep``."""
    queries = [q for q in dict.fromkeys(q.strip() for q in queries) if q]
    if not queries or not sources:
        return []
    vectors = llm.embed(queries)
    best: dict[tuple[str, str], Excerpt] = {}
    for source, index in sources.items():
        for vector in vectors:
            for hit in index.search(vector, k_per_query):
                key = (source, hit.chunk.id)
                if key not in best or hit.score > best[key].score:
                    best[key] = Excerpt(source, hit.chunk, hit.score)
    return sorted(best.values(), key=lambda e: e.score, reverse=True)[:keep]


def _excerpt_block(excerpts: Sequence[Excerpt]) -> str:
    return "\n\n".join(
        f"[{n}] ({SOURCE_LABELS.get(e.source, e.source)}) {e.cite}\n{e.chunk.text[:1500]}"
        for n, e in enumerate(excerpts, start=1)
    )


# --- report ---------------------------------------------------------------------------------


@dataclass
class Finding:
    """What the research found for one sub-question."""

    question: str
    points: list[tuple[str, list[str]]] = field(default_factory=list)  # (text, cites)
    evidence: str = "none"
    missing: str = ""
    best_score: float = 0.0
    gap_round: bool = False

    @property
    def weak(self) -> bool:
        return not self.points or self.evidence != "strong"


@dataclass
class ResearchReport:
    """A finished research run."""

    question: str
    findings: list[Finding]
    summary: list[str] = field(default_factory=list)
    implications: list[str] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)
    sources_searched: list[str] = field(default_factory=list)
    llm_calls: int = 0
    notes: list[str] = field(default_factory=list)

    def cited_sources(self) -> list[str]:
        """Every citation used in the findings, in first-use order."""
        return list(dict.fromkeys(c for f in self.findings for _, cites in f.points for c in cites))

    def to_markdown(self) -> str:
        """The report as markdown (saved to disk and shown in chat)."""
        lines = [f"# Research: {self.question}", ""]
        stamp = datetime.now(UTC).strftime("%Y-%m-%d")
        searched = ", ".join(SOURCE_LABELS.get(s, s) for s in self.sources_searched)
        lines += [f"_{stamp} · offline · searched: {searched} · {self.llm_calls} LLM calls_", ""]
        lines += ["## Summary", *(f"- {s}" for s in self.summary or ["(no summary)"]), ""]
        lines.append("## Findings")
        for n, finding in enumerate(self.findings, start=1):
            tag = " (after gap check)" if finding.gap_round else ""
            lines += ["", f"### {n}. {finding.question}", f"_Evidence: {finding.evidence}{tag}_"]
            lines += [f"- {text} {''.join(cites)}" for text, cites in finding.points]
            if not finding.points:
                lines.append("- Not covered in the library.")
            if finding.missing:
                lines.append(f"- _Not covered:_ {finding.missing}")
        lines += [
            "",
            "## Implications for this RFP",
            *(f"- {i}" for i in self.implications or ["(none)"]),
        ]
        gaps = list(
            dict.fromkeys([*self.gaps, *(f.question for f in self.findings if not f.points)])
        )
        lines += [
            "",
            "## Gaps (not covered in the library)",
            *(f"- {g}" for g in gaps or ["(none)"]),
        ]
        lines += ["", "## Sources", *(f"- {c}" for c in self.cited_sources() or ["(none)"])]
        if self.notes:
            lines += ["", "## Notes", *(f"- {n}" for n in self.notes)]
        lines += ["", "Next: `/deck` (findings can inform your blocks) or another `/research`"]
        return "\n".join(lines)


# --- the loop -------------------------------------------------------------------------------


def _draft(
    llm: LLMClient, budget: Budget, question: str, excerpts: Sequence[Excerpt], notes: list[str]
) -> Finding:
    finding = Finding(question=question, best_score=excerpts[0].score if excerpts else 0.0)
    if not excerpts:
        finding.missing = "no matching excerpts in the indexed sources"
        return finding
    messages: list[Message] = [
        {"role": "system", "content": _FINDING_SYSTEM},
        {
            "role": "user",
            "content": f"Sub-question: {question}\n\nExcerpts:\n\n{_excerpt_block(excerpts)}",
        },
    ]
    budget.spend()
    try:
        draft = llm.generate_structured("worker", messages, FindingDraft)
    except StructuredOutputError:
        notes.append(f"Could not draft a finding for: {question}")
        return finding
    dropped = 0
    for point in draft.points:
        cites = list(
            dict.fromkeys(excerpts[n - 1].cite for n in point.excerpts if 1 <= n <= len(excerpts))
        )
        if point.text.strip() and cites:
            finding.points.append((point.text.strip(), cites))
        elif point.text.strip():
            dropped += 1
    if dropped:
        notes.append(f"Dropped {dropped} uncited point(s) for: {question}")
    finding.evidence = draft.evidence if finding.points else "none"
    finding.missing = draft.missing.strip()
    return finding


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:50] or "research"


def save_report(report: ResearchReport, out_dir: Path) -> Path:
    """Write ``<out_dir>/<date>-<slug>.md`` (``-2``, ``-3``… if it exists)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    base = f"{datetime.now(UTC).strftime('%Y%m%d')}-{_slug(report.question)}"
    path, n = out_dir / f"{base}.md", 1
    while path.exists():
        n += 1
        path = out_dir / f"{base}-{n}.md"
    path.write_text(report.to_markdown(), encoding="utf-8")
    return path


def run_research(
    question: str,
    root: Path,
    llm: LLMClient,
    cfg: StudioConfig,
    *,
    opp_dir: Path | None = None,
    max_calls: int | None = None,
    on_status: StatusFn | None = None,
) -> ResearchReport:
    """Research ``question`` over the library (and the RFP if ``opp_dir``) within the call cap."""
    status = on_status or (lambda _msg: None)
    rcfg = cfg.research
    if not question.strip():
        raise ResearchError("Ask a question, e.g. `/research how do we handle FHIR R4?`")
    sources = open_sources(root, cfg, opp_dir)
    if not sources:
        raise ResearchError(
            "Nothing to search yet. Run `studio library index` (and `/ingest` for an RFP)."
        )
    budget = Budget(max_calls or rcfg.max_llm_calls)
    report = ResearchReport(question=question, findings=[], sources_searched=list(sources))

    # 1. Plan (reserve 1 call for synthesis).
    status("Planning sub-questions…")
    n_max = min(rcfg.max_sub_questions, max(budget.remaining - 2, 1))
    plan_messages: list[Message] = [
        {"role": "system", "content": _PLAN_SYSTEM.format(n_min=min(3, n_max), n_max=n_max)},
        {"role": "user", "content": question},
    ]
    budget.spend()
    try:
        plan = llm.generate_structured("router", plan_messages, ResearchPlan).sub_questions
    except StructuredOutputError:
        report.notes.append("Planning failed; researched the question as a single sub-question.")
        plan = []
    plan = [sq for sq in plan if sq.question.strip()][:n_max] or [
        SubQuestion(question=question, rephrasings=[])
    ]

    # 2–3. Retrieve and draft each sub-question.
    excerpts_for: list[list[Excerpt]] = []
    for n, sq in enumerate(plan, start=1):
        status(f"Searching and drafting finding {n}/{len(plan)}…")
        excerpts = retrieve_multi(
            [sq.question, *sq.rephrasings[:2]],
            sources,
            llm,
            rcfg.top_k_per_query,
            rcfg.excerpts_per_question,
        )
        excerpts_for.append(excerpts)
        if budget.can(1, reserve=1):
            report.findings.append(_draft(llm, budget, sq.question, excerpts, report.notes))
        else:
            report.findings.append(Finding(question=sq.question, missing="call budget reached"))
            report.notes.append(f"Call budget reached before drafting: {sq.question}")

    # 4. Gap check: one round for weak sub-questions, budget permitting.
    weak = [i for i, f in enumerate(report.findings) if f.weak or f.best_score < rcfg.weak_score]
    if weak and budget.can(2, reserve=1):
        status(f"Gap check for {len(weak)} sub-question(s)…")
        listing = "\n".join(f"{i + 1}. {report.findings[i].question}" for i in weak)
        budget.spend()
        try:
            gap = llm.generate_structured(
                "router",
                [{"role": "system", "content": _GAP_SYSTEM}, {"role": "user", "content": listing}],
                GapPlan,
            )
        except StructuredOutputError:
            gap = GapPlan(items=[])
            report.notes.append("Gap check planning failed; kept first-round findings.")
        queries = {item.sub_question - 1: item.queries for item in gap.items}
        for i in weak:
            if not budget.can(1, reserve=1):
                report.notes.append(
                    f"Call budget reached; no gap round for: {report.findings[i].question}"
                )
                continue
            more = retrieve_multi(
                [report.findings[i].question, *queries.get(i, [])],
                sources,
                llm,
                rcfg.top_k_per_query,
                rcfg.excerpts_per_question,
            )
            merged = {(e.source, e.chunk.id): e for e in [*excerpts_for[i], *more]}
            ranked = sorted(merged.values(), key=lambda e: e.score, reverse=True)
            redraft = _draft(
                llm,
                budget,
                report.findings[i].question,
                ranked[: rcfg.excerpts_per_question],
                report.notes,
            )
            redraft.gap_round = True
            if len(redraft.points) >= len(report.findings[i].points):
                report.findings[i] = redraft
    elif weak:
        report.notes.append("Gap check skipped: not enough LLM calls left in the budget.")

    # 5. Synthesis (always has its reserved call).
    status("Writing the report…")
    findings_text = "\n\n".join(
        f"Sub-question: {f.question}\nEvidence: {f.evidence}\n"
        + ("\n".join(f"- {t} {''.join(c)}" for t, c in f.points) or "- (nothing found)")
        + (f"\nNot covered: {f.missing}" if f.missing else "")
        for f in report.findings
    )
    budget.spend()
    try:
        synth = llm.generate_structured(
            "worker",
            [
                {"role": "system", "content": _SYNTH_SYSTEM},
                {
                    "role": "user",
                    "content": f"Question: {question}\n\nFindings:\n\n{findings_text}",
                },
            ],
            Synthesis,
        )
        report.summary, report.implications, report.gaps = (
            synth.summary,
            synth.implications,
            synth.gaps,
        )
    except StructuredOutputError:
        report.notes.append("Synthesis failed; see the findings below.")
    report.llm_calls = budget.used
    return report

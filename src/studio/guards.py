"""Safety guards: cloud-model block, path sandbox, PHI scan."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


class GuardError(ValueError):
    """Raised when a guard rejects an input. The message is user-facing."""


# --- Cloud models ---------------------------------------------------------------------------


def is_cloud_model(name: str) -> bool:
    """True if an Ollama model name refers to a cloud-hosted model (``:cloud`` / ``-cloud``)."""
    lowered = name.strip().lower()
    return ":cloud" in lowered or "-cloud" in lowered


def check_model_allowed(name: str, *, block_cloud: bool = True) -> str:
    """Return ``name`` unchanged, or raise :class:`GuardError` if it is a blocked cloud model."""
    if block_cloud and is_cloud_model(name):
        raise GuardError(
            f"Model '{name}' is a cloud model and is blocked. Use a local model such as qwen3:8b."
        )
    return name


# --- Path sandbox ---------------------------------------------------------------------------


def resolve_in_sandbox(root: str | Path, candidate: str | Path) -> Path:
    """Resolve ``candidate`` (relative to ``root`` unless absolute) and ensure it stays inside.

    Symlinks are resolved first, so a link pointing outside the sandbox is rejected too.
    """
    root_resolved = Path(root).resolve()
    path = Path(candidate)
    if not path.is_absolute():
        path = root_resolved / path
    resolved = path.resolve()
    if not resolved.is_relative_to(root_resolved):
        raise GuardError(f"Path '{candidate}' is outside the sandbox '{root_resolved}'.")
    return resolved


# --- PHI scan -------------------------------------------------------------------------------


@dataclass(frozen=True)
class PhiHit:
    """One possible PHI match. ``excerpt`` is masked so the hit itself does not leak PHI."""

    kind: str
    line: int
    excerpt: str


_SSN = re.compile(r"\b(?!000|666|9\d\d)\d{3}-(?!00)\d{2}-(?!0000)\d{4}\b")
_MRN = re.compile(r"\b(?:MRN|medical record(?: number| no\.?)?)\s*[:#]?\s*[A-Z0-9-]{5,}\b", re.I)
_DOB = re.compile(
    r"\b(?:DOB|date of birth|birth ?date)\s*[:#]?\s*"
    r"(?:\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{4}-\d{2}-\d{2})",
    re.I,
)
_PHONE = re.compile(r"(?:\+1[\s.-]?)?\(?\b\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}\b")
# "Patient: Jane Doe", "Member name - John Smith"
_PERSON = re.compile(
    r"\b(?i:patient|member|subscriber|beneficiary)(?i: name)?\s*[:\-]\s*[A-Z][a-z]+ [A-Z][a-z]+"
)


def _mask(text: str) -> str:
    return re.sub(r"\d", "#", text.strip())[:80]


def scan_phi(text: str) -> list[PhiHit]:
    """Scan text for likely PHI: SSNs, MRN-like IDs, DOBs, and a phone number next to a name.

    This is a coarse warning heuristic (RFPs should not contain PHI), not a de-identification tool.
    """
    hits: list[PhiHit] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        for kind, pattern in (("ssn", _SSN), ("mrn", _MRN), ("dob", _DOB)):
            hits.extend(PhiHit(kind, lineno, _mask(m.group())) for m in pattern.finditer(line))
        if _PHONE.search(line) and _PERSON.search(line):
            hits.append(PhiHit("phone_name", lineno, _mask(line)))
    return hits

"""Plain-text/markdown views shared by the CLI and the chat router (no I/O, no next-step hints).

Keeping formatting here means ``studio <command>`` and ``/<command>`` in chat say the same thing.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

from studio.blocks import Block, HarvestReport
from studio.ingest import FilePhiHit, IngestReport
from studio.rag import LIBRARY_COLLECTIONS, library_index


def phi_hits_text(hits: Sequence[FilePhiHit]) -> str:
    """One line per possible PHI match (masked)."""
    return "\n".join(
        f"  - {h.file}" + (f", p.{h.page}" if h.page else "") + f": {h.kind} ({h.excerpt})"
        for h in hits
    )


def ingest_report_text(report: IngestReport) -> str:
    """What an ingest run did (assumes it wasn't blocked)."""
    lines = [
        f"{label}: {', '.join(names)}"
        for label, names in (
            ("new", report.new),
            ("changed", report.changed),
            ("unchanged", report.unchanged),
            ("removed", report.removed),
        )
        if names
    ]
    lines += [f"skipped {name}: {reason}" for name, reason in report.skipped.items()]
    if report.phi_hits:
        lines.append(f"Warning: ingested despite {len(report.phi_hits)} possible PHI matches.")
    lines.append(f"Indexed {report.chunks_added} new chunks ({report.total_chunks} total).")
    return "\n".join(lines)


def phi_blocked_text(report: IngestReport) -> str:
    """Explains why nothing was ingested."""
    return (
        "Possible PHI found (RFPs should not contain PHI). Nothing was ingested:\n"
        + phi_hits_text(report.phi_hits)
    )


def status_text(info: dict[str, Any], loaded: Sequence[str] | None) -> str:
    """Opportunity pipeline status. ``loaded`` is None when Ollama isn't reachable."""
    lines = [f"Opportunity: {info['id']}" + (f" — {info['title']}" if info["title"] else "")]
    if info["files"]:
        lines.append(f"Ingested: {len(info['files'])} files, {info['chunks']} chunks")
        lines += [f"  - {name} ({count} chunks)" for name, count in info["files"].items()]
    else:
        lines.append("Ingested: nothing yet")
    stale = " (stale: files changed since; rebuild the digest)" if info["digest_stale"] else ""
    lines.append(f"Digest: {'yes' + stale if info['digest'] else 'no'}")
    lines += [f"{key.capitalize()}: {'yes' if info[key] else 'no'}" for key in ("outline", "deck")]
    lines.append(f"Renders: {', '.join(info['renders']) or 'none'}")
    if loaded is None:
        lines.append("Loaded model: unknown (Ollama not reachable)")
    else:
        lines.append(f"Loaded model: {', '.join(loaded) or 'none'}")
    return "\n".join(lines)


def status_next(info: dict[str, Any]) -> str:
    """The obvious next command for an opportunity (slash form)."""
    if not info["files"]:
        return "`/ingest` your RFP files"
    if not info["digest"] or info["digest_stale"]:
        return '`/ask "<question>"` or `/digest`'
    if not info["outline"]:
        return "`/outline`"
    if not info["deck"]:
        return "`/deck`"
    return "`/render`"


def harvest_report_text(report: HarvestReport) -> str:
    """What a harvest run did."""
    lines = [
        f"Blocks: {len(report.new)} new, {len(report.refreshed)} refreshed, "
        f"{len(report.protected)} protected (edited), {report.unchanged} unchanged sources, "
        f"{report.skipped} skipped (not reusable)."
    ]
    if report.flagged:
        lines.append(f"Needs review ({len(report.flagged)}): {', '.join(report.flagged)}")
    lines += [f"Failed: {failure}" for failure in report.failed]
    return "\n".join(lines)


def blocks_text(hits: Sequence[tuple[Block, float]], show_scores: bool) -> str:
    """Block list (or search results)."""
    return "\n".join(
        f"- [{b.slide_type}] {b.id}"
        + (f" ({score:.2f})" if show_scores else "")
        + f": {b.title}"
        + (" ⚠ needs review" if b.needs_review else "")
        for b, score in hits
    )


def flags_text(flagged: dict[str, list[str]]) -> str:
    """Review flags per slide ('' if none)."""
    if not flagged:
        return ""
    lines = ["Please review:"]
    lines += [f"  - {slide_id}: {flag}" for slide_id, flags in flagged.items() for flag in flags]
    return "\n".join(lines)


def library_report_text(name: str, report: IngestReport) -> str:
    """One library collection's indexing result (assumes it wasn't blocked)."""
    parts = [f"{len(report.new)} new", f"{len(report.changed)} changed"]
    parts += [f"{len(report.unchanged)} unchanged", f"{len(report.removed)} removed"]
    lines = [f"{name}: {', '.join(parts)}; {report.total_chunks} chunks indexed."]
    lines += [f"  skipped {file}: {reason}" for file, reason in report.skipped.items()]
    return "\n".join(lines)


def library_status_text(root: Path) -> str:
    """What is indexed in each library collection."""
    lines = []
    for name in LIBRARY_COLLECTIONS:
        index = library_index(root, name)
        lines.append(f"{name}: {len(index.files())} files, {len(index)} chunks")
        lines += [f"  - {f} ({index.file_chunk_count(f)} chunks)" for f in index.files()]
    return "\n".join(lines)

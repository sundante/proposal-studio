"""``studio smoke``: an end-to-end check of a real install, on the real local models.

Runs a synthetic Acme Health Plan RFP through the chat router in a throwaway project folder
(a copy of your config and the sample template): /new → /ingest → /ask → /digest → /outline →
/deck → /render. Prints each step's outcome and time; returns True if every step passed.
"""

from __future__ import annotations

import shutil
import tempfile
import time
from collections.abc import Callable
from pathlib import Path

from studio.llm import LLMClient
from studio.router import Router, RouterContext
from studio.samples import make_pdf

STEPS: list[tuple[str, str, str]] = [  # (message, expected text, label)
    ("/new smoke-test Smoke test (synthetic)", "Created", "create opportunity"),
    ("", "Indexed", "ingest synthetic RFP"),
    ("When are proposals due?", "March 15, 2027", "cited answer"),
    ("/digest", "## RFP digest", "digest"),
    ("/outline", "## Outline", "outline"),
    ("/deck", "Wrote", "deck"),
    ("/render", "no errors", "render (QA)"),
]


def run_smoke(
    root: Path,
    llm_factory: Callable[[], LLMClient],
    *,
    keep: bool = False,
    log: Callable[[str], None] = print,
) -> bool:
    """Run the smoke test; ``root`` supplies config/ and the sample template."""
    tmp = Path(tempfile.mkdtemp(prefix="studio-smoke-"))
    try:
        shutil.copytree(root / "config", tmp / "config")
        (tmp / "config" / "overrides.yaml").unlink(missing_ok=True)
        if (root / "config" / "overrides.yaml").exists():  # keep the user's model choices
            shutil.copy2(root / "config" / "overrides.yaml", tmp / "config" / "overrides.yaml")
        shutil.copytree(root / "templates" / "sample", tmp / "templates" / "sample")
        rfp = make_pdf(tmp / "acme_rfp.pdf")
        router = Router(RouterContext(tmp, llm_factory))
        sess = router.session("smoke")
        ok = True
        for message, expected, label in STEPS:
            start = time.perf_counter()
            reply = router.reply(message, [rfp] if label.startswith("ingest") else [], sess)
            seconds = time.perf_counter() - start
            passed = expected in reply and "⚠" not in reply.split("\n", 2)[-1][:200]
            ok &= passed
            log(f"{'PASS' if passed else 'FAIL'}  {label:<22} {seconds:6.1f}s")
            if not passed:
                log("      " + reply.strip().replace("\n", "\n      ")[:800])
                break
        log("Smoke test passed." if ok else "Smoke test FAILED.")
        if keep:
            log(f"Kept {tmp}")
        return ok
    finally:
        if not keep:
            shutil.rmtree(tmp, ignore_errors=True)

"""``studio bench``: time each route against the performance budget (spec §15) on real models.

Runs in a throwaway copy of the project (like ``studio smoke``) with a synthetic RFP. With
``cpu_only`` every model role gets Ollama's ``num_gpu: 0``, approximating a CPU-only laptop.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import yaml

from studio import config as cfgmod
from studio.llm import LLMClient, OllamaClient
from studio.router import Router, RouterContext
from studio.samples import make_pdf

# (label, budget seconds or None, description of the budget)
BUDGET = {
    "rules routing": (1, "< 1 s"),
    "classifier routing": (15, "< 15 s"),
    "/ask first token": (60, "< 60 s"),
    "/digest": (None, "no budget (map-reduce)"),
    "/deck one slide": (120, "< 2 min"),
    "/deck full": (1200, "10–20 min acceptable"),
    "/render": (10, "< 10 s"),
}


@dataclass
class Timing:
    label: str
    seconds: float
    ok: bool | None  # None when there is no budget


def _rss_mb() -> float | None:
    try:
        import resource

        usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return usage / (1024 * 1024) if os.uname().sysname == "Darwin" else usage / 1024
    except (ImportError, AttributeError):
        return None


def run_bench(
    root: Path,
    *,
    cpu_only: bool = False,
    llm_factory: Callable[[Path], LLMClient] | None = None,
    log: Callable[[str], None] = print,
) -> list[Timing]:
    """Run the benchmark and print a table; returns the timings."""
    tmp = Path(tempfile.mkdtemp(prefix="studio-bench-"))
    try:
        shutil.copytree(root / "config", tmp / "config")
        shutil.copytree(root / "templates" / "sample", tmp / "templates" / "sample")
        if cpu_only:
            roles = cfgmod.load_config(tmp).models.roles
            overrides = {"models": {"roles": {r: {"num_gpu": 0} for r in roles}}}
            (tmp / "config" / "overrides.yaml").write_text(
                yaml.safe_dump(overrides), encoding="utf-8"
            )
        factory = llm_factory or (lambda home: OllamaClient(cfgmod.load_config(home).models))
        router = Router(RouterContext(tmp, lambda: factory(tmp)))
        sess = router.session("bench")
        rfp = make_pdf(tmp / "acme_rfp.pdf")
        router.reply("/new bench Benchmark (synthetic)", session=sess)
        router.reply("", [rfp], sess)
        cfg = cfgmod.load_config(tmp)
        timings: list[Timing] = []

        def record(label: str, seconds: float) -> None:
            budget = BUDGET[label][0]
            timings.append(Timing(label, seconds, None if budget is None else seconds <= budget))

        start = time.perf_counter()
        router.decide("When are proposals due?", [], sess, cfg, lambda: factory(tmp))
        record("rules routing", time.perf_counter() - start)

        start = time.perf_counter()
        router.decide("list what the client needs from us", [], sess, cfg, lambda: factory(tmp))
        record("classifier routing", time.perf_counter() - start)

        async def first_token() -> float:
            begin = time.perf_counter()
            async for chunk in router.handle("When are proposals due?", [], sess):
                if not chunk.startswith("→"):
                    return time.perf_counter() - begin
            return time.perf_counter() - begin

        record("/ask first token", asyncio.run(first_token()))
        for label, message in (
            ("/digest", "/digest"),
            ("/deck one slide", "/deck understanding"),
            ("/deck full", "/deck"),
            ("/render", "/render"),
        ):
            if label == "/deck one slide":
                router.reply("/outline", session=sess)
            begin = time.perf_counter()
            router.reply(message, session=sess)
            record(label, time.perf_counter() - begin)

        mode = "CPU only (num_gpu=0)" if cpu_only else "default (GPU if available)"
        log(f"Benchmark — {mode}; worker {cfg.models.roles['worker'].model}")
        log(f"{'step':<20} {'seconds':>9}  budget")
        for t in timings:
            mark = "—" if t.ok is None else ("✅" if t.ok else "❌")
            log(f"{t.label:<20} {t.seconds:9.1f}  {BUDGET[t.label][1]} {mark}")
        rss = _rss_mb()
        if rss:
            log(f"peak RSS of this process (studio): {rss:.0f} MB")
        return timings
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

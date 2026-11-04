"""Agent adapters as seen by the rest of `studio`: list, describe, and run the 3-step flow.

The command templates live in ``config/agents.yaml``; :mod:`studio.agents.base` does the
sandboxing. These helpers format results for chat and the CLI.
"""

from __future__ import annotations

import shutil

from studio.agents.base import AgentRun
from studio.config import AgentsConfig

SLOW_WARNING = (
    "_Agent runs on this laptop are slow (often minutes per step) and small local models may "
    "not use their file tools well._"
)


def available_agents(cfg: AgentsConfig) -> list[tuple[str, str, bool, str]]:
    """(name, label, ready, reason) per configured agent."""
    out = []
    for name, spec in cfg.agents.items():
        if not spec.enabled:
            out.append((name, spec.label, False, spec.note or "disabled in agents.yaml"))
        elif shutil.which(spec.plan_cmd[0]) is None:
            out.append((name, spec.label, False, f"`{spec.plan_cmd[0]}` not installed"))
        else:
            out.append((name, spec.label, True, ""))
    return out


def agents_text(cfg: AgentsConfig) -> str:
    """Markdown list of agents and whether they can run."""
    lines = ["## Agents"]
    for name, label, ready, reason in available_agents(cfg):
        lines.append(f"- `{name}` — {label}: " + ("ready" if ready else f"unavailable ({reason})"))
    return "\n".join(lines)


def run_text(run: AgentRun, limit: int = 4000) -> str:
    """Readable summary of a plan/apply run."""
    status = (
        "✅ finished"
        if run.ok
        else (
            "⏱ timed out"
            if run.timed_out
            else "⏹ cancelled"
            if run.cancelled
            else f"❌ exit code {run.returncode}"
        )
    )
    output = run.output.strip() or "(no output)"
    if len(output) > limit:
        output = output[:limit] + "\n… (truncated; full log below)"
    parts = [
        f"**{run.agent} · {run.phase}** — {status} in {run.seconds:.0f}s",
        f"```\n{output}\n```",
    ]
    if run.phase == "apply":
        if run.changed:
            parts.append("Changed files: " + ", ".join(f"`{p}`" for p in run.changed))
            if run.diff:
                diff = run.diff if len(run.diff) <= limit else run.diff[:limit] + "\n… (truncated)"
                parts.append(f"```diff\n{diff}\n```")
        else:
            parts.append("No files changed.")
    parts.append(f"Log: `{run.log_path}`")
    return "\n\n".join(parts)

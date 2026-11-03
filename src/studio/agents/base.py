"""Agent sandbox and process runner (plan → approve → apply → approve copy-back).

- **Plan** runs in a throwaway copy of the sandbox, deleted afterwards, so nothing an agent does
  while "planning" survives, even if its CLI has no true read-only mode.
- **Apply** runs in a fresh working copy (``<sandbox>/work``). Changed files are diffed, and
  copied back to the opportunity only by :func:`copy_back`, after the user approves.
- Every run: an isolated HOME inside the sandbox, an allowlisted environment plus the agent's
  own ``env``, a timeout, cancellation, and a log under ``<sandbox>/logs/``.
"""

from __future__ import annotations

import difflib
import hashlib
import os
import queue
import shutil
import signal
import subprocess
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from pydantic import ValidationError

from studio.config import AgentsConfig, AgentSpec
from studio.deck.schemas import Deck
from studio.guards import GuardError, check_model_allowed, resolve_in_sandbox

LineFn = Callable[[str], None]
MAX_DIFF_BYTES = 200_000


class AgentError(ValueError):
    """The agent could not run. User-facing."""


@dataclass
class AgentRun:
    """Result of one plan or apply run."""

    agent: str
    phase: str  # plan | apply
    command: list[str]
    returncode: int | None
    output: str
    log_path: Path
    seconds: float
    timed_out: bool = False
    cancelled: bool = False
    changed: list[str] = field(default_factory=list)  # relative paths (apply only)
    diff: str = ""

    @property
    def ok(self) -> bool:
        return self.returncode == 0 and not self.timed_out and not self.cancelled


def sandbox_dir(cfg: AgentsConfig, root: Path, opp_id: str) -> Path:
    """``workspace/<opp>/agent`` (from ``sandbox_root``), resolved under the project root."""
    path = Path(cfg.sandbox_root.replace("{opp}", opp_id))
    return (path if path.is_absolute() else root / path).resolve()


def resolve_command(argv: Sequence[str]) -> list[str]:
    """Resolve the executable (``.cmd``/``.exe`` shims on Windows via PATHEXT)."""
    exe = shutil.which(argv[0])
    if exe is None:
        raise AgentError(
            f"`{argv[0]}` isn't installed or not on PATH. Install it (see docs/agents.md), "
            "then try again."
        )
    return [exe, *argv[1:]]


def fill(template: Sequence[str], spec: AgentSpec, prompt: str, workdir: Path) -> list[str]:
    """Fill placeholders in one command template."""
    values = {"{prompt}": prompt, "{model}": spec.model, "{workdir}": str(workdir)}
    filled = []
    for part in template:
        for key, value in values.items():
            part = part.replace(key, value)
        filled.append(part)
    return filled


def build_env(cfg: AgentsConfig, spec: AgentSpec, home: Path) -> dict[str, str]:
    """Allowlisted parent env + isolated HOME + the agent's own env (nothing else leaks)."""
    env = {k: os.environ[k] for k in cfg.env_allowlist if k in os.environ}
    home.mkdir(parents=True, exist_ok=True)
    env.update(
        {"HOME": str(home), "USERPROFILE": str(home), "XDG_CONFIG_HOME": str(home / ".config")}
    )
    env.update(
        {"XDG_CACHE_HOME": str(home / ".cache"), "XDG_DATA_HOME": str(home / ".local/share")}
    )
    env.update(spec.env)
    return env


def _snapshot(folder: Path) -> dict[str, str]:
    digests = {}
    for path in folder.rglob("*"):
        if (
            path.is_file()
            and not path.is_symlink()
            and ".home" not in path.relative_to(folder).parts
        ):
            digests[path.relative_to(folder).as_posix()] = hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
    return digests


def _text(path: Path) -> list[str] | None:
    try:
        data = path.read_bytes()
    except OSError:
        return None
    if b"\0" in data[:4096] or len(data) > MAX_DIFF_BYTES:
        return None
    return data.decode("utf-8", errors="replace").splitlines()


def _kill(proc: subprocess.Popen) -> None:
    try:
        if os.name == "nt":
            proc.kill()
        else:
            os.killpg(proc.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        pass


class AgentRunner:
    """Runs one configured agent for an opportunity."""

    def __init__(
        self,
        cfg: AgentsConfig,
        name: str,
        root: Path,
        opp_dir: Path,
        *,
        block_cloud: bool = True,
    ) -> None:
        if name not in cfg.agents:
            names = ", ".join(cfg.agents) or "none configured"
            raise AgentError(f"No agent '{name}'. Available: {names}.")
        self.cfg, self.name, self.spec = cfg, name, cfg.agents[name]
        if not self.spec.enabled:
            note = f" {self.spec.note}" if self.spec.note else ""
            raise AgentError(f"Agent '{name}' is disabled in config/agents.yaml.{note}")
        try:
            check_model_allowed(self.spec.model, block_cloud=block_cloud)
        except GuardError as exc:
            raise AgentError(str(exc)) from exc
        self.opp_dir = opp_dir
        self.sandbox = sandbox_dir(cfg, root, opp_dir.name)
        self.workdir = self.sandbox / "work"
        self.cancel_event = threading.Event()

    # -- working copies --

    def _prepare(self, folder: Path) -> None:
        if folder.exists():
            shutil.rmtree(folder)
        folder.mkdir(parents=True)
        for name in self.cfg.copy_in:
            src = resolve_in_sandbox(self.opp_dir, name)
            if src.is_file():
                shutil.copy2(src, resolve_in_sandbox(folder, name))
        for name, content in self.spec.files.items():
            target = resolve_in_sandbox(folder, name)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content.replace("{model}", self.spec.model), encoding="utf-8")

    # -- process --

    def _run(
        self, phase: str, template: Sequence[str], prompt: str, folder: Path, on_line: LineFn | None
    ) -> AgentRun:
        argv = resolve_command(fill(template, self.spec, prompt, folder))
        logs = self.sandbox / "logs"
        logs.mkdir(parents=True, exist_ok=True)
        log_path = logs / f"{datetime.now(UTC).strftime('%Y%m%dT%H%M%S%f')}-{self.name}-{phase}.log"
        env = build_env(self.cfg, self.spec, self.sandbox / ".home")
        start = time.monotonic()
        kwargs: dict = (
            {"start_new_session": True}
            if os.name != "nt"
            else {
                "creationflags": subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
            }
        )
        proc = subprocess.Popen(
            argv,
            cwd=folder,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            **kwargs,
        )
        lines: queue.Queue[str | None] = queue.Queue()

        def reader() -> None:
            assert proc.stdout is not None
            for line in proc.stdout:
                lines.put(line.rstrip("\n"))
            lines.put(None)

        threading.Thread(target=reader, daemon=True).start()
        output: list[str] = []
        timed_out = cancelled = False
        deadline = start + self.cfg.default_timeout_s
        while True:
            try:
                line = lines.get(timeout=0.2)
            except queue.Empty:
                line = ""
            if line is None:
                break
            if line:
                output.append(line)
                if on_line:
                    on_line(line)
            if self.cancel_event.is_set():
                cancelled = True
            elif time.monotonic() > deadline:
                timed_out = True
            if cancelled or timed_out:
                _kill(proc)
                break
        try:
            returncode = proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            _kill(proc)
            returncode = None
        text = "\n".join(output)
        header = f"$ {' '.join(argv[:1] + ['…'])}\nphase={phase} cwd={folder}\n"
        log_path.write_text(header + text + "\n", encoding="utf-8")
        return AgentRun(
            self.name,
            phase,
            argv,
            returncode,
            text,
            log_path,
            time.monotonic() - start,
            timed_out,
            cancelled,
        )

    # -- public API --

    def plan(self, task: str, on_line: LineFn | None = None) -> AgentRun:
        """Run the plan command in a throwaway copy (deleted afterwards)."""
        scratch = self.sandbox / "plan"
        self._prepare(scratch)
        try:
            return self._run("plan", self.spec.plan_cmd, task, scratch, on_line)
        finally:
            shutil.rmtree(scratch, ignore_errors=True)

    def apply(self, task: str, on_line: LineFn | None = None) -> AgentRun:
        """Run the apply command in a fresh working copy and diff what changed."""
        self._prepare(self.workdir)
        before = _snapshot(self.workdir)
        run = self._run("apply", self.spec.apply_cmd, task, self.workdir, on_line)
        after = _snapshot(self.workdir)
        changed = sorted(p for p in set(before) | set(after) if before.get(p) != after.get(p))
        diffs = []
        for rel in changed:
            old = _text(self.opp_dir / rel) if rel in before else []
            new = _text(self.workdir / rel) if rel in after else []
            if old is None or new is None:
                diffs.append(f"(binary or large file changed: {rel})")
                continue
            diffs.extend(difflib.unified_diff(old, new, f"a/{rel}", f"b/{rel}", lineterm=""))
        run.changed, run.diff = changed, "\n".join(diffs)
        return run

    def copy_back(self) -> list[str]:
        """Copy approved results from the working copy into the opportunity.

        Changed ``copy_in`` files replace the originals (the old version goes to ``history/``);
        any other new or changed file lands in ``<sandbox>/results/``. Symlinks and anything
        resolving outside the working copy are skipped. ``deck.json`` must still be a valid deck.
        """
        if not self.workdir.exists():
            raise AgentError("Nothing to copy back: run the agent's apply step first.")
        changed = list(_snapshot(self.workdir))
        originals = set(self.cfg.copy_in)
        copied = []
        for rel in changed:
            src = self.workdir / rel
            try:
                src = resolve_in_sandbox(self.workdir, rel)
            except GuardError:
                continue
            if rel in self.spec.files:
                continue  # our own config files (opencode.json, …)
            if rel in originals:
                dest = self.opp_dir / rel
                if dest.exists() and dest.read_bytes() == src.read_bytes():
                    continue
                if rel == "deck.json":
                    try:
                        Deck.model_validate_json(src.read_text(encoding="utf-8"))
                    except (ValidationError, ValueError) as exc:
                        raise AgentError(
                            f"The agent's deck.json is not a valid deck, so it wasn't copied: {exc}"
                        ) from exc
                if dest.exists():
                    history = self.opp_dir / "history"
                    history.mkdir(exist_ok=True)
                    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%f")
                    shutil.copy2(dest, history / f"{Path(rel).stem}-{stamp}{Path(rel).suffix}")
                shutil.copy2(src, dest)
            else:
                dest = resolve_in_sandbox(self.sandbox / "results", rel)
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dest)
            copied.append(rel)
        return copied

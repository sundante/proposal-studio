import os
import sys
from pathlib import Path

import pytest

from studio.agents.adapters import available_agents, run_text
from studio.agents.base import AgentError, AgentRunner, build_env
from studio.config import AgentsConfig, AgentSpec
from studio.router import Router, RouterContext
from tests.conftest import REPO_ROOT, SAMPLE_DECK
from tests.fakes import FakeLLM

FAKE = str(REPO_ROOT / "tests" / "fixtures" / "fake_agent.py")


def spec(plan="plan", apply="apply", **kw) -> AgentSpec:
    return AgentSpec(
        label="Fake",
        plan_cmd=[sys.executable, FAKE, plan, "{prompt}"],
        apply_cmd=[sys.executable, FAKE, apply, "{prompt}"],
        model=kw.pop("model", "qwen3:8b"),
        **kw,
    )


def agents_cfg(timeout: int = 30, **agents) -> AgentsConfig:
    return AgentsConfig(default_timeout_s=timeout, agents=agents or {"fake": spec()})


@pytest.fixture
def opp(tmp_path: Path) -> Path:
    opp = tmp_path / "workspace" / "acme"
    opp.mkdir(parents=True)
    (opp / "deck.json").write_text(SAMPLE_DECK.read_text())
    return opp


def runner(cfg: AgentsConfig, opp: Path, name: str = "fake") -> AgentRunner:
    return AgentRunner(cfg, name, opp.parent.parent, opp)


def test_plan_apply_copy_back(opp: Path) -> None:
    r = runner(agents_cfg(), opp)
    lines: list[str] = []
    plan = r.plan("retitle slide 1", on_line=lines.append)
    assert plan.ok and "PLAN for: retitle slide 1" in plan.output and lines
    assert not (r.sandbox / "plan").exists()  # throwaway copy is gone
    assert plan.log_path.exists() and "PLAN for" in plan.log_path.read_text()

    applied = r.apply("retitle slide 1")
    assert applied.ok and applied.changed == ["deck.json", "notes.md"]
    assert '+      "title": "Retitled by agent",' in applied.diff
    assert "Retitled" not in (opp / "deck.json").read_text()  # nothing copied yet

    copied = r.copy_back()
    assert sorted(copied) == ["deck.json", "notes.md"]
    assert "Retitled by agent" in (opp / "deck.json").read_text()
    assert list((opp / "history").glob("deck-*.json"))  # previous version kept
    assert (r.sandbox / "results" / "notes.md").exists()
    assert "Changed files: `deck.json`, `notes.md`" in run_text(applied)


def test_invalid_deck_is_not_copied(opp: Path, tmp_path: Path) -> None:
    bad = tmp_path / "bad_agent.py"
    bad.write_text("from pathlib import Path\nPath('deck.json').write_text('{\"nope\": 1}')\n")
    cfg = agents_cfg(
        fake=AgentSpec(
            label="x",
            plan_cmd=[sys.executable, str(bad)],
            apply_cmd=[sys.executable, str(bad)],
            model="m",
        )
    )
    r = runner(cfg, opp)
    assert r.apply("x").changed == ["deck.json"]
    with pytest.raises(AgentError, match="not a valid deck"):
        r.copy_back()
    assert "Enterprise AI Platform" in (opp / "deck.json").read_text()


def test_timeout_kills(opp: Path) -> None:
    r = runner(agents_cfg(timeout=1, fake=spec(plan="sleep")), opp)
    run = r.plan("x")
    assert run.timed_out and not run.ok and run.seconds < 15
    assert "timed out" in run_text(run)


def test_failure_exit_code(opp: Path) -> None:
    run = runner(agents_cfg(fake=spec(plan="fail")), opp).plan("x")
    assert run.returncode == 3 and "exit code 3" in run_text(run)


def test_env_is_stripped_and_home_isolated(opp: Path, monkeypatch) -> None:
    monkeypatch.setenv("STUDIO_TEST_SECRET", "s3cret")
    r = runner(agents_cfg(fake=spec(plan="env", env={"AGENT_FLAG": "1"})), opp)
    out = r.plan("x").output
    assert "SECRET=<absent>" in out and "AGENT_FLAG=1" in out
    assert f"HOME={r.sandbox / '.home'}" in out
    env = build_env(r.cfg, r.spec, r.sandbox / ".home")
    assert "STUDIO_TEST_SECRET" not in env and env["USERPROFILE"] == str(r.sandbox / ".home")


@pytest.mark.skipif(os.name == "nt", reason="symlinks need privileges on Windows")
def test_escape_attempts_are_not_copied_back(opp: Path) -> None:
    r = runner(agents_cfg(fake=spec(apply="escape")), opp)
    run = r.apply("x")
    assert run.ok
    copied = r.copy_back()
    assert copied == []  # the symlink and the outside write are ignored
    assert not (opp / "link").exists()


def test_agent_files_written_with_model(opp: Path) -> None:
    cfg = agents_cfg(fake=spec(files={"agent.json": '{"model": "{model}"}'}))
    r = runner(cfg, opp)
    r.apply("x")
    assert (r.workdir / "agent.json").read_text() == '{"model": "qwen3:8b"}'
    assert "agent.json" not in r.copy_back()  # our own config never lands in results


def test_refusals(opp: Path) -> None:
    with pytest.raises(AgentError, match="No agent 'nope'"):
        runner(agents_cfg(), opp, "nope")
    with pytest.raises(AgentError, match="disabled"):
        runner(agents_cfg(fake=spec(enabled=False, note="Not tested.")), opp)
    with pytest.raises(AgentError, match="cloud"):
        runner(agents_cfg(fake=spec(model="qwen3-coder:480b-cloud")), opp)
    missing = AgentSpec(
        label="m", plan_cmd=["definitely-not-installed-cli"], apply_cmd=["x"], model="m"
    )
    with pytest.raises(AgentError, match="isn't installed"):
        runner(agents_cfg(fake=missing), opp).plan("x")
    ready = {n: ok for n, _l, ok, _r in available_agents(agents_cfg(fake=spec(), gone=missing))}
    assert ready == {"fake": True, "gone": False}


def test_router_agent_flow(studio_home: Path, monkeypatch) -> None:
    import yaml

    agents_yaml = studio_home / "config" / "agents.yaml"
    data = yaml.safe_load(agents_yaml.read_text())
    data["agents"]["fake"] = spec().model_dump()
    agents_yaml.write_text(yaml.safe_dump(data))
    decision = {"route": "agent", "alternative": "deck", "confidence": 0.95, "args": "fake fix it"}
    router = Router(RouterContext(studio_home, lambda: FakeLLM({"RouteDecision": decision})))
    sess = router.session("a")
    router.reply("/new acme", session=sess)
    (studio_home / "workspace" / "acme" / "deck.json").write_text(SAMPLE_DECK.read_text())

    out = router.reply("/agent fake retitle slide 1", session=sess)
    assert "PLAN for: retitle slide 1" in out and "`/approve` to let fake make the changes" in out
    out = router.reply("/approve", session=sess)
    assert "**fake · apply** — ✅ finished" in out and "Changed files" in out
    out = router.reply("/approve", session=sess)
    assert "Copied back: `deck.json`, `notes.md`" in out
    assert "Retitled by agent" in (studio_home / "workspace" / "acme" / "deck.json").read_text()

    assert "later steps run via `/approve`" in router.reply("/agent --apply fake x", session=sess)
    assert "disabled" in router.reply("/agent hermes do it", session=sess)
    out = router.reply("ask the agent to fix the deck", session=sess)  # classifier → held
    assert "→ routed to /agent (classifier, 0.95)" in out and "won't run it automatically" in out

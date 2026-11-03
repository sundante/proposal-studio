from pathlib import Path

import pytest
import yaml

from studio import config as cfgmod


def test_default_config_loads(studio_home: Path) -> None:
    cfg = cfgmod.load_config()
    assert cfg.models.roles["worker"].model == "qwen3:8b"
    assert cfg.models.block_cloud_models is True
    assert "ask" in cfg.routes.commands
    assert cfg.routes.aliases["q"] == "ask"
    assert [s.id for s in cfg.storyline.slides][0] == "title"


def test_set_shorthand_writes_overrides_only(studio_home: Path) -> None:
    base_before = (studio_home / "config" / "models.yaml").read_text()
    cfg = cfgmod.set_value("worker.model", "qwen3:4b")
    assert cfg.models.roles["worker"].model == "qwen3:4b"
    assert (studio_home / "config" / "models.yaml").read_text() == base_before
    overrides = yaml.safe_load((studio_home / "config" / "overrides.yaml").read_text())
    assert overrides == {"models": {"roles": {"worker": {"model": "qwen3:4b"}}}}
    assert cfgmod.load_config().models.roles["worker"].model == "qwen3:4b"


def test_set_parses_types_and_full_paths(studio_home: Path) -> None:
    cfg = cfgmod.set_value("auto_threshold", "0.5")
    assert cfg.routes.auto_threshold == 0.5
    cfg = cfgmod.set_value("models.think", "true")
    assert cfg.models.think is True


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("worker.model", "qwen3:480b-cloud"),
        ("router.model", "gpt-oss:120b:cloud"),
        ("auto_threshold", "1.5"),
        ("worker.num_ctx", "lots"),
        ("no_such_key", "1"),
        ("worker.nope", "1"),
    ],
)
def test_set_rejects_invalid(studio_home: Path, key: str, value: str) -> None:
    with pytest.raises(cfgmod.ConfigError):
        cfgmod.set_value(key, value)
    assert not (studio_home / "config" / "overrides.yaml").exists()


def test_reset_removes_overrides(studio_home: Path) -> None:
    cfgmod.set_value("worker.model", "qwen3:4b")
    cfg = cfgmod.reset()
    assert cfg.models.roles["worker"].model == "qwen3:8b"
    assert not (studio_home / "config" / "overrides.yaml").exists()


def test_unknown_key_in_yaml_is_rejected(studio_home: Path) -> None:
    path = studio_home / "config" / "models.yaml"
    path.write_text(path.read_text() + "surprise: 1\n")
    with pytest.raises(cfgmod.ConfigError, match="surprise"):
        cfgmod.load_config()


def test_cloud_agent_model_rejected(studio_home: Path) -> None:
    with pytest.raises(cfgmod.ConfigError, match="cloud"):
        cfgmod.set_value("agents.agents.opencode.model", "qwen3-coder:480b-cloud")

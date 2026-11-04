from pathlib import Path

from studio import config as cfgmod
from studio.views import commands_markdown
from tests.conftest import REPO_ROOT


def test_commands_doc_matches_routes() -> None:
    routes = cfgmod.load_config(REPO_ROOT).routes
    committed = (REPO_ROOT / "docs" / "commands.md").read_text(encoding="utf-8")
    assert committed == commands_markdown(routes), "run `studio docs`"
    for name in routes.commands:
        assert f"`/{name}`" in committed


def test_doc_links_resolve() -> None:
    import re

    for doc in [REPO_ROOT / "README.md", *(REPO_ROOT / "docs").glob("*.md")]:
        for target in re.findall(r"\]\(([^)#]+\.md)\)", doc.read_text(encoding="utf-8")):
            if target.startswith("http"):
                continue
            assert (doc.parent / target).exists(), f"{doc.name} links to missing {target}"


def test_bench_with_fake_models(tmp_path: Path) -> None:
    from studio.bench import BUDGET, run_bench
    from tests.test_router import fake_llm

    lines: list[str] = []
    timings = run_bench(REPO_ROOT, llm_factory=lambda _home: fake_llm(), log=lines.append)
    assert [t.label for t in timings] == list(BUDGET)
    assert all(t.ok is not False for t in timings), lines
    assert lines[0].startswith("Benchmark — default")


def test_tutorial_is_complete_offline_and_linked() -> None:
    import re

    html = (REPO_ROOT / "vibes" / "tutorial.html").read_text(encoding="utf-8")
    routes = cfgmod.load_config(REPO_ROOT).routes
    for name in routes.commands:
        assert f"<code>/{name}</code>" in html, f"tutorial is missing /{name}"
    # nothing loaded from the network (it must work offline)
    assert not re.search(r"<(script|link|img)[^>]+(src|href)=[\"']https?://", html)
    assert "@import" not in html
    ids = set(re.findall(r'id="([^"]+)"', html))
    for anchor in re.findall(r'href="#([^"]+)"', html):
        assert anchor in ids, f"broken anchor #{anchor}"
    for target in re.findall(r'href="([^"#:]+\.md)"', html):
        assert (REPO_ROOT / target).exists(), f"tutorial links to missing {target}"
    assert "README.md" in html and "tutorial.html" in (REPO_ROOT / "README.md").read_text()

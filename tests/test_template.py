import io
import json
import zipfile
from pathlib import Path

import pytest
from pptx import Presentation

from studio import config as cfgmod
from studio.render.inspect_template import (
    TemplateError,
    inspect_template,
    layouts_table,
    open_template,
    write_layouts_json,
)
from tests.conftest import REPO_ROOT

PRES = "application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"
TMPL = "application/vnd.openxmlformats-officedocument.presentationml.template.main+xml"


def test_sample_template_matches_layout_map(sample_template: Path) -> None:
    data = inspect_template(sample_template)
    assert data["slide_width_in"] == pytest.approx(13.33, abs=0.01)
    assert data["existing_slides"] == 2
    layouts = {lay["name"]: {p["idx"] for p in lay["placeholders"]} for lay in data["layouts"]}
    cfg = cfgmod.load_config(REPO_ROOT).layout_map
    for slide_type, spec in cfg.layouts.items():
        assert spec.layout in layouts, slide_type
        assert set(spec.placeholders.values()) <= layouts[spec.layout], slide_type


def test_placeholders_fit_on_widescreen(sample_template: Path) -> None:
    data = inspect_template(sample_template)
    for layout in data["layouts"]:
        for ph in layout["placeholders"]:
            assert ph["left"] + ph["width"] <= data["slide_width_in"] + 0.01, (layout["name"], ph)
            assert ph["height"] > 0, (layout["name"], ph)


def test_committed_sample_template_is_current(sample_template: Path) -> None:
    committed = REPO_ROOT / "templates" / "sample" / "proposal-sample.pptx"
    fresh, saved = inspect_template(sample_template), inspect_template(committed)
    assert saved["layouts"] == fresh["layouts"], "re-run `studio template sample`"


def test_write_layouts_json_and_table(sample_template: Path, tmp_path: Path) -> None:
    copy = tmp_path / "firm.pptx"
    copy.write_bytes(sample_template.read_bytes())
    out, data = write_layouts_json(copy)
    assert out == tmp_path / "firm.layouts.json"
    assert json.loads(out.read_text())["layouts"][4]["name"] == "Comparison"
    table = layouts_table(data)
    assert "[4] Comparison: 0=TITLE, 1=BODY, 2=OBJECT, 3=BODY, 4=OBJECT" in table
    assert "DATE" not in table


def _as_potx(src: Path, dest: Path) -> Path:
    out = io.BytesIO()
    with zipfile.ZipFile(src) as zin, zipfile.ZipFile(out, "w") as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename == "[Content_Types].xml":
                data = data.replace(PRES.encode(), TMPL.encode())
            zout.writestr(item, data)
    dest.write_bytes(out.getvalue())
    return dest


def test_potx_opens_via_content_type_patch(sample_template: Path, tmp_path: Path) -> None:
    potx = _as_potx(sample_template, tmp_path / "firm.potx")
    before = potx.read_bytes()
    with pytest.raises(ValueError):
        Presentation(str(potx))  # python-pptx refuses the template content type
    prs = open_template(potx)
    assert len(prs.slide_layouts) == 11
    assert potx.read_bytes() == before  # never modified on disk


def test_open_template_errors(tmp_path: Path) -> None:
    with pytest.raises(TemplateError, match="not found"):
        open_template(tmp_path / "missing.pptx")
    bad = tmp_path / "bad.pptx"
    bad.write_text("not a zip")
    with pytest.raises(TemplateError, match="Save As"):
        open_template(bad)
    keynote = tmp_path / "deck.key"
    keynote.write_text("x")
    with pytest.raises(TemplateError, match=".pptx or .potx"):
        open_template(keynote)

"""Open templates (.pptx / .potx) and dump their layouts and placeholders.

``studio template inspect <file>`` writes ``<file stem>.layouts.json`` next to the template so
the user can fill in ``config/layout_map.yaml``.
"""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path
from typing import Any

from pptx import Presentation
from pptx.exc import PackageNotFoundError
from pptx.presentation import Presentation as PresentationType
from pptx.util import Emu

_PRESENTATION_CT = (
    "application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"
)
_TEMPLATE_CT = "application/vnd.openxmlformats-officedocument.presentationml.template.main+xml"


class TemplateError(ValueError):
    """The template could not be opened or doesn't match the layout map. User-facing."""


def _potx_as_pptx(path: Path) -> io.BytesIO:
    """In-memory copy of a .potx with its main content type patched to a presentation."""
    out = io.BytesIO()
    with zipfile.ZipFile(path) as zin, zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename == "[Content_Types].xml":
                data = data.replace(_TEMPLATE_CT.encode(), _PRESENTATION_CT.encode())
            zout.writestr(item, data)
    out.seek(0)
    return out


def open_template(path: Path) -> PresentationType:
    """Open a .pptx or .potx template. The file on disk is never modified."""
    if not path.exists():
        raise TemplateError(f"Template not found: {path}. Check `template:` in layout_map.yaml.")
    suffix = path.suffix.lower()
    if suffix not in {".pptx", ".potx"}:
        raise TemplateError(f"{path.name}: templates must be .pptx or .potx.")
    try:
        return Presentation(_potx_as_pptx(path) if suffix == ".potx" else str(path))
    except (zipfile.BadZipFile, KeyError, ValueError, PackageNotFoundError) as exc:
        raise TemplateError(
            f"Could not open {path.name} as a PowerPoint template ({exc}). "
            "Try opening it in PowerPoint and using Save As .pptx."
        ) from exc


def _inches(value: int | None) -> float | None:
    return round(Emu(value).inches, 2) if value is not None else None


def inspect_template(path: Path) -> dict[str, Any]:
    """Slide size, existing slide count, and every layout with its placeholders."""
    prs = open_template(path)
    layouts = []
    for index, layout in enumerate(prs.slide_layouts):
        placeholders = []
        for ph in layout.placeholders:
            fmt = ph.placeholder_format
            placeholders.append(
                {
                    "idx": fmt.idx,
                    "type": fmt.type.name if fmt.type is not None else None,
                    "name": ph.name,
                    "left": _inches(ph.left),
                    "top": _inches(ph.top),
                    "width": _inches(ph.width),
                    "height": _inches(ph.height),
                }
            )
        layouts.append({"index": index, "name": layout.name, "placeholders": placeholders})
    return {
        "template": path.name,
        "slide_width_in": _inches(prs.slide_width),
        "slide_height_in": _inches(prs.slide_height),
        "existing_slides": len(prs.slides),
        "layouts": layouts,
    }


def write_layouts_json(path: Path) -> tuple[Path, dict[str, Any]]:
    """Write ``<stem>.layouts.json`` next to the template; return its path and the data."""
    data = inspect_template(path)
    out = path.with_name(f"{path.stem}.layouts.json")
    out.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return out, data


def layouts_table(data: dict[str, Any]) -> str:
    """Compact text table of layouts and content placeholders (skips date/footer/number)."""
    skip = {"DATE", "FOOTER", "SLIDE_NUMBER"}
    lines = [
        f"{data['template']}: {data['slide_width_in']}x{data['slide_height_in']} in, "
        f"{data['existing_slides']} existing slides"
    ]
    for layout in data["layouts"]:
        phs = ", ".join(
            f"{p['idx']}={p['type'] or '?'}"
            for p in layout["placeholders"]
            if p["type"] not in skip
        )
        lines.append(
            f"  [{layout['index']}] {layout['name']}: {phs or '(no content placeholders)'}"
        )
    return "\n".join(lines)

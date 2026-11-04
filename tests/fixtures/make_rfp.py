"""Synthetic Acme Health Plan RFP fixtures (generator lives in ``studio.samples``).

Usage: ``python -m tests.fixtures.make_rfp OUTDIR``.
"""

from __future__ import annotations

import sys
from pathlib import Path

from studio.samples import (  # noqa: F401 - re-exported for tests
    DEADLINE,
    REQUIREMENTS,
    make_all,
    make_docx,
    make_pdf,
    make_pptx,
    make_xlsx,
)

if __name__ == "__main__":
    target = Path(sys.argv[1] if len(sys.argv) > 1 else "acme-fixtures")
    for kind, file in make_all(target).items():
        print(f"{kind}: {file}")

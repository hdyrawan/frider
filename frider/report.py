"""Render classification results as a human table or machine JSON.

The table shows the **actual matched paths** (not the rule regexes), colors
verdicts by family when stdout is a TTY, and keeps the alignment correct by
computing column widths on plain text before adding ANSI codes.
"""

from __future__ import annotations

import json
from typing import List, Optional

from . import __version__
from .rules import Result
from .ui import Palette, display_width, style_verdict

# Bumped whenever a --json field changes meaning or is removed.
SCHEMA_VERSION = 1


def _oneline(text: str) -> str:
    """Collapse whitespace so a cell can never span rows. adb surfaces
    multi-line stderr in error messages, and a newline inside a cell tears the
    table apart — the full text is still intact in --json."""
    return " ".join(text.split())


def _fmt_markers(markers) -> str:
    parts = []
    for fw, paths in markers.items():
        if not paths:
            continue
        shown = paths[0]
        more = len(paths) - 1
        parts.append(f"{fw}:{shown}" + (f" (+{more})" if more else ""))
    return "; ".join(parts) if parts else "-"


def to_row(r: Result) -> List[str]:
    """Plain-text row (no ANSI) — used for width calculation."""
    extra = []
    if r.engines:
        extra.append("engine=" + ",".join(r.engines))
    if r.kotlin:
        extra.append("kotlin")
    if r.embedded_js:
        extra.append("js=" + ",".join(r.embedded_js))
    if r.notable_libs:
        extra.append("libs=" + ",".join(r.notable_libs))
    if r.errors:
        extra.append("errors=" + ";".join(r.errors))
    row = [r.source, r.verdict, r.confidence, _fmt_markers(r.markers), " | ".join(extra)]
    return [_oneline(cell) for cell in row]


def _style_cell(p: Palette, row: List[str], index: int) -> str:
    """Style one plain cell. Returns text that may carry ANSI codes, so the
    caller must pad using the *plain* length, never ``len()`` of the result."""
    cell = row[index]
    if index == 0:
        return p.red(cell) if row[1].startswith("ERROR") else cell
    if index == 1:
        return style_verdict(p, cell)
    if index == 2:
        return p.dim(cell)
    return cell


def _pad(styled: str, plain: str, width: int) -> str:
    """Pad to ``width`` in terminal columns.

    Two things make ``str.ljust`` wrong here. It counts ANSI escapes, which used
    to make every colored table ragged; and it counts characters rather than
    columns, so a CJK filename — double-width in a terminal — overflows its cell.
    """
    return styled + " " * max(0, width - display_width(plain))


def _render_table(headers, plain_rows, palette, styler=None) -> str:
    """Bordered table. ``styler(palette, row, index) -> str`` colours a cell;
    without one the cells are printed plain.

    Widths are measured with ``display_width`` and padding is applied to the
    plain text, never to the styled string — ANSI codes are zero-width, and
    CJK app names are double-width.
    """
    widths = [display_width(h) for h in headers]
    for row in plain_rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], display_width(cell))

    out = []
    sep = "+" + "+".join("-" * (w + 2) for w in widths) + "+"
    out.append(sep)
    header_cells = [palette.bold(_pad(h, h, widths[i])) for i, h in enumerate(headers)]
    out.append("| " + " | ".join(header_cells) + " |")
    out.append(sep)
    for plain in plain_rows:
        cells = [
            _pad(styler(palette, plain, i) if styler else cell, cell, widths[i])
            for i, cell in enumerate(plain)
        ]
        out.append("| " + " | ".join(cells) + " |")
    out.append(sep)
    return "\n".join(out)


def render_table(results: List[Result], palette: Optional[Palette] = None) -> str:
    if not results:
        return "(no inputs classified)"
    palette = palette or Palette()
    headers = ["source", "verdict", "confidence", "markers", "notes"]
    return _render_table(headers, [to_row(r) for r in results], palette, _style_cell)


def render_package_table(packages: List[str], palette: Optional[Palette] = None) -> str:
    """The ``--list`` view: installed packages, nothing pulled or classified."""
    if not packages:
        return "(no packages installed)"
    palette = palette or Palette()
    return _render_table(["package"], [[p] for p in packages], palette)


def render_package_json(packages: List[str]) -> str:
    """``--list --json``. Same envelope as a classification run, so a caller
    checks ``schema_version`` the one way whatever it asked for."""
    return json.dumps(
        {
            "schema_version": SCHEMA_VERSION,
            "tool": "frider",
            "tool_version": __version__,
            "packages": packages,
        },
        indent=2,
    )


def render_json(results: List[Result]) -> str:
    """Machine output, wrapped in a versioned envelope.

    ``schema_version`` is the contract: it is bumped whenever a field changes
    meaning or disappears, so a caller can refuse input it does not understand
    instead of silently misreading it.
    """
    payload = {
        "schema_version": SCHEMA_VERSION,
        "tool": "frider",
        "tool_version": __version__,
        "results": [
            {
                "source": r.source,
                "verdict": r.verdict,
                "framework": r.framework,
                "frameworks": r.frameworks,
                "confidence": r.confidence,
                "engines": r.engines,
                "kotlin": r.kotlin,
                "embedded_js": r.embedded_js,
                "notable_libs": r.notable_libs,
                "matched_files": r.markers,
                "errors": r.errors,
            }
            for r in results
        ],
    }
    return json.dumps(payload, indent=2)

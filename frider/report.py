"""Render classification results as a human table or machine JSON.

The table shows the **actual matched paths** (not the rule regexes), colors
verdicts by family when stdout is a TTY, and keeps the alignment correct by
computing column widths on plain text before adding ANSI codes.
"""

from __future__ import annotations

import json
from typing import List, Optional

from .rules import Result
from .ui import Palette, style_verdict


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
    return [r.source, r.verdict, r.confidence, _fmt_markers(r.markers), " | ".join(extra)]


def _colorize(p: Palette, row: List[str]) -> List[str]:
    out = list(row)
    if row[1].startswith("ERROR"):
        out[0] = p.red(row[0])
    out[1] = style_verdict(p, row[1])
    out[2] = p.dim(row[2])
    return out


def render_table(results: List[Result], palette: Optional[Palette] = None) -> str:
    if not results:
        return "(no inputs classified)"
    palette = palette or Palette()
    headers = ["source", "verdict", "confidence", "markers", "notes"]
    plain_rows = [to_row(r) for r in results]
    widths = [len(h) for h in headers]
    for row in plain_rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(cell))

    out = []
    sep = "+" + "+".join("-" * (w + 2) for w in widths) + "+"
    out.append(sep)
    out.append("| " + " | ".join(palette.bold(h.ljust(widths[i])) for i, h in enumerate(headers)) + " |")
    out.append(sep)
    for plain in plain_rows:
        colored = _colorize(palette, plain)
        out.append("| " + " | ".join(c.ljust(widths[i]) for i, c in enumerate(colored)) + " |")
    out.append(sep)
    return "\n".join(out)


def render_json(results: List[Result]) -> str:
    payload = []
    for r in results:
        payload.append(
            {
                "source": r.source,
                "verdict": r.verdict,
                "confidence": r.confidence,
                "engines": r.engines,
                "kotlin": r.kotlin,
                "embedded_js": r.embedded_js,
                "notable_libs": r.notable_libs,
                "matched_files": r.markers,
                "errors": r.errors,
            }
        )
    return json.dumps(payload, indent=2)

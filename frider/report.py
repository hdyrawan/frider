"""Render classification results as a human table or machine JSON."""

from __future__ import annotations

import json
from typing import List

from .rules import Result


def _fmt_markers(markers) -> str:
    parts = []
    for fw, ms in markers.items():
        parts.append(f"{fw}:{','.join(ms)}")
    return "; ".join(parts) if parts else "-"


def to_row(r: Result) -> List[str]:
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


def render_table(results: List[Result]) -> str:
    if not results:
        return "(no inputs classified)"
    headers = ["source", "verdict", "confidence", "markers", "notes"]
    rows = [to_row(r) for r in results]
    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(cell))
    out = []
    sep = "+" + "+".join("-" * (w + 2) for w in widths) + "+"
    out.append(sep)
    out.append("| " + " | ".join(h.ljust(widths[i]) for i, h in enumerate(headers)) + " |")
    out.append(sep)
    for row in rows:
        out.append("| " + " | ".join(c.ljust(widths[i]) for i, c in enumerate(row)) + " |")
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
                "markers": r.markers,
                "errors": r.errors,
            }
        )
    return json.dumps(payload, indent=2)

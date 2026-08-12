"""Terminal UI helpers: color, verdict styling, summaries, progress."""

from __future__ import annotations

import os
import sys
from typing import Optional

_NO_COLOR_ENV = os.environ.get("NO_COLOR") is not None


class Palette:
    """Minimal ANSI color wrapper. Auto-disabled when stdout is not a TTY or
    when ``NO_COLOR`` is set; force with ``Palette(enabled=True/False)``."""

    def __init__(self, enabled: Optional[bool] = None):
        if enabled is None:
            enabled = not _NO_COLOR_ENV and sys.stdout.isatty()
        self.enabled = enabled

    def _wrap(self, code: int, text: str) -> str:
        if not self.enabled:
            return text
        return f"\x1b[{code}m{text}\x1b[0m"

    def bold(self, text: str) -> str:
        return self._wrap(1, text)

    def dim(self, text: str) -> str:
        return self._wrap(2, text)

    def red(self, text: str) -> str:
        return self._wrap(31, text)

    def green(self, text: str) -> str:
        return self._wrap(32, text)

    def yellow(self, text: str) -> str:
        return self._wrap(33, text)

    def blue(self, text: str) -> str:
        return self._wrap(34, text)

    def cyan(self, text: str) -> str:
        return self._wrap(36, text)


def style_verdict(p: Palette, verdict: str) -> str:
    """Color a verdict by family so a long table scans at a glance."""
    v = verdict.lower()
    if v.startswith("error"):
        return p.red(verdict)
    if "flutter" in v:
        return p.blue(verdict)
    if "react native" in v or "hybrid" in v:
        return p.cyan(verdict)
    if any(k in v for k in ("cordova", "kony", "ionic", "capacitor", "xamarin", "unity")):
        return p.yellow(verdict)
    if "native" in v:
        return p.dim(verdict)
    return p.bold(verdict)


def summarize(results) -> str:
    """One-line tally, e.g. ``3 sources: 2 flutter, 1 native``."""
    counts: dict = {}
    errors = 0
    for r in results:
        if r.errors:
            errors += 1
            continue
        key = r.verdict.split(" (")[0]
        counts[key] = counts.get(key, 0) + 1
    parts = [f"{n} {name.lower()}" for name, n in sorted(counts.items(), key=lambda kv: -kv[1])]
    if errors:
        parts.append(f"{errors} error(s)")
    if not parts:
        return "no sources classified"
    return f"{len(results)} source(s): " + ", ".join(parts)


def progress(message: str) -> None:
    print(message, file=sys.stderr)

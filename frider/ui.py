"""Terminal UI helpers: banner, color, verdict styling, summaries, progress."""

from __future__ import annotations

import os
import sys
import unicodedata
from typing import Optional

# Figlet "Doom". Raw string: the art is full of backslashes that would
# otherwise read as escape sequences.
BANNER = r"""
 ______        _      _
|  ___|      (_)    | |
| |_    _ __  _   __| |  ___  _ __
|  _|  | '__|| | / _` | / _ \| '__|
| |    | |   | || (_| ||  __/| |
\_|    |_|   |_| \__,_| \___||_|
"""

# One line under the art, on stderr: what the tool is, and which build is
# running. The version matters here — the first question about a surprising
# verdict is which frider produced it.
TAGLINE = "Android app framework detector"

# The art spells "Frider", and the "F" glyph ends at column 7 on every line —
# so the wordmark splits there into a red F and a blue "rider".
BANNER_SPLIT = 7

_NO_COLOR_ENV = os.environ.get("NO_COLOR") is not None


def display_width(text: str) -> int:
    """Columns a terminal will actually use for ``text``.

    ``len()`` is wrong for CJK app names, which are common in real APK filenames
    and package labels: a terminal draws them double-width, so a table sized by
    character count comes out ragged even though every row has equal ``len()``.
    Combining marks take no column of their own.
    """
    width = 0
    for ch in text:
        if unicodedata.combining(ch):
            continue
        width += 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
    return width


class Palette:
    """Minimal ANSI color wrapper. Auto-disabled when its stream is not a TTY
    or when ``NO_COLOR`` is set; force with ``Palette(enabled=True/False)``.

    ``stream`` is the output it is colouring, and it decides: the banner goes
    to stderr, so colouring it by stdout's TTY-ness writes escape codes into
    ``2> log.txt`` and drops colour from a terminal whenever stdout is piped.
    Resolved at call time, never bound at import — a default of
    ``stream=sys.stdout`` would capture the real stdout before a test could
    replace it.
    """

    def __init__(self, enabled: Optional[bool] = None, stream=None):
        if enabled is None:
            stream = sys.stdout if stream is None else stream
            enabled = (not _NO_COLOR_ENV
                       and hasattr(stream, "isatty") and stream.isatty())
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


def render_banner(palette: Palette) -> str:
    """The wordmark in two solid colours: the ``F`` red, ``rider`` blue.

    Colour is applied per line rather than to the block, because a single
    escape spanning newlines is reset by some terminals at the line break and
    leaves the rest uncoloured.
    """
    out = []
    for line in BANNER.strip("\n").split("\n"):
        head, tail = line[:BANNER_SPLIT], line[BANNER_SPLIT:]
        out.append(palette.red(head) + palette.blue(tail))
    return "\n".join(out)


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

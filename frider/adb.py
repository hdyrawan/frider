"""Pull installed APK sets from an adb device (``pm path``) for classification.

Uses ``adb -s <serial> shell pm path <pkg>`` and pulls every returned APK into
a cache directory. Requires adb on PATH and a reachable device.
"""

from __future__ import annotations

import os
import subprocess
from typing import List, Optional


class AdbError(RuntimeError):
    pass


def _run(cmd: List[str]) -> str:
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise AdbError(f"command failed: {' '.join(cmd)}\n{r.stderr.strip()}")
    return r.stdout


def apk_paths(serial: str, pkg: str) -> List[str]:
    """Every APK path the package manager reports for the package."""
    out = _run(["adb", "-s", serial, "shell", "pm", "path", pkg])
    paths = [ln.strip()[len("package:"):] for ln in out.splitlines() if ln.startswith("package:")]
    return paths


def pull_package(serial: str, pkg: str, out_dir: str) -> Optional[str]:
    """Pull all APKs of a package into ``out_dir/<pkg>/``; return that dir, or
    None if the package is not installed. The returned dir works with
    ``frider.apk.entries_for``."""
    paths = apk_paths(serial, pkg)
    if not paths:
        return None
    d = os.path.join(out_dir, pkg)
    os.makedirs(d, exist_ok=True)
    for i, apk in enumerate(paths):
        subprocess.run(
            ["adb", "-s", serial, "pull", apk, os.path.join(d, f"apk_{i}.apk")],
            capture_output=True,
            text=True,
        )
    return d

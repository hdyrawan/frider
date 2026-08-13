"""Pull installed APK sets from an adb device (``pm path``) for classification.

Uses ``adb -s <serial> shell pm path <pkg>`` and pulls every returned APK into
a cache directory. Requires adb on PATH and a reachable device.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from typing import List, Optional, Tuple

# adb hangs indefinitely against a wedged device; bound every call so frider
# fails with a message instead of sitting there forever.
SHELL_TIMEOUT = 30
PULL_TIMEOUT = 600


class AdbError(RuntimeError):
    pass


def _run(cmd: List[str], timeout: int = SHELL_TIMEOUT) -> str:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError:
        raise AdbError("adb not found on PATH — install platform-tools") from None
    except subprocess.TimeoutExpired:
        raise AdbError(f"timed out after {timeout}s: {' '.join(cmd)}") from None
    if r.returncode != 0:
        raise AdbError(f"command failed: {' '.join(cmd)}\n{r.stderr.strip()}")
    return r.stdout


def _packages_from(out: str) -> List[str]:
    """Parse ``package:`` lines, tolerating adb's CRLF line endings."""
    lines = (ln.strip() for ln in out.splitlines())
    return [ln[len("package:"):] for ln in lines if ln.startswith("package:")]


def apk_paths(serial: str, pkg: str) -> List[str]:
    """Every APK path the package manager reports for the package."""
    return _packages_from(_run(["adb", "-s", serial, "shell", "pm", "path", pkg]))


def list_third_party_packages(serial: str) -> List[str]:
    """Sorted third-party package names installed on the device."""
    out = _run(["adb", "-s", serial, "shell", "pm", "list", "packages", "-3"])
    return sorted(_packages_from(out))


def pull_package(serial: str, pkg: str, out_dir: str) -> Optional[Tuple[str, int]]:
    """Pull all APKs of a package into ``out_dir/<pkg>/``; return
    ``(dir, apk_count)``, or None if the package is not installed. The returned
    dir works with ``frider.apk.entries_for``. Any failed pull raises
    ``AdbError`` so a broken half-pulled set is never classified as "native"."""
    paths = apk_paths(serial, pkg)
    if not paths:
        return None
    d = os.path.join(out_dir, pkg)
    # Wipe first: the cache dir is reused across runs, and a package that used
    # to ship more splits (or a different app version) would otherwise leave
    # stale apk_N.apk files behind that get classified as part of this set.
    shutil.rmtree(d, ignore_errors=True)
    os.makedirs(d, exist_ok=True)
    for i, apk in enumerate(paths):
        _run(
            ["adb", "-s", serial, "pull", apk, os.path.join(d, f"apk_{i}.apk")],
            timeout=PULL_TIMEOUT,
        )
    return d, len(paths)

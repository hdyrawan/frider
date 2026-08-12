"""frider command line: classify APK/XAPK/APKS files, directories, or
installed packages pulled from an adb device.

Examples::

    frider app.apk
    frider build/*.apk --json
    frider --adb com.example.app com.example.other
    frider --adb --serial 0123456789abcdef --all
    frider --rules /path/to/rules.json app.apk
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from typing import List, Optional

from . import __version__
from .apk import entries_for
from .rules import classify_entries, load_rules
from .report import render_json, render_table
from .ui import Palette, progress, summarize

DEFAULT_ADB_SERIAL = os.environ.get("ANDROID_PROBE_SERIAL", "")


def default_cache_dir() -> str:
    """Stable per-user cache (XDG-aware) so adb runs skip re-pulling."""
    base = os.environ.get("XDG_CACHE_HOME") or os.path.join(os.path.expanduser("~"), ".cache")
    return os.path.join(base, "frider")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="frider",
        description="Android app framework detector (Flutter / React Native / "
                    "Cordova / Ionic / Capacitor / Kony / Xamarin / Unity / native).",
        epilog="A path can be an .apk, an .xapk/.apks container, or a directory "
               "of APKs. With --adb, positional arguments are package names.",
    )
    p.add_argument("paths", nargs="*",
                   help="APK/XAPK/APKS files or directories; with --adb: package names")
    p.add_argument("--adb", action="store_true",
                   help="classify installed packages pulled via adb; positionals are package names")
    p.add_argument("--serial", metavar="SERIAL", default=None,
                   help="adb device serial (default: $ANDROID_PROBE_SERIAL)")
    p.add_argument("--all", action="store_true",
                   help="with --adb: classify every third-party package, not just the named ones")
    p.add_argument("--json", action="store_true", help="machine-readable JSON output")
    p.add_argument("--rules", metavar="FILE", help="custom rules.json (default: bundled)")
    p.add_argument("--cache-dir", metavar="DIR", default=None,
                   help=f"where pulled APKs are cached (default: {default_cache_dir()})")
    p.add_argument("--no-cache", action="store_true",
                   help="with --adb: pull into a fresh temp dir instead of the cache")
    p.add_argument("--no-color", action="store_true", help="disable ANSI colors")
    p.add_argument("--version", action="version", version=f"frider {__version__}")
    return p


def _classify_path(path: str, rules):
    entries = entries_for(path)
    result = classify_entries(entries, rules)
    result.source = path
    return result


def _adb_classify(serial: str, packages: List[str], rules, cache_dir: str):
    from .adb import AdbError, pull_package

    results = []
    for pkg in packages:
        progress(f"pulling {pkg} ...")
        try:
            pulled = pull_package(serial, pkg, cache_dir)
        except AdbError as e:
            progress(f"  error: {e}")
            results.append(_error_result(pkg, str(e)))
            continue
        if pulled is None:
            progress("  not installed")
            results.append(_error_result(pkg, "not installed"))
            continue
        _dir, count = pulled
        progress(f"  ok ({count} apk{'s' if count != 1 else ''})")
        entries = entries_for(_dir)
        result = classify_entries(entries, rules)
        result.source = pkg
        results.append(result)
    return results


def _error_result(source: str, message: str):
    from .rules import Result

    r = Result(source=source, verdict="ERROR", confidence="-")
    r.errors.append(message)
    return r


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    rules = load_rules(args.rules)
    palette = Palette(enabled=False if args.no_color else None)

    results = []
    if args.adb:
        serial = args.serial or DEFAULT_ADB_SERIAL
        if not serial:
            print("frider: --adb needs a serial (pass --serial, or set ANDROID_PROBE_SERIAL)", file=sys.stderr)
            return 2
        if args.all:
            from .adb import _run

            out = _run(["adb", "-s", serial, "shell", "pm", "list", "packages", "-3"])
            pkgs = [ln.split(":")[-1].strip() for ln in out.splitlines() if ln.startswith("package:")]
            packages = sorted(pkgs)
        else:
            packages = args.paths
        if not packages:
            print("frider: --adb requires package names (or --all)", file=sys.stderr)
            return 2
        cache = tempfile.mkdtemp(prefix="frider-") if args.no_cache else (args.cache_dir or default_cache_dir())
        results = _adb_classify(serial, packages, rules, cache)
    else:
        if not args.paths:
            build_parser().print_help()
            return 2
        for path in args.paths:
            try:
                results.append(_classify_path(path, rules))
            except (ValueError, OSError) as e:
                results.append(_error_result(path, str(e)))

    if args.json:
        print(render_json(results))
    else:
        print(render_table(results, palette=palette))
        summary = summarize(results)
        print(palette.dim(summary))

    return 1 if any(r.errors for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())

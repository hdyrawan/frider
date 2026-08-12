"""frider command line: classify APK/XAPK/APKS files, directories, or
installed packages pulled from an adb device.

Examples::

    frider app.apk
    frider build/*.apk --json
    frider --adb com.example.app com.example.other
    frider --adb --all
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

DEFAULT_ADB_SERIAL = os.environ.get("ANDROID_PROBE_SERIAL", "")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="frider",
        description="Android app framework detector (Flutter / React Native / "
                    "Cordova / Ionic / Capacitor / Kony / Xamarin / Unity / native).",
        epilog="A path can be an .apk, an .xapk/.apks container, or a directory "
               "of APKs. With --adb, positional arguments are package names.",
    )
    p.add_argument("paths", nargs="*", help="APK/XAPK/APKS files or directories; with --adb: package names")
    p.add_argument("--adb", nargs="?", const="__default__", metavar="SERIAL",
                   help="classify installed packages pulled via adb (default serial: $ANDROID_PROBE_SERIAL)")
    p.add_argument("--all", action="store_true",
                   help="with --adb: classify every third-party package, not just the named ones")
    p.add_argument("--json", action="store_true", help="machine-readable JSON output")
    p.add_argument("--rules", metavar="FILE", help="custom rules.json (default: bundled)")
    p.add_argument("--cache-dir", metavar="DIR", default=None,
                   help="where pulled APKs are cached (default: temp dir)")
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
        try:
            d = pull_package(serial, pkg, cache_dir)
        except AdbError as e:
            results.append(_error_result(pkg, str(e)))
            continue
        if d is None:
            results.append(_error_result(pkg, "not installed"))
            continue
        entries = entries_for(d)
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

    results = []
    adb_mode = args.adb is not None
    if adb_mode:
        serial = DEFAULT_ADB_SERIAL if args.adb == "__default__" else args.adb
        if not serial:
            print("frider: --adb needs a serial (pass one, or set ANDROID_PROBE_SERIAL)", file=sys.stderr)
            return 2
        cache = args.cache_dir or tempfile.mkdtemp(prefix="frider-")
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
        results = _adb_classify(serial, packages, rules, cache)
    else:
        if not args.paths:
            build_parser().print_help()
            return 2
        for path in args.paths:
            try:
                result = _classify_path(path, rules)
                results.append(result)
            except ValueError as e:
                results.append(_error_result(path, str(e)))
            except OSError as e:
                results.append(_error_result(path, str(e)))

    if args.json:
        print(render_json(results))
    else:
        print(render_table(results))
    return 0


if __name__ == "__main__":
    sys.exit(main())

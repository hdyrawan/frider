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
import re
import shutil
import sys
import tempfile
import zipfile
from typing import List, Optional

from . import __version__
from .apk import entries_for
from .report import render_json, render_package_json, render_package_table, render_table
from .rules import classify_entries, load_rules
from .ui import BANNER, Palette, progress, summarize

DEFAULT_ADB_SERIAL = os.environ.get("ANDROID_PROBE_SERIAL", "")


def default_cache_dir() -> str:
    """Stable per-user cache (XDG-aware) so adb runs skip re-pulling."""
    base = os.environ.get("XDG_CACHE_HOME") or os.path.join(os.path.expanduser("~"), ".cache")
    return os.path.join(base, "frider")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="frider",
        # Raw formatter, or argparse reflows the banner into a paragraph.
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=BANNER.strip("\n") + "\n\n"
                    "Android app framework detector. Classifies Flutter / Dart,\n"
                    "React Native (reporting the Hermes vs JavaScriptCore engine\n"
                    "split most detectors collapse), .NET MAUI, Xamarin, Apache\n"
                    "Cordova, Capacitor, Ionic, Kony, Lynx, NativeScript, Qt,\n"
                    "Titanium, Unity, or native Java/Kotlin — from APK entry\n"
                    "names alone, never file contents.",
        epilog="A path can be an .apk, an .xapk/.apks container, or a directory\n"
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
    p.add_argument("--list", action="store_true", dest="list_packages",
                   help="with --adb: list installed third-party packages without pulling them")
    p.add_argument("--list-all", action="store_true", dest="list_all",
                   help="with --adb: like --list, including system packages")
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
        try:
            entries = entries_for(_dir)
        except (ValueError, OSError) as e:
            # A pulled set that won't open must not fall through to "native".
            progress(f"  error: {e}")
            results.append(_error_result(pkg, str(e)))
            continue
        result = classify_entries(entries, rules)
        result.source = pkg
        results.append(result)
    return results


def _error_result(source: str, message: str):
    from .rules import Result

    # framework="error", never the "native" default — a source we could not
    # read must not report as an app with no framework markers.
    r = Result(source=source, verdict="ERROR", confidence="-", framework="error")
    r.errors.append(message)
    return r


def _list_mode(args, palette) -> int:
    """``--adb --list``: what is installed, without pulling a single APK.

    Listing is the step before a scan — it costs one adb call, where --all
    costs a full pull of every package.
    """
    from .adb import AdbError, list_packages

    if not args.adb:
        print("frider: --list needs --adb (it lists what is on a device)", file=sys.stderr)
        return 2
    serial = args.serial or DEFAULT_ADB_SERIAL
    if not serial:
        print("frider: --adb needs a serial (pass --serial, or set "
              "ANDROID_PROBE_SERIAL)", file=sys.stderr)
        return 2
    if args.paths:
        # Same reasoning as --all: silently dropping the names would look
        # like a listing filtered to exactly those packages.
        progress(f"frider: --list shows every package; ignoring the "
                 f"{len(args.paths)} name(s) given")
    try:
        packages = list_packages(serial, include_system=args.list_all)
    except AdbError as e:
        print(f"frider: {e}", file=sys.stderr)
        return 2

    if args.json:
        print(render_package_json(packages))
    else:
        print(render_package_table(packages, palette))
        scope = "package(s)" if args.list_all else "third-party package(s)"
        # stdout, like the results summary: on stderr it overtakes the table
        # whenever stdout is a pipe, since only stdout is block-buffered.
        print(palette.dim(f"{len(packages)} {scope}"))
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    # The banner goes to stderr on every run, never stdout: --json is a
    # contract a caller pipes into jq, and a table someone pipes into awk is
    # just as easily broken by seven lines of ASCII art in front of it.
    print(BANNER.strip("\n"), file=sys.stderr)
    try:
        rules = load_rules(args.rules)
    except (OSError, ValueError, re.error) as e:
        # A bad --rules file is user input, not a crash: report it plainly.
        print(f"frider: cannot load rules: {e}", file=sys.stderr)
        return 2
    palette = Palette(enabled=False if args.no_color else None)

    if args.list_packages or args.list_all:
        return _list_mode(args, palette)

    results = []
    scratch = None
    if args.adb:
        serial = args.serial or DEFAULT_ADB_SERIAL
        if not serial:
            print("frider: --adb needs a serial (pass --serial, or set "
                  "ANDROID_PROBE_SERIAL)", file=sys.stderr)
            return 2
        if args.all:
            from .adb import AdbError, list_third_party_packages

            if args.paths:
                # Silently dropping them would look like a scan of exactly the
                # packages that were named.
                progress(f"frider: --all scans every package; ignoring the "
                         f"{len(args.paths)} name(s) given")
            try:
                packages = list_third_party_packages(serial)
            except AdbError as e:
                print(f"frider: {e}", file=sys.stderr)
                return 2
        else:
            packages = args.paths
        if not packages:
            print("frider: --adb requires package names (or --all)", file=sys.stderr)
            return 2
        if args.no_cache:
            scratch = cache = tempfile.mkdtemp(prefix="frider-")
        else:
            cache = args.cache_dir or default_cache_dir()
        try:
            results = _adb_classify(serial, packages, rules, cache)
        finally:
            # --no-cache promises a throwaway pull; don't leave GiB in /tmp.
            if scratch:
                shutil.rmtree(scratch, ignore_errors=True)
    else:
        if not args.paths:
            build_parser().print_help()
            return 2
        for path in args.paths:
            try:
                results.append(_classify_path(path, rules))
            except (ValueError, OSError, zipfile.BadZipFile) as e:
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

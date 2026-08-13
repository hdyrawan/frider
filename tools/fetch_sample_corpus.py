#!/usr/bin/env python3
"""Fetch a small corpus of *real* APKs from public package registries.

The tests in ``tests/`` build synthetic zips, which proves the matcher works but
not that a fingerprint is right (see AGENTS.md). A real corpus fixes that, and
the usual obstacle is getting one: app stores are awkward to script against and
their contents are rarely redistributable.

Several open-source Android tools ship real, compiled APKs inside their PyPI
sdists and npm tarballs. Those are ordinary Android-toolchain builds — nobody
built them to match frider's rules — so they make a legitimate, reproducible
starting corpus that needs no binaries committed here.

    python3 tools/fetch_sample_corpus.py corpus/
    python3 tools/corpus_check.py corpus/

WHAT THIS DOES AND DOES NOT PROVE
---------------------------------
Every APK reachable this way is a **native** app. That makes this a real test of
the direction frider has historically got wrong — a native app misreported as a
framework, which is what both the ``res/xml/config.xml`` and ``libfbjni.so``
bugs did. It exercises thousands of real entry names against every marker.

It does **not** validate any framework fingerprint. Nothing here is built with
Flutter, React Native, MAUI, NativeScript, Qt or Titanium, so a broken marker
for those would sail straight through. Only a corpus of real framework apps
answers that, and it has to be assembled by hand.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import sys
import tarfile
import urllib.request
from typing import List, NamedTuple, Optional

USER_AGENT = "frider-corpus-fetcher"
TIMEOUT = 120


class Source(NamedTuple):
    registry: str   # "pypi" or "npm"
    package: str
    label: str      # expected framework id — the corpus directory it lands in
    note: str


# Every one of these is an ordinary Android build with no cross-platform
# framework, so they all belong under the "native" label.
SOURCES: List[Source] = [
    Source("npm", "android-apidemos", "native",
           "Google's Android API demos — plain Java, ~880 entries"),
    Source("npm", "io.appium.settings", "native",
           "Appium's helper app — Java/Kotlin"),
    Source("npm", "appium-uiautomator2-server", "native",
           "Appium's UiAutomator2 server — Kotlin, multidex, ~3800 entries"),
    Source("pypi", "androwarn", "native",
           "androwarn's bundled sample application"),
]


def _get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:  # noqa: S310 - fixed hosts
        return r.read()


def tarball_url(src: Source) -> Optional[str]:
    if src.registry == "npm":
        meta = json.loads(_get(f"https://registry.npmjs.org/{src.package}"))
        return meta["versions"][meta["dist-tags"]["latest"]]["dist"]["tarball"]
    meta = json.loads(_get(f"https://pypi.org/pypi/{src.package}/json"))
    sdists = [f for f in meta["urls"] if f["packagetype"] == "sdist"]
    return sdists[0]["url"] if sdists else None


def extract_apks(blob: bytes, src: Source, dest_dir: str) -> List[str]:
    written = []
    with tarfile.open(fileobj=io.BytesIO(blob)) as tar:
        for member in tar.getmembers():
            if not member.name.lower().endswith(".apk") or not member.isfile():
                continue
            name = f"{src.package}__{os.path.basename(member.name)}"
            handle = tar.extractfile(member)
            if handle is None:
                continue
            with open(os.path.join(dest_dir, name), "wb") as fh:
                fh.write(handle.read())
            written.append(name)
    return written


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(
        prog="fetch_sample_corpus",
        description="Download real APKs from public package registries into a corpus tree.",
    )
    p.add_argument("corpus", help="corpus directory to populate")
    args = p.parse_args(argv)

    total = 0
    for src in SOURCES:
        dest = os.path.join(args.corpus, src.label)
        os.makedirs(dest, exist_ok=True)
        try:
            url = tarball_url(src)
            if url is None:
                print(f"  {src.package}: no downloadable archive, skipped", file=sys.stderr)
                continue
            names = extract_apks(_get(url), src, dest)
        except Exception as exc:                       # network, registry, archive shape
            print(f"  {src.package}: {exc}", file=sys.stderr)
            continue
        if not names:
            print(f"  {src.package}: archive carried no APK, skipped", file=sys.stderr)
            continue
        total += len(names)
        print(f"  {src.label}/  {src.package}  ({src.note})")
        for n in names:
            print(f"      {n}")

    if not total:
        print("no APKs fetched — is the network reachable?", file=sys.stderr)
        return 1

    print(f"\n{total} real APK(s) in {args.corpus}")
    print("These are all native builds: this checks that no framework rule fires on a")
    print("real native app. It does not validate any framework fingerprint — add real")
    print("Flutter/React Native/MAUI apps by hand for that.")
    print(f"\nNext:  python3 tools/corpus_check.py {args.corpus}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

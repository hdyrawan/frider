#!/usr/bin/env python3
"""Measure frider against a corpus of real APKs.

Every test in ``tests/`` builds its fixtures from the same assumptions the
rules were written from, so the suite proves the *matcher* works — not that the
*fingerprints are right*. Only real APKs can tell you that, and the answer is a
number: how often the verdict matches what the app was actually built with.

Corpus layout — the directory name is the expected framework id, so labelling
an app is a matter of dropping it in the right folder:

    corpus/
      flutter/            com.example.a.apk, com.example.b.xapk
      react-native/       ...
      maui/               ...
      native/             ...          # apps with no cross-platform framework
      _ignore/            ...          # skipped: staging, unlabelled, licence-bound

A split-APK pull goes in its own subdirectory and counts as a single case —
the same set semantics as ``frider pulled-apks/``, where every ``apk_*.apk``
is scanned together. A resource-only config split is then not misread as a
second "native" app:

    corpus/
      flutter/
        myapp.apk                       # single-APK case
        myapp-split/                    # split-APK case, scored once
          base.apk
          config.arm64_v8a.apk
          config.en.apk

Run it:

    python3 tools/corpus_check.py corpus/
    python3 tools/corpus_check.py corpus/ --json accuracy.json --min-accuracy 95

Exits non-zero when accuracy falls below ``--min-accuracy`` (default: any
mismatch fails), so it works as a release gate as well as a report.

Not shipped in the wheel — ``pyproject.toml`` packages only ``frider``.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter, defaultdict
from typing import Dict, List, NamedTuple, Optional

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from frider.apk import entries_for  # noqa: E402
from frider.rules import classify_entries, load_rules  # noqa: E402

IGNORED_DIRS = {"_ignore"}
APK_SUFFIXES = (".apk", ".xapk", ".apks")


class Case(NamedTuple):
    path: str
    expected: str
    got: str
    confidence: str
    error: str

    @property
    def ok(self) -> bool:
        return not self.error and self.got == self.expected


def known_labels(rules: Dict) -> List[str]:
    """Every id a corpus directory is allowed to be named after."""
    return sorted({fw["id"] for fw in rules.get("frameworks", [])} | {"native", "hybrid"})


def collect(corpus_dir: str, labels: List[str]) -> List[str]:
    """Label directories, validated — a typo silently scores zero otherwise."""
    found, unknown = [], []
    for name in sorted(os.listdir(corpus_dir)):
        full = os.path.join(corpus_dir, name)
        if not os.path.isdir(full) or name in IGNORED_DIRS:
            continue
        (found if name in labels else unknown).append(name)
    if unknown:
        raise SystemExit(
            f"corpus: unknown label director{'y' if len(unknown) == 1 else 'ies'}: "
            f"{', '.join(unknown)}\nexpected one of: {', '.join(labels)}"
        )
    return found


def classify_one(path: str, rules: Dict, expected: str) -> Case:
    try:
        # A directory of split APKs is classified as one set, matching the
        # CLI's directory mode: every apk_*.apk is scanned together, so a
        # resource-only config split cannot be misread as a "native" app.
        result = classify_entries(entries_for(path), rules)
    except (ValueError, OSError) as exc:
        return Case(path, expected, "error", "-", str(exc))
    return Case(path, expected, result.framework, result.confidence, "")


def run(corpus_dir: str, rules: Dict) -> List[Case]:
    labels = known_labels(rules)
    cases: List[Case] = []
    for label in collect(corpus_dir, labels):
        label_dir = os.path.join(corpus_dir, label)
        for entry in sorted(os.listdir(label_dir)):
            full = os.path.join(label_dir, entry)
            if os.path.isdir(full):
                # A subdirectory holds one split-APK pull: one case, scanned
                # as a set. Do not descend — the files inside belong together.
                cases.append(classify_one(full, rules, label))
            elif entry.lower().endswith(APK_SUFFIXES):
                cases.append(classify_one(full, rules, label))
    return cases


def report(cases: List[Case], stream=None) -> float:
    # Resolved at call time, not bound as a default: a default would capture
    # whatever sys.stdout was at import and ignore any later redirection.
    stream = sys.stdout if stream is None else stream
    if not cases:
        print("corpus is empty — nothing to measure", file=stream)
        return 0.0

    correct = sum(1 for c in cases if c.ok)
    accuracy = 100.0 * correct / len(cases)

    per_label: Dict[str, List[Case]] = defaultdict(list)
    for c in cases:
        per_label[c.expected].append(c)

    width = max(len(label) for label in per_label)
    print(f"{'expected':<{width}}  {'n':>4}  {'ok':>4}  {'acc':>7}  confusions", file=stream)
    print("-" * (width + 34), file=stream)
    for label in sorted(per_label):
        group = per_label[label]
        ok = sum(1 for c in group if c.ok)
        wrong = Counter(c.got for c in group if not c.ok)
        confusions = ", ".join(f"{got}x{n}" for got, n in wrong.most_common()) or "-"
        pct = 100.0 * ok / len(group)
        row = f"{label:<{width}}  {len(group):>4}  {ok:>4}  {pct:>6.1f}%  {confusions}"
        print(row, file=stream)

    print(f"\n{correct}/{len(cases)} correct — {accuracy:.1f}% accuracy", file=stream)

    misses = [c for c in cases if not c.ok]
    if misses:
        print(f"\n{len(misses)} mismatch{'' if len(misses) == 1 else 'es'}:", file=stream)
        for c in misses:
            detail = c.error or f"got {c.got} ({c.confidence})"
            print(f"  {os.path.basename(c.path)}: expected {c.expected}, {detail}", file=stream)
    return accuracy


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(
        prog="corpus_check",
        description="Measure frider's verdicts against a labelled corpus of real APKs.",
    )
    p.add_argument("corpus", help="directory of <framework-id>/ subdirectories")
    p.add_argument("--rules", help="custom rules.json (default: bundled)")
    p.add_argument("--json", metavar="FILE", help="also write the per-APK results as JSON")
    p.add_argument("--min-accuracy", type=float, default=100.0, metavar="PCT",
                   help="exit non-zero below this percentage (default: 100)")
    args = p.parse_args(argv)

    if not os.path.isdir(args.corpus):
        print(f"corpus_check: not a directory: {args.corpus}", file=sys.stderr)
        return 2

    cases = run(args.corpus, load_rules(args.rules))
    accuracy = report(cases)

    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(
                {
                    "accuracy": accuracy,
                    "total": len(cases),
                    "correct": sum(1 for c in cases if c.ok),
                    "cases": [c._asdict() for c in cases],
                },
                fh,
                indent=2,
            )

    if not cases:
        return 1
    return 0 if accuracy >= args.min_accuracy else 1


if __name__ == "__main__":
    sys.exit(main())

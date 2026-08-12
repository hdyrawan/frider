"""Load framework rules and classify an APK's entries.

Rules live in ``rules.json`` (data, not code — the APKiD-style design so
anyone can add a fingerprint without touching Python). A framework wins by
marker presence; ties break on weight then on distinct markers matched.
React Native additionally reports its JS engine: ``hermes`` or ``jsc``
(JavaScriptCore) — most detectors collapse both into "React Native", which
matters because the two engines have different runtime surfaces.

The result records the **actual entry paths** that matched each framework
(capped), not just which rules fired — that is what the table and JSON show.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from .apk import Entry, innermost

DEFAULT_RULES = Path(__file__).parent / "rules.json"

# Keep tables/JSON readable: at most this many matched paths per framework.
MAX_PATHS_PER_FRAMEWORK = 8


@dataclass
class FrameworkHit:
    id: str
    name: str
    weight: int
    markers: List[str] = field(default_factory=list)
    paths: List[str] = field(default_factory=list)


@dataclass
class Result:
    source: str
    verdict: str
    confidence: str
    engines: List[str] = field(default_factory=list)
    kotlin: bool = False
    embedded_js: List[str] = field(default_factory=list)
    notable_libs: List[str] = field(default_factory=list)
    markers: Dict[str, List[str]] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)


def load_rules(path: Optional[str] = None) -> Dict:
    with open(path or DEFAULT_RULES, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _dedup(values: List[str]) -> List[str]:
    return list(dict.fromkeys(values))


def classify_entries(entries: List[Entry], rules: Dict) -> Result:
    paths = [innermost(e.path) for e in entries if not e.is_dir]

    # Precompile every pattern once; rules are few, entries can be thousands.
    all_patterns: List[str] = []
    for fw in rules.get("frameworks", []):
        all_patterns.extend(fw.get("markers", []))
        all_patterns.extend(fw.get("engines", {}).values())
    if rules.get("kotlin"):
        all_patterns.append(rules["kotlin"]["marker"])
    for item in rules.get("embedded_js", []):
        all_patterns.append(item["marker"])
    for item in rules.get("notable_libs", []):
        all_patterns.append(item["regex"])
    compiled = {p: re.compile(p, re.IGNORECASE) for p in dict.fromkeys(all_patterns)}

    def find(pattern: str) -> List[str]:
        rx = compiled[pattern]
        return [p for p in paths if rx.search(p)]

    hits: Dict[str, FrameworkHit] = {}
    for fw in rules.get("frameworks", []):
        fw_id = fw["id"]
        matched_paths: List[str] = []
        matched_rules: List[str] = []
        for marker in fw.get("markers", []):
            found = find(marker)
            if found:
                matched_rules.append(marker)
                matched_paths.extend(found)
        if matched_paths:
            hits[fw_id] = FrameworkHit(
                id=fw_id,
                name=fw["name"],
                weight=fw.get("weight", 50),
                markers=matched_rules,
                paths=_dedup(matched_paths),
            )

    engines: List[str] = []
    for fw in rules.get("frameworks", []):
        if fw.get("engines") and fw["id"] in hits:
            for ename, pattern in fw["engines"].items():
                if find(pattern):
                    engines.append(ename)

    kotlin = bool(rules.get("kotlin")) and bool(find(rules["kotlin"]["marker"]))

    embedded_js = [
        item["name"] for item in rules.get("embedded_js", []) if find(item["marker"])
    ]

    notable_libs = [
        item["label"] for item in rules.get("notable_libs", []) if find(item["regex"])
    ]

    result = Result(
        source="",
        verdict=derive_verdict(hits, engines),
        confidence=derive_confidence(hits),
        engines=engines,
        kotlin=kotlin,
        embedded_js=embedded_js,
        notable_libs=notable_libs,
        markers={
            hid: h.paths[:MAX_PATHS_PER_FRAMEWORK] for hid, h in hits.items()
        },
    )
    return result


def derive_verdict(hits: Dict[str, FrameworkHit], engines: List[str]) -> str:
    ids = set(hits)
    if "flutter" in ids and "react-native" in ids:
        return "Hybrid (Flutter + React Native)"
    if "flutter" in ids:
        return "Flutter / Dart"
    if "react-native" in ids:
        engine = f" ({engines[0]})" if engines else ""
        return "React Native" + engine
    if ids:
        top = sorted(hits.values(), key=lambda h: (h.weight, len(h.paths)), reverse=True)[0]
        return top.name
    return "Native (no framework markers)"


def derive_confidence(hits: Dict[str, FrameworkHit]) -> str:
    total = sum(len(h.paths) for h in hits.values())
    if total >= 2:
        return "High"
    if total == 1:
        return "Medium"
    return "Low"

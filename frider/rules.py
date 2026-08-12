"""Load framework rules and classify an APK's entries.

Rules live in ``rules.json`` (data, not code — the APKiD-style design so
anyone can add a fingerprint without touching Python). A framework wins by
marker presence; ties break on weight then on distinct markers matched.
React Native additionally reports its JS engine: ``hermes`` or ``jsc``
(JavaScriptCore) — most detectors collapse both into \"React Native\", which
matters because the two engines have different runtime surfaces.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from .apk import Entry, innermost

DEFAULT_RULES = Path(__file__).parent / "rules.json"


@dataclass
class FrameworkHit:
    id: str
    name: str
    weight: int
    markers: List[str] = field(default_factory=list)


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


def classify_entries(entries: List[Entry], rules: Dict) -> Result:
    paths = [innermost(e.path) for e in entries if not e.is_dir]

    def match(pattern: str) -> bool:
        rx = re.compile(pattern, re.IGNORECASE)
        return any(rx.search(p) for p in paths)

    hits: Dict[str, FrameworkHit] = {}
    for fw in rules.get("frameworks", []):
        matched = [m for m in fw.get("markers", []) if match(m)]
        if matched:
            hits[fw["id"]] = FrameworkHit(
                id=fw["id"], name=fw["name"], weight=fw.get("weight", 50), markers=matched
            )

    engines: List[str] = []
    for fw in rules.get("frameworks", []):
        if fw.get("engines") and fw["id"] in hits:
            for ename, pattern in fw["engines"].items():
                if match(pattern):
                    engines.append(ename)

    kotlin = bool(rules.get("kotlin")) and match(rules["kotlin"]["marker"])

    embedded_js = [
        e["name"] for e in rules.get("embedded_js", []) if match(e["marker"])
    ]

    notable_libs = [
        item["label"] for item in rules.get("notable_libs", []) if match(item["regex"])
    ]

    result = Result(
        source="",
        verdict=derive_verdict(hits, engines),
        confidence=derive_confidence(hits),
        engines=engines,
        kotlin=kotlin,
        embedded_js=embedded_js,
        notable_libs=notable_libs,
        markers={hid: list(h.markers) for hid, h in hits.items()},
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
        top = sorted(hits.values(), key=lambda h: (h.weight, len(h.markers)), reverse=True)[0]
        return top.name
    return "Native (no framework markers)"


def derive_confidence(hits: Dict[str, FrameworkHit]) -> str:
    total = sum(len(h.markers) for h in hits.values())
    if total >= 2:
        return "High"
    if total == 1:
        return "Medium"
    return "Low"

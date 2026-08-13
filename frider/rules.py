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

from .apk import Entry

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
    # ``verdict`` is prose for humans and may be reworded; ``framework`` is the
    # stable machine id callers should branch on ("flutter", "react-native",
    # "native", "hybrid"). ``frameworks`` lists every id the verdict covers.
    framework: str = "native"
    frameworks: List[str] = field(default_factory=list)
    engines: List[str] = field(default_factory=list)
    kotlin: bool = False
    embedded_js: List[str] = field(default_factory=list)
    notable_libs: List[str] = field(default_factory=list)
    markers: Dict[str, List[str]] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)


def kotlin_markers(rules: Dict) -> List[str]:
    """The Kotlin marker regexes, accepting either the legacy single ``marker``
    string or a ``markers`` list. R8 strips ``.kotlin_module`` from minified
    apps, so a single ``.kotlin_module`` rule silently misses most real Kotlin
    apps — hence the list form (``.kotlin_builtins`` and the ``kotlinx *.version``
    stamps survive minification)."""
    k = rules.get("kotlin")
    if not k:
        return []
    if "markers" in k:
        return list(k["markers"])
    if "marker" in k:
        return [k["marker"]]
    return []


def iter_patterns(rules: Dict) -> List[str]:
    """Every regex the rule set contains, in a stable order."""
    out: List[str] = []
    out.extend(rules.get("apk_structure", {}).values())
    for fw in rules.get("frameworks", []):
        out.extend(fw.get("markers", []))
        out.extend(fw.get("engines", {}).values())
    out.extend(kotlin_markers(rules))
    out.extend(item["marker"] for item in rules.get("embedded_js", []))
    out.extend(item["regex"] for item in rules.get("notable_libs", []))
    return out


def load_rules(path: Optional[str] = None) -> Dict:
    """Load and validate a rule set.

    Raises ``OSError`` if unreadable, ``ValueError`` if the JSON is malformed
    or a rule is missing required keys, and ``re.error`` if a marker is not a
    valid regex — all of which the CLI turns into a one-line message. Catching
    a bad pattern here rather than mid-scan keeps a typo in a custom rules file
    from surfacing as a traceback halfway through a batch.
    """
    with open(path or DEFAULT_RULES, "r", encoding="utf-8") as fh:
        rules = json.load(fh)

    if not isinstance(rules, dict):
        raise ValueError("rules file must contain a JSON object")
    # A kotlin block with neither key would disable Kotlin detection silently —
    # the same misspelling in a framework entry is already a load error. The
    # shape is checked too: a bare string reached `k["markers"]` and raised
    # TypeError, which is not one of the exceptions the CLI turns into a
    # message, and `"markers": "^x$"` degraded into one regex per character —
    # three patterns that match nearly every entry, so every APK read as Kotlin.
    kotlin = rules.get("kotlin")
    if kotlin is not None:
        if not isinstance(kotlin, dict):
            raise ValueError(f"kotlin rule must be an object, got {type(kotlin).__name__}")
        if "markers" in kotlin:
            if not isinstance(kotlin["markers"], list):
                raise ValueError("kotlin 'markers' must be a list of patterns")
        elif "marker" in kotlin:
            if not isinstance(kotlin["marker"], str):
                raise ValueError("kotlin 'marker' must be a string")
        else:
            raise ValueError("kotlin rule needs 'markers' (list) or 'marker' (string)")
    for fw in rules.get("frameworks", []):
        missing = [k for k in ("id", "name") if k not in fw]
        if missing:
            raise ValueError(f"framework entry missing {', '.join(missing)}: {fw!r}")
    for pattern in iter_patterns(rules):
        re.compile(pattern)
    return rules


def _dedup(values: List[str]) -> List[str]:
    return list(dict.fromkeys(values))


def classify_entries(entries: List[Entry], rules: Dict) -> Result:
    # match_path(), not innermost(path): '!' is a legal zip entry-name
    # character, so parsing the boundary back out of the display path
    # truncated real names and matched markers that were never there.
    paths = [e.match_path() for e in entries if not e.is_dir]

    # Precompile every pattern once; rules are few, entries can be thousands.
    compiled = {
        p: re.compile(p, re.IGNORECASE) for p in dict.fromkeys(iter_patterns(rules))
    }

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
        # A framework can require a runtime library to actually be present:
        # asset markers (a bundled JS bundle, an assets/ dir) corroborate but
        # must not claim a framework on their own — a bundled copy that
        # Android would never load is a payload, not a framework. When
        # ``requires`` is set, at least one of those markers must match.
        if matched_paths and fw.get("requires"):
            required = any(find(p) for p in fw["requires"])
            if not required:
                matched_paths = []
                matched_rules = []
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

    kotlin = any(find(m) for m in kotlin_markers(rules))

    embedded_js = [
        item["name"] for item in rules.get("embedded_js", []) if find(item["marker"])
    ]

    notable_libs = [
        item["label"] for item in rules.get("notable_libs", []) if find(item["regex"])
    ]

    # A verdict of "native" is only trustworthy if we actually saw an APK: a
    # manifest plus dex. Otherwise we were handed a fragment or a resource-only
    # split, and "no framework markers" means we could not tell.
    structure = rules.get("apk_structure", {})
    looks_like_an_apk = bool(structure) and all(find(p) for p in structure.values())

    won = winning_ids(hits)
    result = Result(
        source="",
        verdict=derive_verdict(hits, engines),
        confidence=derive_confidence(hits, looks_like_an_apk),
        framework=won[0] if len(won) == 1 else ("hybrid" if won else "native"),
        frameworks=won,
        engines=engines,
        kotlin=kotlin,
        embedded_js=embedded_js,
        notable_libs=notable_libs,
        markers={
            hid: h.paths[:MAX_PATHS_PER_FRAMEWORK] for hid, h in hits.items()
        },
    )
    return result


def winning_ids(hits: Dict[str, FrameworkHit]) -> List[str]:
    """Which framework(s) the verdict is actually about."""
    ids = set(hits)
    if "flutter" in ids and "react-native" in ids:
        return ["flutter", "react-native"]
    if "flutter" in ids:
        return ["flutter"]
    if "react-native" in ids:
        return ["react-native"]
    if ids:
        top = sorted(hits.values(), key=lambda h: (h.weight, len(h.paths)), reverse=True)[0]
        return [top.id]
    return []


def derive_verdict(hits: Dict[str, FrameworkHit], engines: List[str]) -> str:
    won = winning_ids(hits)
    if won == ["flutter", "react-native"]:
        return "Hybrid (Flutter + React Native)"
    if won == ["react-native"]:
        # A split set can ship both engines; naming only the first hid that.
        engine = f" ({'+'.join(engines)})" if engines else ""
        return "React Native" + engine
    if won:
        return hits[won[0]].name
    return "Native (no framework markers)"


def derive_confidence(hits: Dict[str, FrameworkHit], looks_like_an_apk: bool = False) -> str:
    """How much evidence backs *the reported verdict*.

    ``Low`` means "could not tell", never "the answer was native". A native
    verdict over a complete APK is a confident call — absence of every marker
    across a fully read package is real evidence — so it reports High. Low is
    reserved for input too thin to distinguish a native app from a fragment we
    could barely read.

    For a framework verdict the count covers the winning framework only:
    summing every framework's markers let an unrelated weak hit inflate the
    score, so a one-marker verdict could read High on someone else's evidence.
    """
    won = winning_ids(hits)
    if not won:
        return "High" if looks_like_an_apk else "Low"
    total = sum(len(hits[i].paths) for i in won)
    if total >= 2:
        return "High"
    return "Medium"

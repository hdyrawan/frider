"""The project conventions live in AGENTS.md, with CLAUDE.md pointing at it.

Two files describing the same rules drift apart, and the drift is invisible —
nothing fails when one of them goes stale. These tests keep AGENTS.md canonical
and make sure the pointer still points somewhere real.
"""

import json
import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
AGENTS = ROOT / "AGENTS.md"
CLAUDE = ROOT / "CLAUDE.md"
README = ROOT / "README.md"
RULES_JSON = ROOT / "frider" / "rules.json"


def test_agents_file_exists():
    assert AGENTS.is_file(), "AGENTS.md is the canonical conventions file"


def test_assistant_file_points_at_agents_rather_than_copying_it():
    """A second copy of the conventions would drift silently."""
    text = CLAUDE.read_text(encoding="utf-8")
    assert "AGENTS.md" in text, "CLAUDE.md must point at AGENTS.md"
    assert len(text.splitlines()) < 15, (
        "CLAUDE.md looks like it has grown its own copy of the conventions; "
        "keep the content in AGENTS.md"
    )


@pytest.mark.parametrize("topic,needle", [
    ("layout", "frider/rules.json"),
    ("test command", "pytest tests"),
    ("lint command", "ruff check"),
    ("authorship convention", "Co-Authored-By:"),
    ("rules-are-data", "rules.json"),
    ("the corpus caveat", "corpus_check.py"),
    ("single-line report cells", "single-line"),
    ("schema contract", "SCHEMA_VERSION"),
    ("release process", "testpypi"),
    ("scanned-app privacy", "anti-tamper-probe"),
])
def test_agents_file_covers(topic, needle):
    """Each of these was a real trap someone hit. Losing the note reopens it."""
    assert needle in AGENTS.read_text(encoding="utf-8"), f"AGENTS.md no longer covers {topic}"


def test_readme_documents_every_framework_id():
    """`framework` is the documented, stable id callers branch on. Adding a
    fingerprint without listing it leaves the contract's own docs wrong — which
    is how the README kept describing the superseded single-`marker` Kotlin
    rule long after the rule set had moved on."""
    ids = [fw["id"] for fw in json.loads(RULES_JSON.read_text(encoding="utf-8"))["frameworks"]]
    listed = re.search(r"stable id \(([^)]+)\)", README.read_text(encoding="utf-8"))
    assert listed, "README no longer documents the framework id list"
    documented = set(re.findall(r"`([a-z-]+)`", listed.group(1)))
    assert not set(ids) - documented, (
        f"README's framework id list is missing: {sorted(set(ids) - documented)}"
    )


def test_readme_rules_sample_matches_the_real_kotlin_rule():
    """The rules-format sample is copy-pasted by anyone writing a custom rules
    file; a superseded shape there teaches the wrong format."""
    rules = json.loads(RULES_JSON.read_text(encoding="utf-8"))
    readme = README.read_text(encoding="utf-8")
    for marker in rules["kotlin"]["markers"]:
        assert marker.replace("\\", "\\\\") in readme, (
            f"README's kotlin rule sample omits {marker}"
        )


def test_no_scanned_banking_app_is_named_in_the_tree():
    """This repository is public: a package name paired with a framework or
    packer is a target list tied to a named institution. Findings from such an
    app go in generically; the detail lives in the private repo."""
    here = pathlib.Path(__file__).resolve()
    # .github is deliberately scanned; only caches, build output and any local
    # corpus are skipped.
    skip_dirs = {".git", ".ruff_cache", ".pytest_cache", ".mypy_cache", "__pycache__",
                 ".venv", "venv", "node_modules", "dist", "build", "corpus"}
    text_suffixes = {".md", ".py", ".json", ".yml", ".yaml", ".toml", ".txt", ".cfg"}
    leaked = []
    for path in ROOT.rglob("*"):
        if not path.is_file() or path.suffix not in text_suffixes:
            continue
        if any(part in skip_dirs for part in path.relative_to(ROOT).parts[:-1]):
            continue
        if path.resolve() == here:
            continue  # this file necessarily spells the names it searches for
        text = path.read_text(encoding="utf-8", errors="replace").lower()
        for needle in ("digibank", "bumi arta", "mlpt.siemo"):
            if needle in text:
                leaked.append(f"{path.name}: {needle}")
    assert not leaked, f"named banking apps in a public tree: {leaked}"


def test_agents_file_names_no_assistant_vendor():
    """The repository's own convention: no assistant or vendor names in tree."""
    text = AGENTS.read_text(encoding="utf-8").lower()
    for name in ("claude", "anthropic", "copilot", "openai", "gemini", "cursor"):
        # "CLAUDE.md" as a filename reference is unavoidable; a bare mention is not
        assert name not in text.replace("claude.md", ""), f"AGENTS.md names {name}"

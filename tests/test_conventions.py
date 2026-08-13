"""The project conventions live in AGENTS.md, with CLAUDE.md pointing at it.

Two files describing the same rules drift apart, and the drift is invisible —
nothing fails when one of them goes stale. These tests keep AGENTS.md canonical
and make sure the pointer still points somewhere real.
"""

import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
AGENTS = ROOT / "AGENTS.md"
CLAUDE = ROOT / "CLAUDE.md"


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
])
def test_agents_file_covers(topic, needle):
    """Each of these was a real trap someone hit. Losing the note reopens it."""
    assert needle in AGENTS.read_text(encoding="utf-8"), f"AGENTS.md no longer covers {topic}"


def test_agents_file_names_no_assistant_vendor():
    """The repository's own convention: no assistant or vendor names in tree."""
    text = AGENTS.read_text(encoding="utf-8").lower()
    for name in ("claude", "anthropic", "copilot", "openai", "gemini", "cursor"):
        # "CLAUDE.md" as a filename reference is unavoidable; a bare mention is not
        assert name not in text.replace("claude.md", ""), f"AGENTS.md names {name}"

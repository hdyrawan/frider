"""Tests for the corpus harness itself.

The harness is what turns "the fingerprints look right" into a number, so it
has to be trustworthy on its own: a harness that quietly scores an empty
corpus, or that reports success when a label is misspelled, would be worse than
none at all.

The measurement against *real* APKs cannot run in CI — it needs a labelled
corpus on disk. That test is opt-in via ``FRIDER_CORPUS``.
"""

import importlib.util
import io
import json
import os
import pathlib
import zipfile

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("corpus_check", ROOT / "tools" / "corpus_check.py")
corpus_check = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(corpus_check)

BASE = {"AndroidManifest.xml": b"<m/>", "classes.dex": b"d"}

FLUTTER = {"lib/arm64-v8a/libflutter.so": b"e", "assets/flutter_assets/x.json": b"{}"}
RN = {"assets/index.android.bundle": b"j", "lib/arm64-v8a/libhermes.so": b"h"}
UNITY = {"lib/arm64-v8a/libunity.so": b"u"}


def put(corpus, label, name, extra):
    d = corpus / label
    d.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(d / name, "w") as z:
        for k, v in {**BASE, **extra}.items():
            z.writestr(k, v)


@pytest.fixture
def corpus(tmp_path):
    return tmp_path / "corpus"


def test_a_correct_corpus_scores_100_and_exits_zero(corpus, capsys):
    put(corpus, "flutter", "a.apk", FLUTTER)
    put(corpus, "react-native", "b.apk", RN)
    put(corpus, "native", "c.apk", {"resources.arsc": b"a"})

    assert corpus_check.main([str(corpus)]) == 0
    out = capsys.readouterr().out
    assert "3/3 correct — 100.0% accuracy" in out


def test_a_misclassification_is_reported_and_fails(corpus, capsys):
    put(corpus, "native", "mislabelled.apk", UNITY)
    put(corpus, "flutter", "ok.apk", FLUTTER)

    assert corpus_check.main([str(corpus)]) == 1
    out = capsys.readouterr().out
    assert "unityx1" in out, "the confusion should name what it was mistaken for"
    assert "expected native, got unity" in out


def test_min_accuracy_gates_the_exit_code(corpus):
    put(corpus, "native", "bad.apk", UNITY)
    for i in range(4):
        put(corpus, "flutter", f"ok{i}.apk", FLUTTER)

    assert corpus_check.main([str(corpus), "--min-accuracy", "80"]) == 0
    assert corpus_check.main([str(corpus), "--min-accuracy", "90"]) == 1


def test_an_empty_corpus_fails_rather_than_claiming_success(corpus, capsys):
    """A harness that scores nothing must not look like a pass."""
    corpus.mkdir(parents=True)
    assert corpus_check.main([str(corpus)]) == 1
    assert "corpus is empty" in capsys.readouterr().out


def test_a_misspelled_label_is_rejected(corpus):
    """Otherwise every APK under it silently counts as wrong — or worse, the
    directory is skipped and the corpus quietly shrinks."""
    put(corpus, "flutter", "a.apk", FLUTTER)
    (corpus / "flutterr").mkdir()

    with pytest.raises(SystemExit) as exc:
        corpus_check.main([str(corpus)])
    assert "flutterr" in str(exc.value)


def test_ignore_directory_is_skipped(corpus, capsys):
    put(corpus, "flutter", "a.apk", FLUTTER)
    (corpus / "_ignore").mkdir()
    (corpus / "_ignore" / "junk.apk").write_bytes(b"not a zip at all")

    assert corpus_check.main([str(corpus)]) == 0
    assert "1/1 correct" in capsys.readouterr().out


def test_unreadable_apk_counts_as_a_failure_not_a_crash(corpus, capsys):
    put(corpus, "flutter", "good.apk", FLUTTER)
    (corpus / "flutter" / "truncated.apk").write_bytes(b"PK\x03\x04nope")

    assert corpus_check.main([str(corpus)]) == 1
    assert "not a zip/apk" in capsys.readouterr().out


def test_json_output_records_every_case(corpus, tmp_path):
    put(corpus, "flutter", "a.apk", FLUTTER)
    put(corpus, "native", "b.apk", UNITY)
    out = tmp_path / "acc.json"

    corpus_check.main([str(corpus), "--json", str(out)])
    payload = json.loads(out.read_text(encoding="utf-8"))

    assert payload["total"] == 2
    assert payload["correct"] == 1
    assert payload["accuracy"] == 50.0
    assert {c["expected"] for c in payload["cases"]} == {"flutter", "native"}
    assert any(c["got"] == "unity" for c in payload["cases"])


def test_labels_cover_every_framework_in_the_rules():
    """A framework with no permitted label directory could never be measured."""
    from frider.rules import load_rules

    rules = load_rules()
    labels = set(corpus_check.known_labels(rules))
    assert {fw["id"] for fw in rules["frameworks"]} <= labels
    assert {"native", "hybrid"} <= labels


def test_missing_corpus_directory_is_a_clean_error(tmp_path, capsys):
    assert corpus_check.main([str(tmp_path / "nope")]) == 2
    assert "not a directory" in capsys.readouterr().err


# ---- the real measurement, opt-in ----

@pytest.mark.skipif(not os.environ.get("FRIDER_CORPUS"),
                    reason="set FRIDER_CORPUS=/path/to/corpus to measure against real APKs")
def test_real_corpus_meets_the_accuracy_floor():
    """Run against a labelled corpus of real APKs.

    Set FRIDER_CORPUS to the corpus directory, and optionally
    FRIDER_CORPUS_MIN_ACCURACY (default 100) to allow known misses while the
    rules are still being tuned.
    """
    from frider.rules import load_rules

    corpus_dir = os.environ["FRIDER_CORPUS"]
    floor = float(os.environ.get("FRIDER_CORPUS_MIN_ACCURACY", "100"))

    cases = corpus_check.run(corpus_dir, load_rules())
    assert cases, f"no APKs found under {corpus_dir}"

    buf = io.StringIO()
    accuracy = corpus_check.report(cases, stream=buf)
    assert accuracy >= floor, "\n" + buf.getvalue()

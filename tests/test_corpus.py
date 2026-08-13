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
    apk = d / name
    apk.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(apk, "w") as z:
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


def test_split_apk_subdirectory_is_scored_as_one_set(corpus, capsys):
    """A split-APK pull in its own subdirectory must count as a single case.

    The framework markers live in the base APK; resource-only config splits
    carry none. Counting every file individually would misread the config
    splits as "native" apps and drag a 3-file set down to 33% accuracy even
    though the CLI's directory mode (which this mirrors) scores it 100%.
    """
    # base.apk has the framework markers; the config splits are resource-only.
    put(corpus, "flutter", "app-split/base.apk", FLUTTER)
    put(corpus, "flutter", "app-split/config.arm64_v8a.apk", {"resources.arsc": b"a"})
    put(corpus, "flutter", "app-split/config.en.apk", {"res/values-en/strings.xml": b"s"})
    # A loose single-APK case alongside must still count on its own.
    put(corpus, "flutter", "standalone.apk", FLUTTER)

    assert corpus_check.main([str(corpus)]) == 0
    out = capsys.readouterr().out
    assert "2/2 correct — 100.0% accuracy" in out


def test_split_apk_set_without_framework_markers_still_fails(corpus, capsys):
    """A subdirectory is one case, so a genuinely native split set scores as
    a native app — and a Flutter label on it is a real, reported mismatch."""
    put(corpus, "flutter", "mislabel-split/base.apk", {"resources.arsc": b"a"})
    put(corpus, "flutter", "mislabel-split/config.arm64_v8a.apk", {"resources.arsc": b"a"})

    assert corpus_check.main([str(corpus)]) == 1
    out = capsys.readouterr().out
    assert "expected flutter, got native" in out


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


# ---- the real-APK fetcher ----

_fetch_spec = importlib.util.spec_from_file_location(
    "fetch_sample_corpus", ROOT / "tools" / "fetch_sample_corpus.py")
fetch_sample_corpus = importlib.util.module_from_spec(_fetch_spec)
_fetch_spec.loader.exec_module(fetch_sample_corpus)


def test_every_declared_source_uses_a_label_the_checker_accepts():
    """A typo'd label would make corpus_check reject the whole fetched tree."""
    from frider.rules import load_rules

    labels = set(corpus_check.known_labels(load_rules()))
    for src in fetch_sample_corpus.SOURCES:
        assert src.label in labels, f"{src.package} declares unknown label {src.label!r}"
        assert src.registry in ("pypi", "npm"), src.registry


def test_extract_apks_pulls_only_apks_and_namespaces_them(tmp_path):
    """Archives carry plenty of other files, and two packages can ship an APK
    of the same basename — the package prefix keeps them apart."""
    import tarfile

    archive = tmp_path / "pkg.tgz"
    with tarfile.open(archive, "w:gz") as tar:
        for name, body in [("pkg/app-debug.apk", b"APK"),
                           ("pkg/README.md", b"docs"),
                           ("pkg/nested/other.apk", b"APK2")]:
            data = io.BytesIO(body)
            info = tarfile.TarInfo(name)
            info.size = len(body)
            tar.addfile(info, data)

    dest = tmp_path / "out"
    dest.mkdir()
    src = fetch_sample_corpus.Source("npm", "demo-pkg", "native", "")
    written = sorted(fetch_sample_corpus.extract_apks(archive.read_bytes(), src, str(dest)))

    assert written == ["demo-pkg__app-debug.apk", "demo-pkg__other.apk"]
    assert not (dest / "README.md").exists()
    assert (dest / "demo-pkg__app-debug.apk").read_bytes() == b"APK"


def test_fetcher_reports_failure_rather_than_an_empty_corpus(tmp_path, monkeypatch, capsys):
    """Offline, this must fail loudly — an empty corpus that exits 0 would look
    like a passing real-APK check while measuring nothing."""
    def boom(url):
        raise OSError("network unreachable")

    monkeypatch.setattr(fetch_sample_corpus, "_get", boom)
    assert fetch_sample_corpus.main([str(tmp_path / "corpus")]) == 1
    assert "no APKs fetched" in capsys.readouterr().err


@pytest.mark.skipif(not os.environ.get("FRIDER_FETCH_CORPUS"),
                    reason="set FRIDER_FETCH_CORPUS=1 to download real APKs from PyPI and npm")
def test_real_native_apks_do_not_trip_any_framework_rule(tmp_path):
    """The live check: real Android builds, thousands of real entry names, and
    no framework marker may fire on any of them."""
    from frider.rules import load_rules

    corpus = tmp_path / "corpus"
    assert fetch_sample_corpus.main([str(corpus)]) == 0

    cases = corpus_check.run(str(corpus), load_rules())
    assert cases, "fetcher produced no APKs"

    buf = io.StringIO()
    accuracy = corpus_check.report(cases, stream=buf)
    assert accuracy == 100.0, "\n" + buf.getvalue()


def test_a_subdirectory_holding_no_apk_is_not_a_case(corpus, capsys):
    """Regression: an APK-less directory scans as "no framework markers", so a
    scratch folder under native/ counted as a *passing* case and inflated
    accuracy — the empty-corpus guard's failure mode, one level down."""
    put(corpus, "flutter", "real.apk", FLUTTER)
    (corpus / "native" / "scratch").mkdir(parents=True)
    (corpus / "native" / "scratch" / ".gitkeep").write_text("", encoding="utf-8")
    (corpus / "flutter" / "notes-only").mkdir()
    (corpus / "flutter" / "notes-only" / "TODO.txt").write_text("wip", encoding="utf-8")

    assert corpus_check.main([str(corpus)]) == 0
    captured = capsys.readouterr()

    assert "1/1 correct — 100.0% accuracy" in captured.out, \
        "phantom cases are still being counted"
    # the native label had only a scratch folder, so it must not appear as a row
    rows = [ln.split()[0] for ln in captured.out.splitlines()
            if ln and not ln.startswith(("expected", "-", " "))]
    assert "native" not in rows, f"phantom native case counted: {rows}"
    # both skips announced, so a dropped directory is never silent
    assert "skipping native/scratch — holds no APK" in captured.err
    assert "skipping flutter/notes-only — holds no APK" in captured.err


def test_a_split_set_directory_is_still_one_case(corpus, capsys):
    """The skip must not swallow a genuine split-APK pull."""
    split = corpus / "flutter" / "myapp-split"
    split.mkdir(parents=True)
    with zipfile.ZipFile(split / "base.apk", "w") as z:
        z.writestr("AndroidManifest.xml", b"<m/>")
        z.writestr("classes.dex", b"d")
        z.writestr("lib/arm64-v8a/libflutter.so", b"e")
    with zipfile.ZipFile(split / "config.en.apk", "w") as z:
        z.writestr("AndroidManifest.xml", b"<m/>")
        z.writestr("res/values/strings.arsc", b"x")

    assert corpus_check.main([str(corpus)]) == 0
    out = capsys.readouterr().out
    assert "1/1 correct" in out, "a split set must score once, not per file"

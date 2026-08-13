"""frider tests — build tiny fixture APK zips in tmp and assert classifications."""

import io
import json
import os
import pathlib
import re
import zipfile

import pytest

from frider import cli
from frider.apk import entries_for, innermost
from frider.cli import build_parser, main
from frider.rules import classify_entries, load_rules

RULES = load_rules()


def make_apk(path, members):
    """members: dict of path -> bytes (or None for a dir entry)."""
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in members.items():
            if data is None:
                zf.writestr(name, b"")
            else:
                zf.writestr(name, data)
    return path


@pytest.fixture
def flutter_apk(tmp_path):
    return make_apk(tmp_path / "flutter.apk", {
        "AndroidManifest.xml": b"<manifest/>",
        "classes.dex": b"dex",
        "lib/arm64-v8a/libflutter.so": b"engine",
        "lib/arm64-v8a/libapp.so": b"aot",
        "assets/flutter_assets/AssetManifest.json": b"{}",
    })


@pytest.fixture
def rn_hermes_apk(tmp_path):
    return make_apk(tmp_path / "rn.apk", {
        "AndroidManifest.xml": b"<manifest/>",
        "classes.dex": b"dex",
        "assets/index.android.bundle": b"js",
        "lib/arm64-v8a/libhermes.so": b"hermes",
        "lib/arm64-v8a/libreactnativejni.so": b"rn",
        "lib/arm64-v8a/libjsi.so": b"jsi",
        "lib/arm64-v8a/libfbjni.so": b"fbjni",
    })


@pytest.fixture
def rn_jsc_apk(tmp_path):
    return make_apk(tmp_path / "rn-jsc.apk", {
        "AndroidManifest.xml": b"<manifest/>",
        "classes.dex": b"dex",
        "assets/index.android.bundle": b"js",
        "lib/arm64-v8a/libjsc.so": b"jsc",
        "lib/arm64-v8a/libreactnativejni.so": b"rn",
    })


@pytest.fixture
def native_apk(tmp_path):
    return make_apk(tmp_path / "native.apk", {
        "AndroidManifest.xml": b"<manifest/>",
        "classes.dex": b"dex",
        "META-INF/main.kotlin_module": b"k",
        "lib/arm64-v8a/libtoolChecker.so": b"rootbeer",
    })


@pytest.fixture
def hybrid_apk(tmp_path):
    return make_apk(tmp_path / "hybrid.apk", {
        "lib/arm64-v8a/libflutter.so": b"engine",
        "assets/flutter_assets/AssetManifest.json": b"{}",
        "assets/index.android.bundle": b"js",
        "lib/arm64-v8a/libhermes.so": b"hermes",
    })


@pytest.fixture
def cordova_apk(tmp_path):
    return make_apk(tmp_path / "cordova.apk", {
        "assets/www/index.html": b"<html></html>",
        "assets/www/cordova.js": b"cordova",
        "res/xml/config.xml": b"<widget/>",
    })


@pytest.fixture
def xapk_container(tmp_path):
    inner = io.BytesIO()
    with zipfile.ZipFile(inner, "w") as zf:
        zf.writestr("lib/arm64-v8a/libflutter.so", b"engine")
        zf.writestr("assets/flutter_assets/AssetManifest.json", b"{}")
    return make_apk(tmp_path / "app.xapk", {
        "app.apk": inner.getvalue(),
        "config.json": b"{}",
    })


def classify(path):
    return classify_entries(entries_for(path), RULES)


def test_flutter(flutter_apk):
    r = classify(str(flutter_apk))
    assert r.verdict == "Flutter / Dart"
    assert r.confidence == "High"
    assert r.engines == []
    assert r.kotlin is False


def test_rn_hermes(rn_hermes_apk):
    r = classify(str(rn_hermes_apk))
    assert r.verdict == "React Native (hermes)"
    assert r.confidence == "High"
    assert "hermes" in r.engines
    assert "jsc" not in r.engines


def test_rn_jsc_is_not_hermes(rn_jsc_apk):
    """The whole reason frider exists: JavaScriptCore is not Hermes."""
    r = classify(str(rn_jsc_apk))
    assert r.verdict == "React Native (jsc)"
    assert "jsc" in r.engines
    assert "hermes" not in r.engines


def test_native_with_kotlin_and_notable_lib(native_apk):
    r = classify(str(native_apk))
    assert r.verdict == "Native (no framework markers)"
    assert r.kotlin is True
    assert any("RootBeer" in label for label in r.notable_libs)


def test_kotlin_detected_when_r8_strips_kotlin_module(tmp_path):
    """R8 minification strips ``.kotlin_module`` but keeps ``kotlin/*.kotlin_builtins``
    and the ``kotlinx *.version`` stamps. A real Kotlin app must still read as
    Kotlin. Regression for a real minified-banking-app miss (2026-08-13)."""
    apk = make_apk(tmp_path / "r8-kotlin.apk", {
        "AndroidManifest.xml": b"<manifest/>",
        "classes.dex": b"dex",
        "kotlin/kotlin.kotlin_builtins": b"k",
        "META-INF/kotlinx_coroutines_core.version": b"1.7",
    })
    r = classify(str(apk))
    assert r.framework == "native"
    assert r.kotlin is True


def test_no_kotlin_stays_false(tmp_path):
    """A plain Java app (no Kotlin markers) must not be misread as Kotlin."""
    apk = make_apk(tmp_path / "plain-java.apk", {
        "AndroidManifest.xml": b"<manifest/>",
        "classes.dex": b"dex",
        "META-INF/androidx.core_core.version": b"1.0",
    })
    r = classify(str(apk))
    assert r.kotlin is False


def test_kotlin_legacy_single_marker_rule_still_loads(tmp_path):
    """The rule set accepts either ``markers`` (current) or a single ``marker``
    (what shipped before R8-stripped apps forced the list form). A custom rules
    file written against the old shape must keep working."""
    legacy = {"kotlin": {"marker": "^META-INF/.*\\.kotlin_module$"}, "frameworks": []}
    apk = make_apk(tmp_path / "legacy.apk", {
        "AndroidManifest.xml": b"<manifest/>",
        "classes.dex": b"dex",
        "META-INF/app_release.kotlin_module": b"k",
    })
    assert classify_entries(entries_for(str(apk)), legacy).kotlin is True


def test_kotlin_rule_with_neither_key_is_a_load_error(tmp_path):
    """A typo'd key would otherwise switch Kotlin detection off in silence, and
    report every app as `kotlin: false` with no indication why."""
    bad = tmp_path / "bad-rules.json"
    bad.write_text('{"kotlin": {"markerz": ["^x$"]}, "frameworks": []}', encoding="utf-8")
    with pytest.raises(ValueError, match="kotlin rule needs"):
        load_rules(str(bad))


@pytest.mark.parametrize("body,match", [
    # A bare string reached k["markers"] and raised TypeError, which main()
    # does not catch — so a hand-edited rules file printed a traceback.
    ('{"kotlin": "marker"}', "must be an object"),
    ('{"kotlin": ["^x$"]}', "must be an object"),
    ('{"kotlin": {"marker": 5}}', "'marker' must be a string"),
    # list("^x$") is ['^', 'x', '$']: three patterns matching nearly every
    # entry, so every APK read as Kotlin. Worse than a crash — silently wrong.
    ('{"kotlin": {"markers": "^x$"}}', "must be a list"),
    ('{"kotlin": {"markers": 5}}', "must be a list"),
])
def test_misshapen_kotlin_rule_is_a_clean_error(tmp_path, body, match):
    """`main()` catches OSError, ValueError and re.error and turns them into a
    one-line message; anything else reaches the user as a traceback."""
    bad = tmp_path / "bad-shape.json"
    bad.write_text(body, encoding="utf-8")
    with pytest.raises(ValueError, match=match):
        load_rules(str(bad))


def test_hybrid(hybrid_apk):
    r = classify(str(hybrid_apk))
    assert r.verdict == "Hybrid (Flutter + React Native)"


def test_cordova(cordova_apk):
    r = classify(str(cordova_apk))
    assert "Cordova" in r.verdict


def test_xapk_container_sees_inner_apk(xapk_container):
    r = classify(str(xapk_container))
    assert r.verdict == "Flutter / Dart"


def test_markers_record_real_matched_paths(flutter_apk):
    """Regression: markers must name the actual entries, not the rule regexes."""
    r = classify(str(flutter_apk))
    paths = r.markers["flutter"]
    assert "lib/arm64-v8a/libflutter.so" in paths
    assert "assets/flutter_assets/AssetManifest.json" in paths
    assert not any(p.startswith("lib/[^/]") for p in paths)


def test_reader_works_after_entries_returned(flutter_apk):
    """Regression: file-backed readers reopen the zip, so calling read()
    after entries_for() returns must not hit a closed handle."""
    entries = entries_for(str(flutter_apk))
    target = next(e for e in entries if e.path.endswith("libflutter.so"))
    assert target.read is not None
    assert target.read() == b"engine"


def test_xapk_nested_reader_works(xapk_container):
    """Regression: nested (BytesIO-backed) entries read fine too."""
    entries = entries_for(str(xapk_container))
    target = next(e for e in entries if e.path.endswith("libflutter.so"))
    assert target.read is not None
    assert target.read() == b"engine"


def test_innermost_path_helper():
    assert innermost("app.apk!lib/arm64-v8a/libflutter.so") == "lib/arm64-v8a/libflutter.so"
    assert innermost("lib/arm64-v8a/libflutter.so") == "lib/arm64-v8a/libflutter.so"


def test_directory_mode(tmp_path):
    make_apk(tmp_path / "a.apk", {"lib/arm64-v8a/libflutter.so": b"e"})
    make_apk(tmp_path / "b.apk", {"classes.dex": b"d"})
    results = [classify(str(tmp_path / n)) for n in ("a.apk", "b.apk")]
    assert results[0].verdict == "Flutter / Dart"
    assert results[1].verdict == "Native (no framework markers)"


def test_directory_mode_reads_splits_as_one_set(tmp_path):
    """A dir of pulled split APKs is one classification (union of entries)."""
    make_apk(tmp_path / "apk_0.apk", {"classes.dex": b"d", "AndroidManifest.xml": b"<m/>"})
    make_apk(tmp_path / "apk_1.apk", {"lib/arm64-v8a/libflutter.so": b"e"})
    r = classify(str(tmp_path))
    assert r.verdict == "Flutter / Dart"


# ---- CLI parsing (regression for the --adb ambiguity) ----

def test_parser_adb_flag_separates_serial_from_packages():
    args = build_parser().parse_args(["--adb", "--serial", "X", "com.a", "com.b"])
    assert args.adb is True
    assert args.serial == "X"
    assert args.paths == ["com.a", "com.b"]


def test_parser_adb_flag_without_serial_keeps_positionals_as_packages():
    """Regression: `frider --adb com.example.app` must treat the positional as
    a PACKAGE, not as the serial (the old optional-value --adb ate it)."""
    args = build_parser().parse_args(["--adb", "com.example.app"])
    assert args.adb is True
    assert args.serial is None
    assert args.paths == ["com.example.app"]


def test_parser_plain_paths_are_not_adb_mode():
    args = build_parser().parse_args(["app.apk", "dir/"])
    assert args.adb is False
    assert args.paths == ["app.apk", "dir/"]


def test_module_entry_exit_codes_propagate(flutter_apk, tmp_path):
    """Regression: `python3 -m frider` must exit non-zero on errors, not 0."""
    import subprocess
    import sys

    ok = subprocess.run([sys.executable, "-m", "frider", str(flutter_apk), "--no-color"],
                        capture_output=True, text=True)
    assert ok.returncode == 0

    bad = subprocess.run(
        [sys.executable, "-m", "frider", str(tmp_path / "missing.apk"), "--no-color"],
        capture_output=True, text=True)
    assert bad.returncode == 1
    assert "ERROR" in bad.stdout


def test_corrupt_zip_is_clean_error(tmp_path):
    """Regression: a file with zip magic but a broken central directory must
    produce an ERROR row (exit 1), never a traceback."""
    import struct
    import subprocess
    import sys
    import zipfile as zf_mod

    local = (b"PK\x03\x04" + struct.pack("<HHHHH", 20, 0, 0, 0, 0)
             + b"a.txt" + b"\x00" * 16 + b"hello")
    eocd = b"PK\x05\x06" + struct.pack("<HHHHIIH", 0, 0, 1, 1, 64, 40, 0)
    corrupt = tmp_path / "corrupt.apk"
    corrupt.write_bytes(local + b"\x90" * 64 + eocd)
    assert zf_mod.is_zipfile(str(corrupt))  # passes the magic check...
    with pytest.raises(zf_mod.BadZipFile):
        zf_mod.ZipFile(str(corrupt)).infolist()  # ...but breaks on open

    r = subprocess.run([sys.executable, "-m", "frider", str(corrupt), "--no-color"],
                       capture_output=True, text=True)
    assert r.returncode == 1
    assert "ERROR" in r.stdout
    assert "corrupt zip" in r.stdout
    assert "Traceback" not in r.stderr


# ---- regressions for the review round ----

def test_colored_table_columns_stay_aligned(flutter_apk, native_apk):
    """Regression: cells were padded with str.ljust AFTER coloring, so the
    ANSI escapes counted toward the width and every colored row came out
    ragged. Rows must be as wide as the separator, colors on or off."""
    from frider.report import render_table
    from frider.ui import Palette

    results = [classify(str(flutter_apk)), classify(str(native_apk))]
    for palette in (Palette(enabled=False), Palette(enabled=True)):
        lines = render_table(results, palette=palette).splitlines()
        sep_width = len(lines[0])
        visible = [re.sub(r"\x1b\[[0-9;]*m", "", ln) for ln in lines]
        assert all(len(v) == sep_width for v in visible), (
            f"ragged table (colors={palette.enabled}): "
            f"{[len(v) for v in visible]} vs sep {sep_width}"
        )


def test_unreadable_apk_in_set_errors_instead_of_reading_native(tmp_path):
    """Regression: a truncated pull is not a zip, so it used to be surfaced as
    an opaque file entry and the set classified as "native" — a silently wrong
    answer for a file frider could not read."""
    d = tmp_path / "pulled"
    d.mkdir()
    make_apk(d / "apk_0.apk", {"classes.dex": b"d"})
    (d / "apk_1.apk").write_bytes(b"PK\x03\x04truncated-download")

    with pytest.raises(ValueError, match="unreadable apk"):
        entries_for(str(d))


def test_loose_non_apk_files_are_still_tolerated(tmp_path):
    """...but a non-APK payload beside the splits is fine and stays lazy."""
    d = tmp_path / "pulled"
    d.mkdir()
    make_apk(d / "apk_0.apk", {"lib/arm64-v8a/libflutter.so": b"e"})
    (d / "assets.obb").write_bytes(b"\x00" * 1024)

    r = classify_entries(entries_for(str(d)), RULES)
    assert r.verdict == "Flutter / Dart"


def test_loose_file_reader_is_lazy_not_slurped(tmp_path):
    """Regression: loose files were read into memory eagerly even though
    classification only ever looks at entry names."""
    d = tmp_path / "pulled"
    d.mkdir()
    payload = d / "big.obb"
    payload.write_bytes(b"abc")
    entry = next(e for e in entries_for(str(d)) if e.path == "big.obb")
    payload.write_bytes(b"xyz")  # changed after entries_for() returned
    assert entry.read() == b"xyz", "reader captured stale bytes at scan time"


def test_confidence_counts_only_the_winning_framework(tmp_path):
    """Regression: confidence summed markers across ALL frameworks, so an
    unrelated weak hit could push a one-marker verdict up to High."""
    apk = make_apk(tmp_path / "mixed.apk", {
        "lib/arm64-v8a/libkony.so": b"k",       # winner, 1 marker
        "assets/www/index.html": b"<html/>",    # unrelated cordova hit
    })
    r = classify(str(apk))
    assert r.verdict == "Kony (Temenos)"
    assert r.confidence == "Medium"


def test_generic_config_xml_is_not_cordova(tmp_path):
    """Regression: res/xml/config.xml is a generic Android resource path that
    plenty of native apps and SDKs ship — it must not alone mean Cordova."""
    apk = make_apk(tmp_path / "sdk.apk", {
        "classes.dex": b"d",
        "AndroidManifest.xml": b"<m/>",
        "res/xml/config.xml": b"<config/>",
    })
    assert classify(str(apk)).verdict == "Native (no framework markers)"


def test_fbjni_alone_is_not_react_native(tmp_path):
    """Regression: fbjni ships with several Meta libraries (SoLoader, Fresco,
    Flipper) in apps that have no React Native at all."""
    apk = make_apk(tmp_path / "fb.apk", {
        "classes.dex": b"d",
        "lib/arm64-v8a/libfbjni.so": b"fb",
    })
    assert classify(str(apk)).verdict == "Native (no framework markers)"


def test_both_engines_are_both_reported(tmp_path):
    """A split set can ship Hermes and JSC; naming only the first hid that."""
    apk = make_apk(tmp_path / "both.apk", {
        "assets/index.android.bundle": b"js",
        "lib/arm64-v8a/libhermes.so": b"h",
        "lib/arm64-v8a/libjsc.so": b"jsc",
    })
    r = classify(str(apk))
    assert set(r.engines) == {"hermes", "jsc"}
    assert "hermes" in r.verdict and "jsc" in r.verdict


def test_deeply_nested_ionic_bundle_is_detected(tmp_path):
    """Real Ionic builds nest deeper than one directory under assets/www."""
    apk = make_apk(tmp_path / "ionic.apk", {
        "assets/www/index.html": b"<html/>",
        "assets/www/build/vendor/ionic.bundle.js": b"i",
    })
    assert "ionic" in classify(str(apk)).markers


def test_bad_rules_file_is_a_clean_error_not_a_traceback(tmp_path):
    """Regression: a missing/invalid --rules file raised straight out of
    load_rules as FileNotFoundError / JSONDecodeError / re.error."""
    import subprocess
    import sys

    bad_json = tmp_path / "bad.json"
    bad_json.write_text("{ not json")
    bad_regex = tmp_path / "badrx.json"
    bad_regex.write_text('{"frameworks":[{"id":"x","name":"X","markers":["lib/(oops"]}]}')

    for rules_arg in (str(tmp_path / "missing.json"), str(bad_json), str(bad_regex)):
        r = subprocess.run(
            [sys.executable, "-m", "frider", "--rules", rules_arg, "app.apk", "--no-color"],
            capture_output=True, text=True,
        )
        assert r.returncode == 2, rules_arg
        assert "Traceback" not in r.stderr, rules_arg
        assert "cannot load rules" in r.stderr, rules_arg


def test_load_rules_rejects_malformed_framework_entry(tmp_path):
    f = tmp_path / "r.json"
    f.write_text('{"frameworks":[{"name":"no id here","markers":[]}]}')
    with pytest.raises(ValueError, match="missing id"):
        load_rules(str(f))


# ---- adb pull behaviour (previously untested) ----

@pytest.fixture
def fake_adb(monkeypatch, tmp_path):
    """Stub subprocess.run so adb behaviour is testable without a device."""
    import subprocess as sp

    state = {"splits": ["/data/app/base.apk"], "payload": None, "calls": []}

    def fake_run(cmd, **kw):
        state["calls"].append(cmd)
        if "path" in cmd:
            out = "".join(f"package:{p}\r\n" for p in state["splits"])
            return sp.CompletedProcess(cmd, 0, out, "")
        if "pull" in cmd:
            dest = cmd[-1]
            payload = state["payload"]
            if payload is None:
                make_apk(dest, {"classes.dex": b"d"})
            else:
                open(dest, "wb").write(payload)
            return sp.CompletedProcess(cmd, 0, "1 file pulled", "")
        return sp.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(sp, "run", fake_run)
    return state


def test_pull_clears_stale_splits_from_cache(fake_adb, tmp_path):
    """Regression: the cache dir was reused with exist_ok=True, so a package
    that used to ship more splits left stale apk_N.apk files behind and they
    were classified as part of the new set."""
    from frider.adb import pull_package

    cache = str(tmp_path / "cache")
    fake_adb["splits"] = ["/data/app/base.apk", "/data/app/split_config.apk"]
    d, count = pull_package("SERIAL", "com.example", cache)
    assert count == 2
    # leave a marker only the stale split would carry
    make_apk(os.path.join(d, "apk_1.apk"), {"lib/arm64-v8a/libflutter.so": b"e"})
    assert classify_entries(entries_for(d), RULES).verdict == "Flutter / Dart"

    # the app updates and now ships a single split
    fake_adb["splits"] = ["/data/app/base.apk"]
    d, count = pull_package("SERIAL", "com.example", cache)
    assert count == 1
    assert sorted(os.listdir(d)) == ["apk_0.apk"], "stale split survived the re-pull"
    assert classify_entries(entries_for(d), RULES).verdict == "Native (no framework markers)"


def test_pulled_but_unreadable_apk_never_reports_native(fake_adb, tmp_path):
    """Regression: adb exits 0 but writes a truncated file — that used to be
    treated as an opaque blob and the package classified as native."""
    from frider.adb import pull_package

    fake_adb["payload"] = b"PK\x03\x04truncated"
    d, _ = pull_package("SERIAL", "com.example", str(tmp_path / "cache"))
    with pytest.raises(ValueError, match="unreadable apk"):
        entries_for(d)


def test_adb_missing_binary_is_a_clean_error(monkeypatch):
    import subprocess as sp

    from frider.adb import AdbError, apk_paths

    def boom(cmd, **kw):
        raise FileNotFoundError(2, "No such file or directory", "adb")

    monkeypatch.setattr(sp, "run", boom)
    with pytest.raises(AdbError, match="adb not found on PATH"):
        apk_paths("SERIAL", "com.example")


def test_adb_hang_is_bounded_by_timeout(monkeypatch):
    import subprocess as sp

    from frider.adb import AdbError, list_third_party_packages

    def hang(cmd, **kw):
        raise sp.TimeoutExpired(cmd, kw.get("timeout", 30))

    monkeypatch.setattr(sp, "run", hang)
    with pytest.raises(AdbError, match="timed out"):
        list_third_party_packages("SERIAL")


def test_package_list_parsing_tolerates_crlf(fake_adb):
    from frider.adb import apk_paths

    fake_adb["splits"] = ["/data/app/base.apk", "/data/app/split.apk"]
    assert apk_paths("SERIAL", "com.example") == ["/data/app/base.apk", "/data/app/split.apk"]


# ---- banner ----

def test_banner_art_is_intact():
    """The art is whitespace-significant: every line must keep its exact
    leading columns, so nothing may strip or reflow it."""
    from frider.ui import BANNER

    lines = BANNER.strip("\n").split("\n")
    assert len(lines) == 6
    assert lines[0].startswith(" ______")
    assert [line[0] for line in lines] == [" ", "|", "|", "|", "|", "\\"]
    assert "\\___||_|" in lines[5]


def test_help_renders_the_banner_unreflowed():
    """Regression: argparse's default formatter collapses whitespace, which
    turns the banner into a paragraph of punctuation."""
    import subprocess
    import sys

    from frider.ui import BANNER

    r = subprocess.run([sys.executable, "-m", "frider", "--help"],
                       capture_output=True, text=True)
    assert r.returncode == 0
    for line in BANNER.strip("\n").split("\n"):
        assert line in r.stdout, f"banner line lost or reflowed: {line!r}"


def test_banner_prints_on_stderr_and_never_on_stdout(flutter_apk):
    """The banner shows on every run, on stderr. stdout is the contract: a
    caller pipes --json into jq and a table into awk, and seven lines of ASCII
    art in front of either one breaks it."""
    import subprocess
    import sys

    for extra in ([], ["--json"]):
        r = subprocess.run(
            [sys.executable, "-m", "frider", str(flutter_apk), "--no-color"] + extra,
            capture_output=True, text=True,
        )
        assert r.returncode == 0
        assert "\\_|" not in r.stdout
        assert "_ __" not in r.stdout
        assert "\\_|" in r.stderr, "the banner should print on stderr"
    # ...and stdout is still valid JSON, banner or not.
    r = subprocess.run(
        [sys.executable, "-m", "frider", str(flutter_apk), "--json"],
        capture_output=True, text=True,
    )
    assert json.loads(r.stdout)["results"][0]["framework"] == "flutter"


# ---- --adb --list ----

@pytest.fixture
def fake_pm_list(monkeypatch):
    """Stub `pm list packages`, recording whether -3 was passed."""
    import subprocess as sp

    state = {"third_party": ["com.b.app", "com.a.app"],
             "system": ["android", "com.android.systemui"],
             "calls": []}

    def fake_run(cmd, **kw):
        state["calls"].append(cmd)
        names = list(state["third_party"])
        if "-3" not in cmd:
            names += state["system"]
        return sp.CompletedProcess(cmd, 0, "".join(f"package:{n}\r\n" for n in names), "")

    monkeypatch.setattr(sp, "run", fake_run)
    return state


def test_list_shows_third_party_packages_without_pulling(fake_pm_list, capsys):
    """Listing is the step before a scan: one adb call, no APK pulled. A pull
    here would cost gigabytes for a question the package list already answers."""
    assert main(["--adb", "--serial", "S", "--list", "--no-color"]) == 0
    out = capsys.readouterr().out
    assert "| package" in out
    assert "| com.a.app" in out
    assert "2 third-party package(s)" in out
    assert not any("pull" in c for c in fake_pm_list["calls"]), "--list must not pull"
    assert all("-3" in c for c in fake_pm_list["calls"])


def test_list_sorts_packages(fake_pm_list, capsys):
    """Device order is arbitrary; a listing you scan by eye must not be."""
    main(["--adb", "--serial", "S", "--list", "--no-color"])
    lines = [ln for ln in capsys.readouterr().out.splitlines() if ln.startswith("| com.")]
    assert lines == sorted(lines)


def test_list_all_includes_system_packages(fake_pm_list, capsys):
    """--list-all drops the -3 filter; without that it would silently return
    the same third-party set and look like the device had no system apps."""
    assert main(["--adb", "--serial", "S", "--list-all", "--no-color"]) == 0
    out = capsys.readouterr().out
    assert "| com.android.systemui" in out
    assert "4 package(s)" in out
    assert all("-3" not in c for c in fake_pm_list["calls"])


def test_list_json_uses_the_same_versioned_envelope(fake_pm_list, capsys):
    """A caller checks schema_version one way, whatever it asked for."""
    assert main(["--adb", "--serial", "S", "--list", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema_version"] == 1
    assert payload["tool"] == "frider"
    assert payload["packages"] == ["com.a.app", "com.b.app"]


def test_list_without_adb_is_a_usage_error(capsys):
    """--list reads a device; without --adb there is nothing to list, and
    silently listing nothing would look like an empty device."""
    assert main(["--list"]) == 2
    assert "--list needs --adb" in capsys.readouterr().err


def test_list_without_a_serial_is_a_usage_error(monkeypatch, capsys):
    monkeypatch.setattr(cli, "DEFAULT_ADB_SERIAL", "")
    assert main(["--adb", "--list"]) == 2
    assert "needs a serial" in capsys.readouterr().err


def test_list_says_it_ignored_package_names(fake_pm_list, capsys):
    """Same reasoning as --all: dropping them in silence would look like a
    listing filtered to exactly the names given."""
    main(["--adb", "--serial", "S", "--list", "com.example", "--no-color"])
    assert "ignoring the 1 name(s) given" in capsys.readouterr().err


def test_list_says_it_ignored_all(fake_pm_list, capsys):
    """`--list --all` asked for a full scan and gets a listing. Saying nothing
    would read as a scan that happened to print a package list."""
    assert main(["--adb", "--serial", "S", "--list", "--all", "--no-color"]) == 0
    err = capsys.readouterr().err
    assert "ignoring --all" in err
    assert not any("pull" in c for c in fake_pm_list["calls"])


def test_list_does_not_need_a_rules_file(fake_pm_list, capsys):
    """A listing classifies nothing, so a broken --rules file is no reason to
    refuse to say what is installed."""
    assert main(["--adb", "--serial", "S", "--list", "--rules",
                 "/nonexistent/rules.json", "--no-color"]) == 0
    assert "cannot load rules" not in capsys.readouterr().err


def test_list_packages_builds_the_right_adb_command(fake_pm_list):
    from frider.adb import list_packages

    list_packages("SERIAL")
    assert fake_pm_list["calls"][-1] == [
        "adb", "-s", "SERIAL", "shell", "pm", "list", "packages", "-3"]
    list_packages("SERIAL", include_system=True)
    assert fake_pm_list["calls"][-1] == [
        "adb", "-s", "SERIAL", "shell", "pm", "list", "packages"]


# The "F" of the wordmark, read off the art by eye. Written out rather than
# sliced with BANNER_SPLIT: deriving the expectation from the constant under
# test makes the assertion circular, and a wrong split column then passes.
F_GLYPH = [
    " ______",
    "|  ___|",
    "| |_   ",
    "|  _|  ",
    "| |    ",
    "\\_|    ",
]


def test_banner_is_red_f_and_blue_rider():
    """The art spells "Frider", so the wordmark takes two solid colours along
    the letter boundary — the red must cover the F exactly, not part of an
    adjacent glyph."""
    from frider.ui import BANNER, Palette, render_banner

    lines = render_banner(Palette(enabled=True)).split("\n")
    assert len(lines) == 6
    for line, plain, f_part in zip(lines, BANNER.strip("\n").split("\n"), F_GLYPH):
        assert line == f"\x1b[31m{f_part}\x1b[0m\x1b[34m{plain[len(f_part):]}\x1b[0m"


def test_banner_colour_is_dropped_when_asked():
    """--no-color reaches the banner too, not just the table."""
    from frider.ui import Palette, render_banner

    assert "\x1b[" not in render_banner(Palette(enabled=False))


def test_no_color_env_beats_a_tty(monkeypatch):
    """https://no-color.org: NO_COLOR wins over an interactive terminal. The
    banner is the loudest colour frider emits, and it honours it."""
    from frider import ui

    class Tty:
        def isatty(self):
            return True

    monkeypatch.setattr(ui, "_NO_COLOR_ENV", True)
    assert ui.Palette(stream=Tty()).enabled is False
    assert "\x1b[" not in ui.render_banner(ui.Palette(stream=Tty()))
    # ...and an explicit enabled=True is still an override, not a suggestion.
    assert ui.Palette(enabled=True, stream=Tty()).enabled is True


def test_banner_colour_follows_stderr_not_stdout():
    """The banner writes to stderr, so stderr decides. Colouring it by stdout
    would write escape codes into `2> log.txt`, and would drop colour from a
    terminal whenever stdout happened to be piped."""
    from frider.ui import Palette

    class Stream:
        def __init__(self, tty):
            self._tty = tty

        def isatty(self):
            return self._tty

    assert Palette(stream=Stream(True)).enabled is True
    assert Palette(stream=Stream(False)).enabled is False


def test_banner_colour_never_reaches_a_redirected_stderr(flutter_apk, tmp_path):
    """End to end: with stderr captured to a file, the art must arrive plain."""
    import subprocess
    import sys

    log = tmp_path / "err.log"
    with open(log, "w") as fh:
        subprocess.run([sys.executable, "-m", "frider", str(flutter_apk)],
                       stdout=subprocess.DEVNULL, stderr=fh)
    text = log.read_text()
    assert "_ __" in text, "the banner should still be there"
    assert "\x1b[" not in text, "a redirected stderr must not get escape codes"


def test_tagline_names_the_tool_and_the_running_version(flutter_apk):
    """Under the art: what this is, and which build produced the verdict —
    the first question about a surprising result is which frider ran. On
    stderr with the banner, so stdout stays parseable."""
    import subprocess
    import sys

    from frider import __version__
    from frider.ui import TAGLINE

    r = subprocess.run(
        [sys.executable, "-m", "frider", str(flutter_apk), "--no-color"],
        capture_output=True, text=True,
    )
    assert f"{TAGLINE} · v{__version__}" in r.stderr
    assert TAGLINE not in r.stdout


def test_readme_banner_matches_the_code():
    """The README copy and frider.ui.BANNER must not drift apart."""

    from frider.ui import BANNER

    readme = pathlib.Path(__file__).resolve().parent.parent / "README.md"
    assert BANNER.strip("\n") in readme.read_text(encoding="utf-8")


# ---- description consistency ----

DESCRIBED_ELSEWHERE = [
    "Flutter", "React Native", "Hermes", "JavaScriptCore",
    "MAUI", "Xamarin", "Cordova", "Capacitor", "Ionic", "Kony",
    "NativeScript", "Qt", "Titanium", "Unity",
]


def _all_descriptions():
    """The four places frider describes itself, which used to disagree."""

    import frider
    from frider.cli import build_parser

    root = pathlib.Path(__file__).resolve().parent.parent
    pyproject = root / "pyproject.toml"
    readme = root / "README.md"

    summary = re.search(r'^description = "(.*)"$',
                        pyproject.read_text(encoding="utf-8"), re.M).group(1)
    # README's opening paragraph, before the first '## ' heading
    intro = readme.read_text(encoding="utf-8").split("\n## ")[0]

    return {
        "pyproject.toml": summary,
        "frider/__init__.py": frider.__doc__,
        "frider --help": build_parser().description,
        "README.md": intro,
    }


@pytest.mark.parametrize("source", list(_all_descriptions()))
def test_every_description_names_every_framework(source):
    """Regression: the four descriptions drifted — --help omitted the Hermes vs
    JavaScriptCore split entirely, which is the distinction the tool exists to
    make, and one said 'Cordova' where the others said 'Apache Cordova'."""
    text = _all_descriptions()[source]
    missing = [t for t in DESCRIBED_ELSEWHERE if t.lower() not in text.lower()]
    assert not missing, f"{source} does not mention: {', '.join(missing)}"


def test_descriptions_agree_on_apache_cordova():
    for source, text in _all_descriptions().items():
        assert "Apache Cordova" in text or "Apache\nCordova" in text, source


def test_multiline_error_cannot_break_the_table():
    """Regression: adb surfaces multi-line stderr in its error messages, and a
    newline inside a cell tore the table into ragged rows."""
    from frider.report import render_table
    from frider.rules import Result
    from frider.ui import Palette

    r = Result(source="com.demo.rn", verdict="ERROR", confidence="-")
    r.errors.append("command failed: adb -s X pull /data/app/base.apk\n"
                    "error: device offline\nmore detail")
    out = render_table([r], palette=Palette(enabled=False))
    assert len({len(line) for line in out.splitlines()}) == 1, "ragged table"
    assert "device offline" in out


def test_json_keeps_the_full_multiline_message():
    """Only the table collapses whitespace; --json stays verbatim."""
    import json

    from frider.report import render_json
    from frider.rules import Result

    r = Result(source="com.demo.rn", verdict="ERROR", confidence="-")
    r.errors.append("line one\nline two")
    payload = json.loads(render_json([r]))
    assert payload["results"][0]["errors"] == ["line one\nline two"]


def test_adb_error_has_no_trailing_newline_when_stderr_is_empty(monkeypatch):
    import subprocess as sp

    from frider.adb import AdbError, apk_paths

    monkeypatch.setattr(sp, "run", lambda cmd, **kw: sp.CompletedProcess(cmd, 1, "", ""))
    with pytest.raises(AdbError) as exc:
        apk_paths("SERIAL", "com.example")
    assert str(exc.value) == str(exc.value).strip()
    assert "\n" not in str(exc.value)


def test_version_is_declared_in_exactly_one_place():
    """Regression: the version lived in both pyproject.toml and __init__.py.
    Once they drifted, `frider --version` would disagree with the installed
    wheel. pyproject now reads it from the package."""

    import frider

    pyproject = (pathlib.Path(__file__).resolve().parent.parent
                 / "pyproject.toml").read_text(encoding="utf-8")
    assert 'dynamic = ["version"]' in pyproject
    assert not re.search(r'^version = "', pyproject, re.M), \
        "pyproject hardcodes a version again"
    assert re.fullmatch(r"\d+\.\d+\.\d+", frider.__version__)


# ---- machine contract: schema envelope and framework ids ----

def test_json_envelope_carries_a_schema_version():
    """The envelope is the contract: a caller can refuse input it does not
    understand instead of silently misreading a changed field."""
    import json

    import frider
    from frider.report import SCHEMA_VERSION, render_json
    from frider.rules import Result

    payload = json.loads(render_json([Result(source="a", verdict="X", confidence="High")]))
    assert payload["schema_version"] == SCHEMA_VERSION
    assert payload["tool"] == "frider"
    assert payload["tool_version"] == frider.__version__
    assert isinstance(payload["results"], list)


@pytest.mark.parametrize("members,framework,frameworks", [
    ({"lib/arm64-v8a/libflutter.so": b"e"}, "flutter", ["flutter"]),
    ({"lib/arm64-v8a/libflutter.so": b"e",
      "assets/flutter_assets/x.json": b"{}"}, "flutter", ["flutter"]),
    ({"assets/index.android.bundle": b"j",
      "lib/arm64-v8a/libhermes.so": b"h"}, "react-native", ["react-native"]),
    ({"lib/arm64-v8a/libunity.so": b"u"}, "unity", ["unity"]),
    ({"classes.dex": b"d"}, "native", []),
    ({"lib/arm64-v8a/libflutter.so": b"e",
      "assets/index.android.bundle": b"j",
      "lib/arm64-v8a/libhermes.so": b"h"},
     "hybrid", ["flutter", "react-native"]),
])
def test_framework_id_is_stable_and_machine_readable(tmp_path, members, framework, frameworks):
    """Callers must branch on an id, not regex the prose verdict."""
    r = classify(str(make_apk(tmp_path / "a.apk", members)))
    assert r.framework == framework
    assert r.frameworks == frameworks


def test_error_results_are_not_reported_as_native(tmp_path):
    """Regression: Result defaults framework to 'native', so an unreadable
    source would have claimed to be an app with no framework markers."""
    import json
    import subprocess
    import sys

    r = subprocess.run(
        [sys.executable, "-m", "frider", "--json", str(tmp_path / "missing.apk")],
        capture_output=True, text=True,
    )
    assert r.returncode == 1
    entry = json.loads(r.stdout)["results"][0]
    assert entry["framework"] == "error"
    assert entry["verdict"] == "ERROR"


# ---- confidence means "how sure", not "which answer" ----

def test_native_over_a_complete_apk_is_high_confidence(tmp_path):
    """Regression: every native verdict read Low, so the most common result in
    any real scan looked like the least trustworthy one."""
    apk = make_apk(tmp_path / "native.apk", {
        "AndroidManifest.xml": b"<m/>",
        "classes.dex": b"d",
        "resources.arsc": b"a",
    })
    r = classify(str(apk))
    assert r.verdict == "Native (no framework markers)"
    assert r.confidence == "High"


def test_low_confidence_means_we_could_not_tell(tmp_path):
    """A fragment with no manifest or dex is not evidence of a native app."""
    apk = make_apk(tmp_path / "fragment.apk", {"res/drawable/icon.png": b"x"})
    r = classify(str(apk))
    assert r.verdict == "Native (no framework markers)"
    assert r.confidence == "Low"


def test_resource_only_split_alone_is_low_confidence(tmp_path):
    """A split with a manifest but no code cannot settle the question."""
    apk = make_apk(tmp_path / "split_config.xxhdpi.apk", {
        "AndroidManifest.xml": b"<m/>",
        "res/drawable-xxhdpi/i.png": b"x",
    })
    assert classify(str(apk)).confidence == "Low"


def test_framework_confidence_still_counts_only_the_winner(tmp_path):
    apk = make_apk(tmp_path / "mixed.apk", {
        "AndroidManifest.xml": b"<m/>", "classes.dex": b"d",
        "lib/arm64-v8a/libkony.so": b"k",
        "assets/www/index.html": b"<html/>",
    })
    r = classify(str(apk))
    assert r.framework == "kony"
    assert r.confidence == "Medium"


# ---- nested containers must not be buffered in memory ----

def test_spool_member_streams_to_a_real_file(tmp_path):
    """Deterministic half of the memory fix: the nested archive is backed by a
    real file, not an in-memory buffer. fileno() raises on BytesIO."""
    from frider.apk import _spool_member

    payload = b"nested-apk-bytes" * 1024
    outer = tmp_path / "c.xapk"
    with zipfile.ZipFile(outer, "w") as z:
        z.writestr("inner.apk", payload)

    with zipfile.ZipFile(outer) as z:
        spooled = _spool_member(z, "inner.apk")
    assert spooled.fileno() > 0, "nested member is buffered in memory"
    assert spooled.read() == payload
    spooled.close()


def test_nested_container_spools_every_member_instead_of_buffering(tmp_path, monkeypatch):
    """Regression: each nested split was read whole into BytesIO just to list
    entry names, so a 180 MiB XAPK cost 122 MiB resident.

    Asserted structurally rather than by measuring RSS: ru_maxrss is a
    lifetime peak whose value depends on how the process was spawned, so an
    RSS threshold here passes even against the buffering implementation.
    """
    import frider.apk as apk

    container = tmp_path / "big.xapk"
    with zipfile.ZipFile(container, "w") as z:
        for name in ("base.apk", "split_a.apk"):
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w") as inner:
                inner.writestr("lib/arm64-v8a/libflutter.so", b"engine")
            z.writestr(name, buf.getvalue())
        z.writestr("manifest.json", b"{}")

    spooled = []
    real = apk._spool_member

    def tracking(zf, name):
        spooled.append(name)
        return real(zf, name)

    monkeypatch.setattr(apk, "_spool_member", tracking)
    entries = apk.entries_for(str(container))

    assert spooled == ["base.apk", "split_a.apk"], \
        "a nested member bypassed the spool and was buffered in memory"
    assert any(e.path.endswith("!lib/arm64-v8a/libflutter.so") for e in entries)
    assert classify_entries(entries, RULES).framework == "flutter"


# ---- newer framework fingerprints ----

@pytest.mark.parametrize("name,extra,framework", [
    ("maui", {"assemblies/Microsoft.Maui.Controls.dll": b"d",
              "assemblies/Microsoft.Maui.dll": b"d",
              "lib/arm64-v8a/libmonodroid.so": b"m"}, "maui"),
    ("xamarin-forms", {"assemblies/Xamarin.Forms.Core.dll": b"d",
                       "assemblies/mscorlib.dll": b"d",
                       "lib/arm64-v8a/libmonodroid.so": b"m"}, "xamarin"),
    ("nativescript", {"lib/arm64-v8a/libNativeScript.so": b"n",
                      "assets/metadata/treeNodeStream.dat": b"m"}, "nativescript"),
    ("qt", {"lib/arm64-v8a/libQt6Core_arm64-v8a.so": b"q",
            "lib/arm64-v8a/libplugins_platforms_qtforandroid_arm64-v8a.so": b"q"}, "qt"),
    ("titanium", {"lib/arm64-v8a/libtitanium.so": b"t",
                  "assets/Resources/app.js": b"j"}, "titanium"),
])
def test_newer_frameworks_are_identified(tmp_path, name, extra, framework):
    base = {"AndroidManifest.xml": b"<m/>", "classes.dex": b"d"}
    r = classify(str(make_apk(tmp_path / f"{name}.apk", {**base, **extra})))
    assert r.framework == framework


def test_maui_outranks_xamarin_when_both_match(tmp_path):
    """A MAUI app also ships libmonodroid.so, so both rules fire. The more
    specific one has to win, or MAUI would never be reported."""
    r = classify(str(make_apk(tmp_path / "maui.apk", {
        "AndroidManifest.xml": b"<m/>", "classes.dex": b"d",
        "assemblies/Microsoft.Maui.dll": b"d",
        "lib/arm64-v8a/libmonodroid.so": b"m",
    })))
    assert r.framework == "maui"
    assert "xamarin" in r.markers, "the xamarin evidence should still be recorded"


def test_assembly_store_build_reports_dotnet_not_a_guess(tmp_path):
    """Release .NET builds pack assemblies into a blob, so the DLL names are
    not visible as entries. Reporting xamarin is correct; guessing maui is not."""
    r = classify(str(make_apk(tmp_path / "blob.apk", {
        "AndroidManifest.xml": b"<m/>", "classes.dex": b"d",
        "assemblies/assemblies.blob": b"b",
        "assemblies/assemblies.manifest": b"m",
        "lib/arm64-v8a/libmonodroid.so": b"m",
        "lib/arm64-v8a/libmono-android.release.so": b"r",
    })))
    assert r.framework == "xamarin"
    assert r.confidence == "High"


def test_plain_kotlin_app_is_not_mistaken_for_a_cross_platform_framework(tmp_path):
    """Kotlin/Compose Multiplatform deliberately have no rules — they compile to
    ordinary Android code, so any marker broad enough to catch them would fire
    on plain Kotlin apps like this one."""
    r = classify(str(make_apk(tmp_path / "kotlin.apk", {
        "AndroidManifest.xml": b"<m/>", "classes.dex": b"d",
        "META-INF/app_release.kotlin_module": b"k",
        "META-INF/androidx.compose.ui_ui.version": b"1",
    })))
    assert r.framework == "native"
    assert r.kotlin is True


# ---- marker matching is anchored and boundary-aware ----

def test_bang_in_an_entry_name_does_not_truncate_the_evidence(tmp_path):
    """Regression: '!' marks a container boundary in the display path but is a
    legal zip entry-name character, so splitting on it truncated real names —
    mis-citing the evidence and matching markers that were never there."""
    apk = make_apk(tmp_path / "bang.apk", {
        "AndroidManifest.xml": b"<m/>", "classes.dex": b"d",
        "assets/we!rd/lib/arm64-v8a/libflutter.so": b"e",
    })
    entries = entries_for(str(apk))
    target = next(e for e in entries if "we!rd" in e.path)
    assert target.match_path() == "assets/we!rd/lib/arm64-v8a/libflutter.so", \
        "the boundary was parsed back out of a path that legitimately contains '!'"


def test_container_boundary_still_yields_the_inner_path(tmp_path):
    """The nested case must keep working: inner paths drive matching, so an
    anchored marker fires on an APK inside an XAPK."""
    inner = io.BytesIO()
    with zipfile.ZipFile(inner, "w") as z:
        z.writestr("AndroidManifest.xml", b"<m/>")
        z.writestr("classes.dex", b"d")
        z.writestr("lib/arm64-v8a/libflutter.so", b"e")
    apk = make_apk(tmp_path / "c.xapk", {"app.apk": inner.getvalue()})

    entries = entries_for(str(apk))
    nested = next(e for e in entries if e.path.endswith("!lib/arm64-v8a/libflutter.so"))
    assert nested.match_path() == "lib/arm64-v8a/libflutter.so"
    assert classify_entries(entries, RULES).framework == "flutter"


@pytest.mark.parametrize("entry", [
    "assets/backup/lib/arm64-v8a/libflutter.so",     # a bundled copy, never loaded
    "assets/apks/lib/arm64-v8a/libflutter.so.bak",   # renamed
    "assets/bundle!lib/arm64-v8a/libflutter.so.txt",  # renamed, and bang-bearing
    "META-INF/lib/arm64-v8a/libflutter.so",          # not where Android looks
])
def test_a_library_path_that_is_not_at_the_apk_root_is_not_a_marker(tmp_path, entry):
    """Regression: markers were unanchored substring searches, so any nested or
    renamed copy of a library name matched. Android only loads lib/<abi>/*.so at
    the archive root; anything else is a payload, not a framework."""
    apk = make_apk(tmp_path / "bundled.apk", {
        "AndroidManifest.xml": b"<m/>", "classes.dex": b"d", "resources.arsc": b"a",
        entry: b"not a loaded library",
    })
    r = classify(str(apk))
    assert r.framework == "native", f"{entry} was treated as a Flutter marker"
    assert r.markers == {}


def test_every_marker_is_anchored():
    """A future unanchored marker reopens the whole class of bug."""
    from frider.rules import iter_patterns

    unanchored = [p for p in iter_patterns(RULES) if not p.startswith("^")]
    assert not unanchored, f"unanchored markers: {unanchored}"


def test_rn_bundle_without_an_engine_is_not_react_native(tmp_path):
    """Regression: an `assets/index.android.bundle` that is shipped but never
    executed must not claim React Native. A real RN app loads the bundle with
    libhermes/libjsc/libreactnative; a bundle with none of those is a bundled
    asset (dead copy, leftover, or payload), not a framework. Found on a real
    Flutter banking app that shipped a vestigial RN bundle."""
    apk = make_apk(tmp_path / "bundle-only.apk", {
        "AndroidManifest.xml": b"<m/>", "classes.dex": b"d", "resources.arsc": b"a",
        "assets/index.android.bundle": b"not executed",
    })
    r = classify(str(apk))
    assert r.framework == "native", "bundle alone was treated as React Native"
    assert r.markers == {}


def test_flutter_assets_without_an_engine_is_not_flutter(tmp_path):
    """Regression: flutter_assets/ alone must not claim Flutter. The engine
    (libflutter.so/libapp.so) is what actually runs a Flutter app; a stray
    assets dir is a payload."""
    apk = make_apk(tmp_path / "assets-only.apk", {
        "AndroidManifest.xml": b"<m/>", "classes.dex": b"d", "resources.arsc": b"a",
        "assets/flutter_assets/AssetManifest.json": b"{}",
    })
    r = classify(str(apk))
    assert r.framework == "native", "flutter_assets alone was treated as Flutter"
    assert r.markers == {}


def test_rn_bundle_plus_engine_still_detected(tmp_path):
    """The legit path must keep working: bundle + hermes engine is RN."""
    apk = make_apk(tmp_path / "rn-ok.apk", {
        "AndroidManifest.xml": b"<m/>", "classes.dex": b"d", "resources.arsc": b"a",
        "assets/index.android.bundle": b"js",
        "lib/arm64-v8a/libhermes.so": b"h",
    })
    r = classify(str(apk))
    assert r.framework == "react-native"
    assert "hermes" in r.engines


# ---- Lynx (ByteDance) ----

def test_lynx_runtime_is_detected(tmp_path):
    """Lynx ships its own runtime (liblynx.so / liblynxbase.so) and renders
    ``template.js`` bundles produced by its toolchain — a cross-platform UI
    framework in the same class as React Native, and previously reported as
    native because no rule existed."""
    apk = make_apk(tmp_path / "lynx.apk", {
        "AndroidManifest.xml": b"<m/>", "classes.dex": b"d", "resources.arsc": b"a",
        "lib/arm64-v8a/liblynx.so": b"engine",
        "lib/arm64-v8a/liblynxbase.so": b"base",
        "assets/lynx_core.js": b"js",
    })
    r = classify(str(apk))
    assert r.framework == "lynx"
    assert r.verdict == "Lynx (ByteDance)"


def test_lynx_core_asset_without_the_runtime_is_not_lynx(tmp_path):
    """``assets/lynx_core.js`` is a payload: Android loads nothing from
    assets/, so without liblynx.so there is no engine to run it. Same rule as
    the React Native bundle and flutter_assets cases."""
    apk = make_apk(tmp_path / "lynx-asset-only.apk", {
        "AndroidManifest.xml": b"<m/>", "classes.dex": b"d", "resources.arsc": b"a",
        "assets/lynx_core.js": b"not executed",
    })
    r = classify(str(apk))
    assert r.framework == "native", "lynx_core.js alone was treated as Lynx"
    assert r.markers == {}


# ---- Entry.match_path() carries the inner path; it is required, not derived ----

def test_entry_without_inner_fails_loudly():
    """Regression: match_path() used to fall back to innermost(path) when
    inner was missing, and innermost() splits on '!' — legal in zip entry
    names — so a directly-constructed Entry could silently truncate a path
    like assets/we!rd/lib/... and match markers that were never there. The
    inner path is now required: a construction that omits it must fail at
    construction time, not misclassify at match time."""
    from frider.apk import Entry

    with pytest.raises(TypeError):
        Entry("assets/we!rd/lib/arm64-v8a/libflutter.so", False, None)


def test_match_path_returns_the_carried_inner_path_not_the_display_path():
    """The match path is whatever was set at construction — the display path's
    '!' container boundary is never parsed back out, even when the path really
    contains '!' as a legal character."""
    from frider.apk import Entry

    e = Entry("assets/we!rd/lib/arm64-v8a/libflutter.so", False, None,
              inner="assets/we!rd/lib/arm64-v8a/libflutter.so")
    assert e.match_path() == "assets/we!rd/lib/arm64-v8a/libflutter.so"

    container = Entry("bundle.xapk!app.apk!lib/arm64-v8a/libflutter.so", False, None,
                      inner="lib/arm64-v8a/libflutter.so")
    assert container.match_path() == "lib/arm64-v8a/libflutter.so"
    assert container.path == "bundle.xapk!app.apk!lib/arm64-v8a/libflutter.so"
# ---- adb package names are a path, and therefore a trust boundary ----

@pytest.mark.parametrize("hostile", [
    "../victim",
    "../../etc",
    "/etc/frider",
    "com.example/../../..",
    "a\nb",
    "",
    ".hidden",
])
def test_an_implausible_package_name_is_refused(hostile):
    """Regression: the package name becomes a cache directory that is deleted
    before each pull, so a device reporting '../victim' rmtree'd a path outside
    the cache — and an absolute name discarded the cache root entirely, because
    os.path.join('/cache', '/etc/x') is '/etc/x'."""
    from frider.adb import AdbError, check_package_name

    with pytest.raises(AdbError, match="implausible package name"):
        check_package_name(hostile)


@pytest.mark.parametrize("legal", [
    "com.example.app",
    "com.example.app_2",
    "a.b",
    "com.example.app.free.v2",
])
def test_real_package_names_are_accepted(legal):
    from frider.adb import check_package_name

    assert check_package_name(legal) == legal


def test_a_hostile_package_name_cannot_delete_outside_the_cache(tmp_path, monkeypatch):
    """End to end: the pull refuses before rmtree runs."""
    import subprocess as sp

    from frider.adb import AdbError, pull_package

    victim = tmp_path / "victim"
    victim.mkdir()
    keep = victim / "keepme.txt"
    keep.write_text("important", encoding="utf-8")
    cache = tmp_path / "cache"
    cache.mkdir()

    def fake_run(cmd, **kw):
        return sp.CompletedProcess(cmd, 0, "package:/data/app/base.apk\n", "")

    monkeypatch.setattr(sp, "run", fake_run)
    with pytest.raises(AdbError):
        pull_package("SERIAL", "../victim", str(cache))

    assert keep.exists(), "the pull deleted a directory outside the cache"
    assert keep.read_text(encoding="utf-8") == "important"


# ---- table alignment counts terminal columns, not characters ----

def test_wide_characters_do_not_break_alignment():
    """Regression: widths were computed with len(), but a terminal draws CJK
    double-width — so a table of CJK app names came out ragged on screen even
    though every row had an equal character count."""
    import unicodedata

    from frider.report import render_table
    from frider.rules import Result
    from frider.ui import Palette

    def columns(s):
        return sum(0 if unicodedata.combining(c)
                   else (2 if unicodedata.east_asian_width(c) in ("W", "F") else 1)
                   for c in s)

    results = [
        Result(source="中文アプリ.apk", verdict="Flutter / Dart", confidence="High"),
        Result(source="plain.apk", verdict="Unity", confidence="High"),
    ]
    for palette in (Palette(enabled=False), Palette(enabled=True)):
        out = render_table(results, palette=palette)
        visible = [re.sub(r"\x1b\[[0-9;]*m", "", ln) for ln in out.splitlines()]
        assert len({columns(v) for v in visible}) == 1, (
            f"ragged in terminal columns (colors={palette.enabled}): "
            f"{[columns(v) for v in visible]}"
        )


def test_display_width_counts_columns():
    from frider.ui import display_width

    assert display_width("abc") == 3
    assert display_width("中文") == 4
    assert display_width("é") == 1, "a combining accent takes no column"

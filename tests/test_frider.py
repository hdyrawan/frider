"""frider tests — build tiny fixture APK zips in tmp and assert classifications."""

import io
import os
import re
import zipfile

import pytest

from frider.apk import entries_for, innermost
from frider.rules import classify_entries, load_rules
from frider.cli import build_parser

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

    bad = subprocess.run([sys.executable, "-m", "frider", str(tmp_path / "missing.apk"), "--no-color"],
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

    local = b"PK\x03\x04" + struct.pack("<HHHHH", 20, 0, 0, 0, 0) + b"a.txt" + b"\x00" * 16 + b"hello"
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

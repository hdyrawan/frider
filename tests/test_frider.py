"""frider tests — build tiny fixture APK zips in tmp and assert classifications."""

import io
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

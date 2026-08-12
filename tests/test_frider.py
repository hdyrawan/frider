"""frider tests — build tiny fixture APK zips in tmp and assert classifications."""

import io
import zipfile

import pytest

from frider.apk import entries_for, innermost
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


def test_hybrid(hybrid_apk):
    r = classify(str(hybrid_apk))
    assert r.verdict == "Hybrid (Flutter + React Native)"


def test_cordova(cordova_apk):
    r = classify(str(cordova_apk))
    assert "Cordova" in r.verdict


def test_xapk_container_sees_inner_apk(xapk_container):
    r = classify(str(xapk_container))
    assert r.verdict == "Flutter / Dart"


def test_innermost_path_helper():
    assert innermost("app.apk!lib/arm64-v8a/libflutter.so") == "lib/arm64-v8a/libflutter.so"
    assert innermost("lib/arm64-v8a/libflutter.so") == "lib/arm64-v8a/libflutter.so"


def test_directory_mode(tmp_path):
    make_apk(tmp_path / "a.apk", {"lib/arm64-v8a/libflutter.so": b"e"})
    make_apk(tmp_path / "b.apk", {"classes.dex": b"d"})
    results = [classify(str(tmp_path / n)) for n in ("a.apk", "b.apk")]
    assert results[0].verdict == "Flutter / Dart"
    assert results[1].verdict == "Native (no framework markers)"

# frider

Android app **fr**amework **ider** — detect the UI framework of an Android app
from its APK contents: **Flutter / Dart**, **React Native** (with the **Hermes vs
JavaScriptCore** engine split most detectors miss), **Apache Cordova**, **Ionic**,
**Capacitor**, **Kony (Temenos)**, **Xamarin / .NET**, **Unity**, or **native
Java/Kotlin**. Zero runtime dependencies — pure Python standard library.

Fingerprints are **data, not code**: rules live in `frider/rules.json`, so
anyone can add a detector without touching Python.

## Why this exists

Framework knowledge decides which toolchain applies to an app (Dart cert-verify
hooks vs Hermes JS surface vs a native host). Naive detectors — including the
`android-framework-detector` project this is modelled on — classify anything
with `libreactnative*` as "React Native" and stop there. That is wrong half the
time in practice: **JavaScriptCore and Hermes have different runtime surfaces**,
and apps built on Cordova or Kony look like "native" to a Flutter/RN-only scan
(three real apps were mislabelled that way the first time this tool ran).

`frider` therefore reports:

- the framework verdict,
- the **React Native JS engine** (`hermes` vs `jsc`),
- Kotlin metadata presence,
- embedded JS runtimes that are *not* the framework (Duktape, J2V8),
- notable third-party native libs (RootBeer, AppGuard, RiskStub, PairIP,
  EverSafe, DataVisor, Vkey) as an informational side channel.

## Install

```bash
pip install .            # or: pipx install . / uv tool install .
frider --version
```

No dependencies beyond the Python standard library. Requires Python 3.9+.

## Usage

```bash
# a single APK
frider app.apk

# a directory / split-APK pull (every apk_*.apk is scanned as one set)
frider pulled-apks/

# an XAPK/APKS container (nested APKs are surfaced automatically)
frider app.xapk

# machine-readable
frider app.apk --json

# custom rules
frider --rules /path/to/rules.json app.apk
```

### adb mode — classify installed packages

```bash
# classify specific installed packages (pulls via `pm path`, needs adb + device)
frider --adb <serial> com.example.app com.example.other

# every third-party package on the device
frider --adb <serial> --all

# serial from the environment
export ANDROID_PROBE_SERIAL=<serial>
frider --adb com.example.app
```

Pulled APKs are cached under `--cache-dir` (default: a temp dir) so a second run
over the same packages does not re-pull.

### Example output

```
+----------------------+--------------------------+------------+-----------------------------+-------------------------------+
| source               | verdict                  | confidence | markers                     | notes                         |
+----------------------+--------------------------+------------+-----------------------------+-------------------------------+
| app.apk              | Flutter / Dart           | High       | flutter:libflutter.so,...   |                               |
| rn.apk               | React Native (hermes)    | High       | react-native:libhermes.so   | engine=hermes                 |
| rn-jsc.apk           | React Native (jsc)       | High       | react-native:libjsc.so      | engine=jsc                    |
| web.apk              | Apache Cordova           | High       | cordova:assets/www/index... |                               |
| kony.apk             | Kony (Temenos)           | Medium     | kony:libkonyjsvm.so         | libs=RootBeer (root checker)  |
+----------------------+--------------------------+------------+-----------------------------+-------------------------------+
```

## Rules format

`frider/rules.json` is the whole detection surface:

```json
{
  "kotlin": { "marker": "META-INF/.*\\.kotlin_module" },
  "frameworks": [
    {
      "id": "react-native",
      "name": "React Native",
      "weight": 100,
      "markers": ["assets/index\\.android\\.bundle", "lib/[^/]+/libreactnative[^/]*\\.so"],
      "engines": {
        "hermes": "lib/[^/]+/libhermes[^/]*\\.so",
        "jsc": "lib/[^/]+/libjsc\\.so|lib/[^/]+/libjscexecutor\\.so"
      }
    }
  ],
  "embedded_js": [ { "id": "duktape", "name": "Duktape (embedded JS)", "marker": "lib/[^/]+/libduktape\\.so" } ],
  "notable_libs": [ { "regex": "lib/[^/]+/libtoolChecker\\.so", "label": "RootBeer (root checker)" } ]
}
```

Markers are regular expressions matched (case-insensitive) against every APK
entry path; the innermost path is used, so `container.xapk!app.apk!lib/...`
matches the same rules as a flat APK. A framework wins by marker presence;
ties break on `weight`, then on the number of distinct markers matched. An app
with both Flutter and React Native markers is reported as hybrid.

## Development

```bash
python3 -m pytest tests/ -q     # 9 fixture-based tests
```

## Roadmap

- [ ] full-corpus re-validation against real APK sets (the pass that first
      caught the Cordova/Kony blind spot)
- [ ] framework **version** extraction (Flutter engine, Hermes, RN) — deliberately
      not in v1: it needs per-framework verification before shipping numbers
- [ ] optional YARA-rule backend (`yara-python`) so rules can be shared as `.yar`
      with the rest of the ecosystem
- [ ] protector/RASP vendor scoring as a first-class output

## License

MIT — see [LICENSE](LICENSE).

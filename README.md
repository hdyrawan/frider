# frider

```
 ______        _      _
|  ___|      (_)    | |
| |_    _ __  _   __| |  ___  _ __
|  _|  | '__|| | / _` | / _ \| '__|
| |    | |   | || (_| ||  __/| |
\_|    |_|   |_| \__,_| \___||_|
```

[![tests](https://github.com/hdyrawan/frider/actions/workflows/test.yml/badge.svg)](https://github.com/hdyrawan/frider/actions/workflows/test.yml)
[![python](https://img.shields.io/badge/python-3.9%2B-blue)](https://pypi.org/project/frider/)
[![license](https://img.shields.io/badge/license-MIT-green)](LICENSE)

Android app **fr**amework **ider** — classifies the UI framework of an Android
app from its APK entry names: **Flutter / Dart**, **React Native** (reporting the
**Hermes vs JavaScriptCore** engine split most detectors collapse), **.NET
MAUI**, **Xamarin**, **Apache Cordova**, **Capacitor**, **Ionic**, **Kony
(Temenos)**, **NativeScript**, **Qt**, **Titanium**, **Unity**, or **native
Java/Kotlin**. Zero runtime dependencies — pure Python
standard library.

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

**Requirements:** Python **3.9+** (`python3 --version` to check) and nothing else —
frider has **zero runtime dependencies**, so installs are instant and there is no
dependency hell. It runs on Linux, macOS and Windows.

### Option 1 — pipx (recommended, isolated CLI install)

[pipx](https://pipx.pypa.io/) installs the command into its own environment so it
never touches your other Python packages:

```bash
pipx install git+https://github.com/hdyrawan/frider.git
frider --version
```

### Option 2 — uv tool

```bash
uv tool install git+https://github.com/hdyrawan/frider.git
frider --version
```

### Option 3 — plain pip

Prefer a virtual environment so the `frider` script lands on your PATH:

```bash
python3 -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install git+https://github.com/hdyrawan/frider.git
frider --version
```

Or, from a clone of this repo:

```bash
git clone https://github.com/hdyrawan/frider.git && cd frider
pip install .
frider --version
```

### Option 4 — run without installing

From a clone you can also run it directly, no install step at all:

```bash
git clone https://github.com/hdyrawan/frider.git && cd frider
python3 -m frider app.apk
```

### For development

```bash
git clone https://github.com/hdyrawan/frider.git && cd frider
python3 -m venv .venv && source .venv/bin/activate
pip install -e .           # editable: code changes apply immediately
python3 -m pytest tests/   # run the test suite
```

### Verify & uninstall

```bash
frider --version        # e.g. "frider 0.2.0"
frider --help           # full usage
pipx uninstall frider   # or: uv tool uninstall frider / pip uninstall frider
```

> adb mode (`--adb`) additionally needs the Android `adb` binary on your `PATH`
> and a reachable device — the APK-file modes need nothing but Python.

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
frider --adb --serial <serial> com.example.app com.example.other

# serial from the environment
export ANDROID_PROBE_SERIAL=<serial>
frider --adb com.example.app

# every third-party package on the device
frider --adb --all
```

Pulled APKs are cached under `~/.cache/frider/` (or `$XDG_CACHE_HOME/frider`),
so a second run over the same packages does not re-pull. Pass `--cache-dir DIR`
to point elsewhere or `--no-cache` for a throwaway pull.

### Example output

```
+----------------------+--------------------------+------------+---------------------------------------------+-------------------------------+
| source               | verdict                  | confidence | markers                                     | notes                         |
+----------------------+--------------------------+------------+---------------------------------------------+-------------------------------+
| app.apk              | Flutter / Dart           | High       | flutter:lib/arm64-v8a/libflutter.so (+7)     |                               |
| rn.apk               | React Native (hermes)    | High       | react-native:lib/arm64-v8a/libhermes.so      | engine=hermes                 |
| rn-jsc.apk           | React Native (jsc)       | High       | react-native:lib/arm64-v8a/libjsc.so (+1)    | engine=jsc                    |
| web.apk              | Apache Cordova           | High       | cordova:assets/www/index.html (+2)           |                               |
| kony.apk             | Kony (Temenos)           | Medium     | kony:lib/arm64-v8a/libkonyjsvm.so            | libs=RootBeer (root checker)  |
+----------------------+--------------------------+------------+---------------------------------------------+-------------------------------+
2 source(s): 1 flutter / dart, 1 react native
```

The **markers** column shows the actual APK entries that matched (up to 8 per
framework, with a `(+N)` overflow count) — not the rule regexes. Colors are
enabled automatically when stdout is a TTY; disable with `--no-color` or the
`NO_COLOR` env var. A one-line tally follows the table.

### Confidence

Confidence describes how sure frider is of **the verdict it reported** — never
which answer it happened to reach.

| | meaning |
|---|---|
| `High` | two or more markers for the winning framework — or, for a native verdict, a complete APK (manifest **and** dex) in which no marker appeared at all |
| `Medium` | exactly one marker for the winning framework |
| `Low` | **could not tell.** The input was too thin to settle the question — a fragment, or a resource-only split with no code in it |

`Low` never means "the answer was native". Absence of every marker across a
package that frider fully read is real evidence, and reports `High`.

### Known limits

Classification reads entry **names** only, never file contents, which bounds
what can be distinguished:

- **.NET MAUI vs plain .NET Android.** MAUI is named only when its assemblies
  ship as individual `.dll` entries. Release builds default to
  `AndroidUseAssemblyStore`, which packs them into `assemblies/*.blob` — the
  names are inside the blob, so those apps report `xamarin` (accurate: they
  *are* .NET) rather than `maui`.
- **Kotlin Multiplatform and Compose Multiplatform are not detected**, and
  deliberately have no rules. They compile to ordinary Android code with no
  distinguishing entry names; any marker specific enough to be safe would miss
  most builds, and anything broader would fire on plain Kotlin apps. Adding a
  guess here would be worse than reporting `native`.

### JSON output

`--json` emits a versioned envelope. Branch on **`framework`**, which is a
stable id (`flutter`, `react-native`, `maui`, `xamarin`, `cordova`, `capacitor`,
`ionic`, `kony`, `nativescript`, `qt`, `titanium`, `unity`, plus `native`,
`hybrid` and `error`). `verdict` is prose for humans and may be reworded between
releases; `matched_files` names the real APK entries behind the call, so a
verdict can be audited rather than trusted.

```json
{
  "schema_version": 1,
  "tool": "frider",
  "tool_version": "0.2.0",
  "results": [
    {
      "source": "rn.apk",
      "verdict": "React Native (hermes)",
      "framework": "react-native",
      "frameworks": ["react-native"],
      "confidence": "High",
      "engines": ["hermes"],
      "kotlin": false,
      "embedded_js": [],
      "notable_libs": [],
      "matched_files": { "react-native": ["assets/index.android.bundle"] },
      "errors": []
    }
  ]
}
```

`schema_version` is bumped whenever a field changes meaning or is removed, so a
caller can refuse input it does not understand instead of misreading it.

### Exit codes

`0` — everything classified · `1` — at least one source errored (missing file,
unreadable APK, adb pull failure, package not installed) · `2` — usage error
(e.g. `--adb` without a serial and no `ANDROID_PROBE_SERIAL`).

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
ties break on `weight`, then on the number of distinct entries matched. An app
with both Flutter and React Native markers is reported as hybrid.

## Measuring accuracy against real APKs

Every fixture in `tests/` is a synthetic zip built from the same assumptions
the rules were written from, so the suite proves the **matcher** works — not
that the **fingerprints are right**. Only real APKs answer that, and the answer
is a number.

Label a corpus by dropping each APK into a directory named after its expected
`framework` id:

```
corpus/
  flutter/        com.example.a.apk  com.example.b.xapk
  react-native/   ...
  maui/           ...
  native/         ...     # apps built with no cross-platform framework
  _ignore/        ...     # skipped: staging, unlabelled, licence-bound
```

Then measure:

```bash
python3 tools/corpus_check.py corpus/
python3 tools/corpus_check.py corpus/ --json accuracy.json --min-accuracy 95
```

```
expected      n    ok      acc  confusions
------------------------------------------
flutter      12    12   100.0%  -
native        9     8    88.9%  unityx1
react-native  7     7   100.0%  -

27/28 correct — 96.4% accuracy
```

It exits non-zero below `--min-accuracy` (default: any mismatch fails), so the
same command works as a release gate. The suite picks it up too:

```bash
FRIDER_CORPUS=corpus/ python3 -m pytest tests/           # floor of 100%
FRIDER_CORPUS=corpus/ FRIDER_CORPUS_MIN_ACCURACY=95 python3 -m pytest tests/
```

Without `FRIDER_CORPUS` that test skips, so CI stays green without shipping
APKs. A mislabelled directory is rejected rather than silently scored zero, and
an empty corpus fails rather than reporting success.

## Development

```bash
python3 -m pytest tests/ -q     # 18 fixture-based tests
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

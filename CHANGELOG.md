# Changelog

All notable changes to this project are documented here. This project follows
[semantic versioning](https://semver.org/): the `--json` payload carries its own
`schema_version`, bumped whenever a field changes meaning or disappears.

## 0.4.0

### Added

- **`--adb --list`** shows what is installed without pulling anything. Listing
  is the step before a scan, and it costs one adb call where `--all` costs a
  full pull of every APK on the device. Third-party packages by default — the
  same set `--all` classifies, so the listing says exactly what a scan would
  cover — with `--list-all` for system packages too. `--json` returns the usual
  versioned envelope, carrying `packages` instead of `results`.

### Changed

- **The banner prints on every run, on stderr** — the wordmark in two solid
  colours, `F` red and `rider` blue, with a one-line description and the
  running version under it (`Android app framework detector · v0.4.0`).
  It appeared only in `--help` before. stderr rather than stdout because stdout
  is the contract: `--json` gets piped into `jq` and tables get piped into
  `awk`, and neither survives seven lines of ASCII art in front of it. The
  version is there because the first question about a surprising verdict is
  which build produced it.
- **Colour is decided per stream.** `Palette` took its TTY check from stdout
  whatever it was colouring, so a banner on stderr wrote escape codes into
  `2> log.txt` and lost its colour whenever stdout alone was piped. It now
  takes the stream it colours; `--no-color` and `NO_COLOR` still win.

## 0.3.0

### Changed — behaviour

- **`confidence` now describes how sure the verdict is, not which answer it
  reached.** Every native verdict previously read `Low`, so the most common
  result in any real scan looked like the least trustworthy one. `Low` now means
  *could not tell* — input too thin to settle the question. A native verdict
  over a complete APK reports `High`.
- **Confidence counts only the winning framework.** It previously summed
  matched paths across every framework that hit, so one unrelated weak match
  could promote a single-marker verdict to `High`.
- **A split set shipping both JS engines reports both.** Only the first was
  named before, hiding exactly the distinction this tool exists to make.

### Changed — output contract

- **`--json` is wrapped in a versioned envelope** (`schema_version`, `tool`,
  `tool_version`, `results`) so a consumer can refuse input it does not
  understand instead of misreading a changed field.
- **Results carry a stable machine id** in `framework`, with `frameworks`
  listing every id the verdict covers. `verdict` remains prose for humans and
  may be reworded; branch on `framework` instead.

### Added — detection

- **Lynx (ByteDance)** fingerprint, framework id `lynx`. Lynx is a
  cross-platform UI framework in the same class as React Native — its own
  runtime (`liblynx.so`, `liblynxbase.so`) rendering `template.js` bundles
  produced by its toolchain — and apps embedding it previously reported
  `native`. The asset marker `assets/lynx_core.js` is gated behind `requires`,
  so a bundle without the runtime cannot claim the framework. Found by sweeping
  a device: one of 141 packages ships Lynx, and no other package matches the
  marker.
- `.NET MAUI`, `NativeScript`, `Qt for Android` and `Titanium` fingerprints.
  MAUI is weighted above `xamarin` so the more specific match wins.
- The `xamarin` rule recognises modern .NET builds (assembly store,
  `libmono-android`), not only classic Xamarin.
- `SecNeo DexShield` joins the notable-library list (`libDexHelper*.so`),
  alongside the SecIron pair already there.

### Added — documentation

- **A measured accuracy figure**, from a 141-package device sweep cross-checked
  against dex contents: 140/141 framework verdicts confirmed, `kotlin` correct
  on 123/132 apps with readable dex. See the README.
- **Three new *Known limits***, each observed in that sweep rather than
  imagined: a build that excludes Kotlin's packaged resources reads
  `kotlin: false`; `kotlin: true` means the Kotlin runtime is packaged, not
  that the app's own code is Kotlin; and native libraries packed into a
  compressed container (Meta's Superpack) hide the engine name, so such an app
  can report `native` while embedding a framework.
- AGENTS.md records how to verify a sub-signal against the dex, and the two
  ways that check misleads — R8 renaming and dex packers make absence
  meaningless, while a single vestigial class reference is not use.

### Fixed

- **Kotlin went undetected on R8-minified apps.** The `kotlin` signal keyed on a
  single marker, `META-INF/*.kotlin_module` — which R8 strips during minification.
  Every minified Kotlin app (i.e. most shipping apps) therefore read `kotlin: false`.
  The rule now accepts a `markers` list and also matches `kotlin/*.kotlin_builtins`
  and the `kotlinx *.version` stamps, both of which survive minification. The legacy
  single-`marker` form still loads. Found on a shipping banking app: a Kotlin app
  with no `.kotlin_module`, previously reported `kotlin: false`, now `true`; its
  framework verdict (native) was correct throughout. Verified afterwards against
  dex contents over a 141-package device sweep — the signal goes from **42.4%**
  (56/132) to **93.2%** (123/132) accurate on apps whose dex can be read. The
  residual 9 are documented in the README's *Known limits*: 8 apps ship no Kotlin
  resource at all because the build excludes them, and 1 packages the Kotlin
  runtime without containing Kotlin code of its own.
- **A `kotlin` rule with a misspelled key disabled Kotlin detection in
  silence.** A block containing neither `markers` nor `marker` yielded no
  patterns, so every app read `kotlin: false` with nothing to indicate why —
  while the same typo in a framework entry was already a load error. Such a
  rules file is now rejected at load time.
- **An asset marker could claim a framework on its own.** `assets/index.android.bundle`
  alone was enough for a React Native verdict — but Android loads nothing from
  `assets/`, and a shipped bundle with no engine to execute it is a payload, not
  a framework. Found on a real banking app that ships a vestigial RN bundle on
  a Flutter host and was misreported hybrid. Frameworks can now declare
  `requires` (runtime `.so` markers) that must match before the framework is
  claimed; asset markers corroborate but cannot fire alone. Flutter and RN both
  declare `requires`; a full 141-package device sweep changed only that one
  verdict after the fix.
- **`Entry.match_path()` could silently truncate a path containing `!`.**
  When `inner` was missing, it fell back to re-deriving the path from the
  display string by splitting on `!` — legal in zip entry names — so a
  directly-constructed entry like `assets/we!rd/lib/...` could be read as
  `rd/lib/...` and match markers that were not there. The inner path is now
  required at construction: a caller who omits it gets a loud `TypeError`
  instead of a misclassification. `innermost()` remains for parsing display
  paths.
- **A device-supplied package name could delete a directory outside the cache.**
  The name became a cache subdirectory that is wiped before each pull, so a
  device reporting `../victim` under `--adb --all` ran `rmtree` on a path outside
  the cache, and an absolute name discarded the cache root entirely — 
  `os.path.join("/cache", "/etc/x")` is `/etc/x`. Names are now validated against
  the Android package-name grammar, the resolved path is checked to be inside the
  cache root, and a bad name becomes an error row.
- **CJK app names made the table ragged.** Column widths were counted in
  characters, but a terminal draws East Asian text double-width. Widths and
  padding now count terminal columns.
- **`--adb --all` silently ignored any package names given alongside it**, which
  looked like a scan of exactly those packages. It now says what it is doing.
- **A path containing `!` matched markers that were not there.** The container
  boundary in a display path was parsed back out by splitting on `!`, which is
  a legal zip entry-name character — so `assets/we!rd/lib/.../libflutter.so`
  was read as `rd/lib/.../libflutter.so`, mis-citing the evidence. The match
  path now travels alongside the display path instead of being re-derived.
- **Markers were unanchored substring searches.** A bundled copy under
  `assets/`, a renamed `.so.bak`, or a library path under `META-INF/` matched a
  framework, though Android only loads `lib/<abi>/*.so` from the archive root.
  An APK with no native libraries at all could report Flutter. Every marker is
  now anchored to the whole entry path, and a test fails if an unanchored one
  reappears.
- **Colored tables came out ragged.** Cells were padded after ANSI codes were
  added, so the escapes counted toward the width — the default interactive
  output was broken.
- **An unreadable APK in a set was classified as native.** A truncated pull or
  bad split was surfaced as an opaque entry, so a file that could not be read
  reported as an app with no framework markers.
- **A missing, malformed, or bad-regex `--rules` file printed a traceback.**
  Rules are validated and every pattern compiled at load time.
- **`--adb --all` crashed against an unreachable device**, and one bad pull
  aborted the whole batch instead of marking that row.
- **Stale splits contaminated the adb cache.** A package that previously shipped
  more splits left files behind that were classified as part of the next pull.
- **Multi-line error text broke the table.** adb relays multi-line stderr, and a
  newline inside a cell tore the row apart.
- **adb calls had no timeout**, so a wedged device hung indefinitely; a missing
  adb binary raised `FileNotFoundError`.
- **`--no-cache` leaked its temp directory.**
- `res/xml/config.xml` alone reported Apache Cordova, and `libfbjni.so` alone
  reported React Native — both paths ordinary native apps ship.
- Ionic markers only matched one directory below `assets/www`, missing the
  nested paths real builds produce.
- Directory-mode paths now normalise Windows separators.

### Performance

- **Nested APK splits are streamed, not buffered.** Listing entry names in an
  80 MiB container cost 80 MiB resident; it now costs 2 MiB.
- Loose files in a directory are read on demand rather than slurped up front.

### Infrastructure

- CI across Python 3.9–3.13 on Linux, plus 3.13 on macOS and Windows, with a
  lint job and a check that the wheel still declares no runtime dependencies.
- Release workflow using Trusted Publishing (OIDC) — no API token is stored in
  this repository. It refuses to upload when a release tag disagrees with
  `__version__`.
- `tools/corpus_check.py` measures accuracy against a labelled corpus of real
  APKs; the suite runs it when `FRIDER_CORPUS` is set.
- The version is declared once, in `frider/__init__.py`.
- `py.typed`, so downstream type-checkers can see the annotations.
- GitHub Actions pinned by commit SHA, with Dependabot tracking updates.

## 0.2.0

- Fixed five bugs and overhauled the CLI UX.
- Corrupt or truncated APKs surface as clean errors rather than tracebacks.

## 0.1.0

- Initial release: Flutter, React Native (Hermes vs JavaScriptCore), Cordova,
  Ionic, Capacitor, Kony, Xamarin, Unity and native detection from APK
  contents, with fingerprints as data in `rules.json`.

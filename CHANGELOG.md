# Changelog

All notable changes to this project are documented here. This project follows
[semantic versioning](https://semver.org/): the `--json` payload carries its own
`schema_version`, bumped whenever a field changes meaning or disappears.

## Unreleased

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

- `.NET MAUI`, `NativeScript`, `Qt for Android` and `Titanium` fingerprints.
  MAUI is weighted above `xamarin` so the more specific match wins.
- The `xamarin` rule recognises modern .NET builds (assembly store,
  `libmono-android`), not only classic Xamarin.

### Fixed

- **`Entry.match_path()` could silently truncate a path containing `!`.**
  When `inner` was missing, it fell back to re-deriving the path from the
  display string by splitting on `!` — legal in zip entry names — so a
  directly-constructed entry like `assets/we!rd/lib/...` could be read as
  `rd/lib/...` and match markers that were not there. The inner path is now
  required at construction: a caller who omits it gets a loud `TypeError`
  instead of a misclassification. `innermost()` remains for parsing display
  paths.
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

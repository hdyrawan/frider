# Security

## Reporting a vulnerability

Report privately through GitHub's
[security advisory form](https://github.com/hdyrawan/frider/security/advisories/new)
rather than a public issue. Expect an acknowledgement within a week.

## Threat model

frider's input is untrusted by design: the whole point is inspecting APKs you
did not build, including ones you suspect. Two properties keep that safe.

**Contents are never read.** Classification matches entry *names* only, so a
malicious payload inside an APK is never parsed, decompressed, or executed.
Nothing in the classification path reads a file body.

**Archive handling is bounded.** Nested APKs inside an XAPK/APKS container are
streamed to a temp file rather than buffered, so a large container cannot
exhaust memory. Entries are listed, never extracted to disk, so a crafted entry
name cannot escape a destination directory — there is no destination directory.

Two things worth knowing:

- **A custom `--rules` file is code you are trusting.** Its patterns are
  compiled as regexes, so a hostile rules file can cause catastrophic
  backtracking. Only use rule files you would run a script from.
- **`--adb` writes to disk.** Pulled APKs are cached under
  `~/.cache/frider/<package>/`, and that directory is cleared before each pull.
  Package names come from the device's package manager.

## Supported versions

Fixes land on the latest release. There are no long-term support branches.

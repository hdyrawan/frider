"""Open APK / XAPK / APKS files or directories and expose their entries.

Entries are plain names + an optional reader. Nested APKs inside an XAPK/APKS
container are surfaced with a ``<container>!<inner-path>`` prefix so the
classifier sees the inner zip's contents.

That prefix is for display only. The path rules match on travels alongside it as
``Entry.inner`` (read via ``Entry.match_path()``), because ``!`` is a legal
character in a zip entry name — parsing the boundary back out of the display
path truncated real names like ``assets/we!rd/lib/...``.

Readers are safe to call any time: file-backed entries reopen the zip on each
read instead of capturing a handle that a ``with`` block later closed, so
entries survive their source archive being garbage-collected.
"""

from __future__ import annotations

import os
import shutil
import tempfile
import zipfile
from dataclasses import dataclass
from typing import IO, Callable, List, Optional

# Streaming chunk for copying nested archive members out of their container.
COPY_CHUNK = 1024 * 1024


CONTAINER_SUFFIXES = (".apk", ".xapk", ".apks")


@dataclass
class Entry:
    path: str
    is_dir: bool
    read: Optional[Callable[[], bytes]]
    # The path rules match on, carried alongside rather than parsed back out of
    # ``path``. ``!`` marks a container boundary in ``path`` for display, but it
    # is also a legal character in a zip entry name, so recovering the inner
    # path by splitting on it truncated names like ``assets/we!rd/lib/...`` —
    # which both mis-cited the evidence and let an unrelated entry match a
    # marker. Set at construction, where the boundary is actually known, and
    # REQUIRED: a fallback that re-derives it from ``path`` would silently
    # reopen the truncation bug for any caller who forgets it.
    inner: str

    def match_path(self) -> str:
        """The path a rule should be tested against.

        This is always the inner path carried at construction — never parsed
        back out of the display ``path``.
        """
        return self.inner


def _make_file_reader(path: str, name: str) -> Callable[[], bytes]:
    """Read ``name`` from ``path`` by reopening the zip — safe after close."""

    def read() -> bytes:
        with zipfile.ZipFile(path) as zf:
            return zf.read(name)

    return read


def _make_buffer_reader(zf: zipfile.ZipFile, name: str) -> Callable[[], bytes]:
    """Read from a nested zip whose backing file the caller keeps referenced."""

    def read() -> bytes:
        return zf.read(name)

    return read


def _spool_member(zf: zipfile.ZipFile, name: str) -> IO[bytes]:
    """Copy a nested archive member out to a temp file, streaming.

    ``zipfile`` needs a seekable file object, so a nested APK cannot simply be
    read lazily from its container. Buffering it in memory instead cost a
    resident copy of every split — 122 MiB for a 180 MiB XAPK, and real ones
    reach several GB — purely to list entry *names*. Spooling to disk keeps
    that bounded. ``SpooledTemporaryFile`` is deliberately not used: it lacks
    ``seekable()`` before Python 3.11, and this package supports 3.9.
    """
    tmp = tempfile.TemporaryFile()
    try:
        with zf.open(name) as src:
            shutil.copyfileobj(src, tmp, COPY_CHUNK)
        tmp.seek(0)
        return tmp
    except BaseException:
        tmp.close()
        raise


def _zip_entries(zf: zipfile.ZipFile, reopen_path: Optional[str], prefix: str = "") -> List[Entry]:
    out: List[Entry] = []
    for info in zf.infolist():
        name = info.filename
        display = f"{prefix}!{name}" if prefix else name
        if name.endswith("/"):
            out.append(Entry(display, True, None, inner=name))
        elif reopen_path is not None:
            out.append(Entry(display, False, _make_file_reader(reopen_path, name),
                             inner=name))
        else:
            out.append(Entry(display, False, _make_buffer_reader(zf, name),
                             inner=name))
    return out


def entries_for(path: str) -> List[Entry]:
    """Return all entries for an APK file, an XAPK/APKS container, or a
    directory of APKs (each APK inside becomes a ``<filename>!<path>`` entry).
    """
    if os.path.isdir(path):
        out: List[Entry] = []
        for root, _dirs, files in os.walk(path):
            for fn in sorted(files):
                fp = os.path.join(root, fn)
                # Rules match on '/' separators, so normalise Windows '\'.
                rel = os.path.relpath(fp, path).replace(os.sep, "/")
                if zipfile.is_zipfile(fp):
                    # a real APK/split set inside the dir — surface its entries
                    for e in entries_for(fp):
                        out.append(Entry(f"{rel}!{e.path}", e.is_dir, e.read,
                                         inner=e.match_path()))
                elif fn.lower().endswith(CONTAINER_SUFFIXES):
                    # Named like an APK but unreadable as one (truncated pull,
                    # bad split). Surfacing it as an opaque blob would let the
                    # set classify as "native" — a wrong answer is worse than
                    # an error, so refuse the whole set.
                    raise ValueError(f"unreadable apk in set: {fp}")
                else:
                    out.append(Entry(rel, False, _make_lazy_file_reader(fp),
                                     inner=rel))
        return out

    if not zipfile.is_zipfile(path):
        raise ValueError(f"not a zip/apk: {path}")

    try:
        with zipfile.ZipFile(path) as zf:
            out = _zip_entries(zf, reopen_path=path)
            # Surface nested APKs (XAPK/APKS containers hold .apk members).
            for e in list(out):
                if not e.is_dir and e.match_path().lower().endswith(CONTAINER_SUFFIXES):
                    try:
                        # nzf keeps the temp file referenced, and the readers
                        # keep nzf referenced, so it lives exactly as long as
                        # the entries do.
                        nzf = zipfile.ZipFile(_spool_member(zf, e.match_path()))
                        out.extend(_zip_entries(nzf, reopen_path=None, prefix=e.path))
                    except (zipfile.BadZipFile, OSError):
                        pass
            return out
    except zipfile.BadZipFile as e:
        # A file with zip magic but a broken central directory (truncated
        # download, bad split) must surface as a clean error, not a traceback.
        raise ValueError(f"corrupt zip: {path} ({e})") from e


def _make_lazy_file_reader(path: str) -> Callable[[], bytes]:
    """Read a loose file on demand. Classification only ever looks at entry
    names, so slurping every payload up front just pinned hundreds of MiB of
    asset/obb bytes in RAM for nothing."""

    def read() -> bytes:
        with open(path, "rb") as fh:
            return fh.read()

    return read


def innermost(path: str) -> str:
    """The path after any ``container!`` prefix — what rules should match."""
    return path.split("!")[-1]

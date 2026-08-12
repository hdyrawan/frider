"""Open APK / XAPK / APKS files or directories and expose their entries.

Entries are plain names + an optional reader. Nested APKs inside an XAPK/APKS
container are surfaced with a ``<container>!<inner-path>`` prefix so the
classifier sees the inner zip's contents. Rules match against the innermost
path (the part after the last ``!``).

Readers are safe to call any time: file-backed entries reopen the zip on each
read instead of capturing a handle that a ``with`` block later closed, so
entries survive their source archive being garbage-collected.
"""

from __future__ import annotations

import io
import os
import zipfile
from dataclasses import dataclass
from typing import Callable, List, Optional


@dataclass
class Entry:
    path: str
    is_dir: bool
    read: Optional[Callable[[], bytes]]


def _make_file_reader(path: str, name: str) -> Callable[[], bytes]:
    """Read ``name`` from ``path`` by reopening the zip — safe after close."""

    def read() -> bytes:
        with zipfile.ZipFile(path) as zf:
            return zf.read(name)

    return read


def _make_buffer_reader(zf: zipfile.ZipFile, name: str) -> Callable[[], bytes]:
    """Read from an in-memory zip that the caller keeps referenced."""

    def read() -> bytes:
        return zf.read(name)

    return read


def _zip_entries(zf: zipfile.ZipFile, reopen_path: Optional[str], prefix: str = "") -> List[Entry]:
    out: List[Entry] = []
    for info in zf.infolist():
        name = info.filename
        display = f"{prefix}!{name}" if prefix else name
        if name.endswith("/"):
            out.append(Entry(display, True, None))
        elif reopen_path is not None:
            out.append(Entry(display, False, _make_file_reader(reopen_path, name)))
        else:
            out.append(Entry(display, False, _make_buffer_reader(zf, name)))
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
                rel = os.path.relpath(fp, path)
                if zipfile.is_zipfile(fp):
                    # a real APK/split set inside the dir — surface its entries
                    for e in entries_for(fp):
                        out.append(Entry(f"{rel}!{e.path}", e.is_dir, e.read))
                else:
                    with open(fp, "rb") as fh:
                        data = fh.read()
                    out.append(Entry(rel, False, _make_bytes_reader(data)))
        return out

    if not zipfile.is_zipfile(path):
        raise ValueError(f"not a zip/apk: {path}")

    try:
        with zipfile.ZipFile(path) as zf:
            out = _zip_entries(zf, reopen_path=path)
            # Surface nested APKs (XAPK/APKS containers hold .apk members).
            for e in list(out):
                inner = e.path.split("!")[-1]
                if not e.is_dir and inner.lower().endswith((".apk", ".xapk", ".apks")):
                    try:
                        assert e.read is not None
                        data = e.read()
                        nzf = zipfile.ZipFile(io.BytesIO(data))
                        out.extend(_zip_entries(nzf, reopen_path=None, prefix=e.path))
                    except (zipfile.BadZipFile, OSError):
                        pass
            return out
    except zipfile.BadZipFile as e:
        # A file with zip magic but a broken central directory (truncated
        # download, bad split) must surface as a clean error, not a traceback.
        raise ValueError(f"corrupt zip: {path} ({e})") from e


def _make_bytes_reader(data: bytes) -> Callable[[], bytes]:
    def read() -> bytes:
        return data

    return read


def innermost(path: str) -> str:
    """The path after any ``container!`` prefix — what rules should match."""
    return path.split("!")[-1]

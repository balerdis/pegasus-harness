"""A real filesystem that also remembers the order writes and removals happened in.

`PosixFileSystem` has nothing to say about *when* a write landed relative to
another one, and file metadata cannot answer that either: two writes a
moment apart can carry the same `st_mtime_ns` on this machine's filesystem
far too often to trust. Some tests need that order anyway — a snapshot has
to reach disk before the first artifact it protects — so this wraps a real
filesystem and appends to a list on every write and every removal, in the
order the calls happened. Every other call passes straight through; this is
bookkeeping around the real implementation, not a second one.
"""
from __future__ import annotations

from pathlib import Path

from pegasus.infra.fs_posix import PosixFileSystem


class RecordingFileSystem:
    """Delegates every port call to a real filesystem and records write/removal order."""

    def __init__(self, filesystem: PosixFileSystem | None = None):
        self._filesystem = filesystem or PosixFileSystem()
        self.writes: list[Path] = []
        self.removals: list[Path] = []

    # --- Reading ---

    def exists(self, path: Path) -> bool:
        return self._filesystem.exists(path)

    def read_bytes(self, path: Path) -> bytes:
        return self._filesystem.read_bytes(path)

    def mode_of(self, path: Path) -> int | None:
        return self._filesystem.mode_of(path)

    def list_dir(self, path: Path) -> list[str]:
        return self._filesystem.list_dir(path)

    # --- Permissions ---

    def mode_for(self, *, executable: bool) -> int:
        return self._filesystem.mode_for(executable=executable)

    # --- Writing ---

    def write_atomic(self, path: Path, content: bytes, *, mode: int = 0o644) -> None:
        self._filesystem.write_atomic(path, content, mode=mode)
        self.writes.append(path)

    def remove(self, path: Path) -> None:
        self._filesystem.remove(path)
        self.removals.append(path)

    def remove_dir(self, path: Path) -> None:
        self._filesystem.remove_dir(path)
        self.removals.append(path)

    def make_dir(self, path: Path, *, mode: int = 0o755) -> None:
        self._filesystem.make_dir(path, mode=mode)

    # --- Who is running ---

    def writable_on_behalf_of_owner(self, home: Path) -> bool:
        return self._filesystem.writable_on_behalf_of_owner(home)

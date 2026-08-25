"""Test doubles shared across the suite.

The filesystem port exists so that everything above it can be proven without a
home directory to ruin. This is the implementation that makes good on that.
"""
from __future__ import annotations

from pathlib import Path

from pegasus.ports.filesystem import FileSystemError

DEFAULT_MODE = 0o644
DEFAULT_DIR_MODE = 0o755


class FakeFileSystem:
    """An in-memory filesystem that answers the port and records what it was told.

    Beyond storing bytes it can be told to fail: ``fail_on`` names the paths
    whose next write must raise, which is how rollback gets exercised without
    filling a real disk.
    """

    def __init__(
        self,
        *,
        files: dict[Path, bytes] | None = None,
        modes: dict[Path, int] | None = None,
        owner: bool = True,
        privileged: bool = False,
        fail_on: set[Path] | None = None,
        fail_always: set[Path] | None = None,
        fail_remove: set[Path] | None = None,
        fail_remove_dir: set[Path] | None = None,
        fail_list: set[Path] | None = None,
        fail_read: set[Path] | None = None,
    ):
        self.files: dict[Path, bytes] = dict(files or {})
        self.modes: dict[Path, int] = dict(modes or {})
        self.directories: set[Path] = set()
        self.directory_modes: dict[Path, int] = {}
        self.owner = owner
        self.privileged = privileged
        self.fail_on: set[Path] = set(fail_on or ())
        self.fail_always: set[Path] = set(fail_always or ())
        self.fail_remove: set[Path] = set(fail_remove or ())
        self.fail_remove_dir: set[Path] = set(fail_remove_dir or ())
        self.fail_list: set[Path] = set(fail_list or ())
        self.fail_read: set[Path] = set(fail_read or ())
        self.writes: list[Path] = []
        self.removals: list[Path] = []

    # --- Reading ---

    def exists(self, path: Path) -> bool:
        return path in self.files or path in self.directories

    def read_bytes(self, path: Path) -> bytes:
        if path in self.fail_read:
            raise FileSystemError(f"refusing to read {path}: injected failure")
        if path not in self.files:
            raise FileSystemError(f"no such file: {path}")
        return self.files[path]

    def mode_of(self, path: Path) -> int | None:
        if path in self.files:
            return self.modes.get(path, DEFAULT_MODE)
        if path in self.directories:
            return self.directory_modes.get(path, DEFAULT_DIR_MODE)
        return None

    def list_dir(self, path: Path) -> list[str]:
        if path in self.fail_list:
            raise FileSystemError(f"refusing to list {path}: injected failure")
        if path in self.files:
            raise FileSystemError(f"not a directory: {path}")
        names = {
            candidate.relative_to(path).parts[0]
            for candidate in (*self.files, *self.directories)
            if candidate != path and path in candidate.parents
        }
        return sorted(names)

    # --- Writing ---

    def write_atomic(self, path: Path, content: bytes, *, mode: int = DEFAULT_MODE) -> None:
        self.make_dir(path.parent)
        if path in self.fail_always:
            raise FileSystemError(f"refusing to write {path}: injected permanent failure")
        if path in self.fail_on:
            # One shot, like a transient disk error: the retry that puts the
            # previous content back must be allowed to succeed.
            self.fail_on.discard(path)
            raise FileSystemError(f"refusing to write {path}: injected failure")
        self.files[path] = content
        self.modes[path] = mode
        self.writes.append(path)

    def remove(self, path: Path) -> None:
        if path in self.fail_remove:
            raise FileSystemError(f"refusing to remove {path}: injected failure")
        self.files.pop(path, None)
        self.modes.pop(path, None)
        self.removals.append(path)

    def remove_dir(self, path: Path) -> None:
        if path in self.fail_remove_dir:
            raise FileSystemError(f"refusing to remove {path}: injected failure")
        if path in self.files:
            # The real one calls rmtree, which raises on a file. Deleting it
            # here instead would let a caller aimed at the wrong kind of path
            # pass its tests and destroy data in production.
            raise FileSystemError(f"cannot remove {path}: not a directory")
        for candidate in list(self.files):
            if candidate == path or path in candidate.parents:
                self.files.pop(candidate, None)
                self.modes.pop(candidate, None)
        for candidate in list(self.directories):
            if candidate == path or path in candidate.parents:
                self.directories.discard(candidate)
                self.directory_modes.pop(candidate, None)
        self.removals.append(path)

    def make_dir(self, path: Path, *, mode: int = 0o755) -> None:
        # Additive, like the real filesystem: a directory that already exists
        # keeps whatever mode it has. The mode argument only ever applies to
        # the leaf this call creates; any missing parents created along the
        # way get the default mode, never the one that was requested.
        if path in self.directories:
            return
        for ancestor in reversed(path.parents):
            if ancestor not in self.directories:
                self.directories.add(ancestor)
                self.directory_modes[ancestor] = DEFAULT_DIR_MODE
        self.directories.add(path)
        self.directory_modes[path] = mode

    # --- Who is running ---

    def owned_by_current_user(self, path: Path) -> bool:
        return self.owner

    def running_privileged(self) -> bool:
        return self.privileged

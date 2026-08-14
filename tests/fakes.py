"""Test doubles shared across the suite.

The filesystem port exists so that everything above it can be proven without a
home directory to ruin. This is the implementation that makes good on that.
"""
from __future__ import annotations

from pathlib import Path

from pegasus.ports.filesystem import FileSystemError

DEFAULT_MODE = 0o644


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
    ):
        self.files: dict[Path, bytes] = dict(files or {})
        self.modes: dict[Path, int] = dict(modes or {})
        self.directories: set[Path] = set()
        self.owner = owner
        self.privileged = privileged
        self.fail_on: set[Path] = set(fail_on or ())
        self.fail_always: set[Path] = set(fail_always or ())
        self.fail_remove: set[Path] = set(fail_remove or ())
        self.writes: list[Path] = []
        self.removals: list[Path] = []

    # --- Reading ---

    def exists(self, path: Path) -> bool:
        return path in self.files or path in self.directories

    def read_bytes(self, path: Path) -> bytes:
        if path not in self.files:
            raise FileSystemError(f"no such file: {path}")
        return self.files[path]

    def mode_of(self, path: Path) -> int | None:
        if path in self.files:
            return self.modes.get(path, DEFAULT_MODE)
        if path in self.directories:
            return 0o755
        return None

    # --- Writing ---

    def write_atomic(self, path: Path, content: bytes, *, mode: int = DEFAULT_MODE) -> None:
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

    def make_dir(self, path: Path, *, mode: int = 0o755) -> None:
        self.directories.add(path)

    # --- Who is running ---

    def owned_by_current_user(self, path: Path) -> bool:
        return self.owner

    def running_privileged(self) -> bool:
        return self.privileged

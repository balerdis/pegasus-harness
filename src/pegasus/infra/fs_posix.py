"""The POSIX filesystem, spelled out.

The whole point of this module is the write. A naive ``open(path, "wb")``
truncates the file before it writes, so a crash — or a full disk — in the middle
leaves the user with a stump that Pegasus recorded as installed. The sequence
below never puts an incomplete file where a reader could find it:

1. write the whole content to a temporary file in the *same* directory, so the
   final step is a rename within one filesystem and never a copy across two;
2. ``fsync`` it, so the bytes are on the device and not only in a buffer;
3. ``chmod`` it before it is visible under its real name;
4. ``os.replace`` it onto the target, which POSIX guarantees is atomic;
5. ``fsync`` the directory, so the rename itself survives a power cut.

Everything else here is small on purpose: the port asks for little, and little
is what a platform implementation should have to get right.
"""
from __future__ import annotations

import os
import shutil
import stat
import tempfile
from pathlib import Path

from pegasus.ports.filesystem import FileSystemError

TEMPORARY_PREFIX = ".pegasus-"
TEMPORARY_SUFFIX = ".partial"


class PosixFileSystem:
    """A filesystem backed by the real one, on Linux and other POSIX systems."""

    # --- Reading ---

    def exists(self, path: Path) -> bool:
        try:
            return path.exists()
        except OSError as error:
            # `Path.exists()` swallows only the errors that already mean
            # absence — a parent that cannot be traversed raises instead, and
            # that is not the same fact. Absent and unreadable collapse to
            # the same `False` otherwise, and a caller downstream — a
            # snapshot deciding what to write back — cannot tell one from
            # the other once they do.
            raise FileSystemError(f"cannot tell whether {path} exists: {error}") from error

    def read_bytes(self, path: Path) -> bytes:
        try:
            return path.read_bytes()
        except OSError as error:
            raise FileSystemError(f"cannot read {path}: {error}") from error

    def mode_of(self, path: Path) -> int | None:
        try:
            return stat.S_IMODE(path.stat().st_mode)
        except OSError:
            return None

    def list_dir(self, path: Path) -> list[str]:
        # Delegates to `self.exists` rather than a raw `path.exists()` on
        # purpose: an unreadable parent must raise here exactly as it does
        # there, not list empty by accident because the two calls happened
        # to share the same underlying mistake.
        if not self.exists(path):
            return []
        try:
            return sorted(entry.name for entry in path.iterdir())
        except OSError as error:
            raise FileSystemError(f"cannot list {path}: {error}") from error

    # --- Permissions ---

    def mode_for(self, *, executable: bool) -> int:
        return 0o755 if executable else 0o644

    # --- Writing ---

    def write_atomic(self, path: Path, content: bytes, *, mode: int = 0o644) -> None:
        parent = path.parent
        self.make_dir(parent)
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                dir=parent, prefix=TEMPORARY_PREFIX, suffix=TEMPORARY_SUFFIX, delete=False
            ) as output:
                temporary = Path(output.name)
                output.write(content)
                output.flush()
                os.fsync(output.fileno())
            temporary.chmod(mode)
            os.replace(temporary, path)
            temporary = None
            _fsync_directory(parent)
        except OSError as error:
            raise FileSystemError(f"cannot write {path}: {error}") from error
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def remove(self, path: Path) -> None:
        try:
            path.unlink(missing_ok=True)
        except OSError as error:
            raise FileSystemError(f"cannot remove {path}: {error}") from error

    def remove_dir(self, path: Path) -> None:
        try:
            shutil.rmtree(path)
        except FileNotFoundError:
            pass
        except OSError as error:
            raise FileSystemError(f"cannot remove {path}: {error}") from error

    def make_dir(self, path: Path, *, mode: int = 0o755) -> None:
        try:
            path.mkdir(mode=mode, parents=True, exist_ok=True)
        except OSError as error:
            raise FileSystemError(f"cannot create {path}: {error}") from error

    # --- Who is running ---

    def writable_on_behalf_of_owner(self, home: Path) -> bool:
        if os.geteuid() == 0:
            return False
        try:
            return home.stat().st_uid == os.geteuid()
        except OSError:
            return False


def _fsync_directory(path: Path) -> None:
    """Persist the rename itself, not just the bytes it points at."""
    descriptor = os.open(path, os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)

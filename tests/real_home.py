"""A throwaway home directory backed by the real POSIX filesystem.

The in-memory double answers the port, which is what makes most of the suite
fast to write, but it has no permission bits and no system calls to patch —
it cannot be put into a state the real filesystem can. Any test module that
needs one of those real conditions builds on this base rather than the fake,
and reaches for `platform_conditions` to produce them.

Kept generic on purpose: this only sets up the throwaway home and the real
filesystem underneath it. Anything specific to the surface under test — the
CLI's runtime, its layout, how it is invoked — belongs in a subclass in that
test module, not here.
"""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

import no_network  # noqa: F401  -- importing it is what installs the refusal
from pegasus.infra.fs_posix import PosixFileSystem


class RealHomeTestCase(unittest.TestCase):
    """A throwaway home with the real POSIX filesystem underneath it."""

    def setUp(self):
        if os.geteuid() == 0:
            self.skipTest("root is not refused by permission bits, and Pegasus refuses to install as root")
        self.directory = tempfile.TemporaryDirectory(dir=_scratch_root())
        self.addCleanup(self.directory.cleanup)
        self.home = Path(self.directory.name)
        self.filesystem = PosixFileSystem()


def _scratch_root() -> str | None:
    """Where the throwaway home is carved out of.

    `write_atomic` waits for the device on every write, twice, so that a power
    cut cannot leave a user's configuration half written. A home that is
    deleted at the end of the test has nothing to survive, and that wait is
    most of the suite's running time. A memory-backed filesystem keeps the
    call doing exactly what it does in production and gives it nothing to
    spin up; where there is none, the default location is used and the tests
    are only slower.
    """
    memory = Path("/dev/shm")
    return str(memory) if memory.is_dir() and os.access(memory, os.W_OK) else None

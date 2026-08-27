"""Conditions the real filesystem can be put into, on purpose, for a test.

`FakeFileSystem` answers the port from memory, so it can be told to fail by
setting a flag; the real one cannot. Every function here produces, on real
disk, a condition that the in-memory double injects — an unreadable file, a
directory that refuses a write, a path whose removal is refused, a write that
fails once and then succeeds, a probe that fails only once something is
really there.

Each function mutates something outside the test (a permission bit, a
patched system call) and returns a zero-argument callable that undoes it.
That callable is meant to be handed straight to ``self.addCleanup`` — a
module-level function has no ``self`` to register a cleanup on its own, and a
returned callable is the smallest thing that works the same way whether the
caller is a ``TestCase`` method or something else entirely. A read-only
directory cannot be deleted, so leaving a condition in place past the end of
a test would break the temporary directory's own cleanup; every helper here
must be paired with the callable it returns.
"""
from __future__ import annotations

import os
import stat
from pathlib import Path
from typing import Callable


def make_unreadable(path: Path) -> Callable[[], None]:
    """Make a file or directory whose contents cannot be read.

    Strips every permission bit, which denies a file's contents and a
    directory's listing equally well. The mode in place before the call is
    restored by the returned callable.
    """
    original = stat.S_IMODE(path.stat().st_mode)
    path.chmod(0o000)
    return lambda: path.chmod(original)


def make_unwritable(path: Path) -> Callable[[], None]:
    """Make a directory that refuses a new file written into it.

    Read and execute bits stay, so the directory can still be traversed and
    listed; only write is denied, which is what makes creating a file inside
    it fail while everything else about the directory keeps working.
    """
    original = stat.S_IMODE(path.stat().st_mode)
    path.chmod(0o555)
    return lambda: path.chmod(original)


def make_undeletable(path: Path) -> Callable[[], None]:
    """Make a path whose holder refuses its removal.

    Deleting an entry is a write to the directory that holds it, not to the
    entry itself, so this locks the parent directory rather than the path
    passed in — the permission that actually governs removal on a POSIX
    filesystem.
    """
    return make_unwritable(path.parent)


def fail_next_write_once(path: Path) -> Callable[[], None]:
    """Make the next atomic write to this path fail, and the one after it succeed.

    No permission bit produces this: a directory that refuses a write
    refuses every write to it, not just the first. This patches
    ``os.replace``, the call ``write_atomic`` relies on to make the final
    rename atomic, the way `test_filesystem.py` already stubs it to stand in
    for a full disk — except keyed on the destination path rather than on
    every call, so only the write aimed at this path is disturbed, and only
    once.
    """
    original = os.replace
    triggered = False

    def patched(source, destination, *arguments, **keywords):
        nonlocal triggered
        if not triggered and Path(destination) == path:
            triggered = True
            raise OSError(28, "No space left on device", str(destination))
        return original(source, destination, *arguments, **keywords)

    os.replace = patched
    return lambda: _restore(os, "replace", patched, original)


def fail_probe_once_it_exists(path: Path) -> Callable[[], None]:
    """Make determining this path's state fail, but only once something is
    really there.

    Keyed on the state of the disk, never on a call count. A run that probes
    an absent path first and a present one later needs the failure to land on
    the second probe regardless of how many times the code in between happens
    to ask; a count would tie the test to that number and misfire the moment
    an unrelated probe is added upstream.
    """
    original = os.stat

    def patched(target, *arguments, **keywords):
        answer = original(target, *arguments, **keywords)
        if not isinstance(target, int) and Path(target) == path:
            raise PermissionError(13, "Permission denied", str(target))
        return answer

    os.stat = patched
    return lambda: _restore(os, "stat", patched, original)


def _restore(module, name: str, installed: Callable, original: Callable) -> None:
    """Put the original call back, and refuse loudly if ours is not in place.

    These patches replace a module attribute, so they only unwind cleanly in
    reverse: restoring an inner one first would discard the outer patch and
    then resurrect the inner one, leaving the call replaced for every test
    that followed. Registering the returned callable with `addCleanup` gives
    that reverse order for free.

    Unwinding out of order is refused rather than repaired. Repairing it
    needs a stack of patches that can be removed from the middle, which is
    more machinery than a test helper should carry; a refusal turns a leak
    that would surface as an unrelated test failing later into an error on
    the test that caused it.
    """
    current = getattr(module, name)
    if current is not installed:
        raise RuntimeError(
            f"{module.__name__}.{name} is no longer the patch this restores: "
            "conditions must be undone in reverse, which addCleanup does"
        )
    setattr(module, name, original)

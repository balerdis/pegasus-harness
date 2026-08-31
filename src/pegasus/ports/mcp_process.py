"""The port through which Pegasus starts one configured MCP server and trades
exactly one line with it.

Nothing above this port may call `subprocess` directly, the same reason a
real fetch stays behind `Downloader`: what happens once a process is
launched has to be provable against a script instead of a real server, and
the guarantee that the child never outlives this call has to be free for
every caller rather than something each one has to get right on its own.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class MCPExchange:
    """What came back from launching one command and trying to trade one line with it.

    Read in order: `spawn_error` set means the command never became a
    process. Otherwise it did start -- `timed_out` means it never answered
    before the deadline (killed on the way out); failing that, `line` is its
    first line of stdout, or `None` if it exited on its own without printing
    one. `exit_code` is set once the process is no longer running, and is
    `None` while `timed_out` is true, so a caller can never trust an exit
    code taken from a process this port had to kill to get back.
    """

    line: str | None
    exit_code: int | None
    timed_out: bool
    spawn_error: str | None


@runtime_checkable
class MCPProcess(Protocol):
    def exchange(self, command: tuple[str, ...], request: str, timeout_seconds: float) -> MCPExchange:
        """Launch `command`, write `request` plus a newline to its stdin, and
        read back one line of stdout.

        The child is never left running past this call, on any exit path --
        answered, timed out, exited on its own, or failed to start.
        """

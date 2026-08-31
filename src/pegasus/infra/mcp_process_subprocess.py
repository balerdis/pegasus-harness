"""The real MCP process: launched exactly as configured, killed no matter how the exchange ends.

This class itself is proven for real, against fixture scripts shipped in the
test tree -- the launch, the timeout, and the unconditional kill are what
Pegasus owns. What no hermetic suite can prove is a real MCP server behind
it; that stays the business of a live run, the same distinction
`infra.downloader_http` draws against the real network.

The child inherits this process's environment unchanged, deliberately: some
MCP servers take secrets that way, and this is the one place that has to
launch them as they were actually configured. Nothing here reads or prints
that environment for any other reason.
"""
from __future__ import annotations

import select
import subprocess
import time

from pegasus.ports.mcp_process import MCPExchange

#: How long `close` waits for a killed child to actually go away before
#: giving up on the wait -- the kill itself is not optional, this is only
#: about how long we stay to confirm it.
SHUTDOWN_GRACE_SECONDS = 5

#: How long to wait for a process that already closed its stdout to finish
#: exiting, so `exited` and `timeout` never depend on winning a race.
EXIT_SETTLE_SECONDS = 2


class SubprocessMCPProcess:
    """Runs one command, trades one line with it, and never leaves it running."""

    def exchange(self, command: tuple[str, ...], request: str, timeout_seconds: float) -> MCPExchange:
        try:
            process = subprocess.Popen(  # noqa: S603
                list(command),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                bufsize=1,
            )
        except OSError as error:
            return MCPExchange(line=None, exit_code=None, timed_out=False, spawn_error=str(error))

        try:
            return self._talk(process, request, timeout_seconds)
        finally:
            self._close(process)

    def _talk(self, process: subprocess.Popen, request: str, timeout_seconds: float) -> MCPExchange:
        deadline = time.monotonic() + timeout_seconds
        try:
            process.stdin.write(request + "\n")
            process.stdin.flush()
        except (BrokenPipeError, OSError):
            pass  # The process may already be gone; what it exited with is read below.

        line: str | None = None
        stdout_closed = False
        try:
            remaining = deadline - time.monotonic()
            while remaining > 0:
                ready, _, _ = select.select([process.stdout], [], [], remaining)
                if ready:
                    raw = process.stdout.readline()
                    line = raw.rstrip("\n") if raw else None
                    stdout_closed = not raw
                    break
                if process.poll() is not None:
                    break
                remaining = deadline - time.monotonic()
        except OSError:
            pass

        if line is None and stdout_closed:
            # The pipe closing means the process is done talking, but it can
            # still be a moment from actually exiting. Without settling that,
            # a server that dies without answering gets reported as one that
            # never answered -- a different diagnosis, and a race deciding
            # which one the person is told.
            try:
                process.wait(timeout=EXIT_SETTLE_SECONDS)
            except subprocess.TimeoutExpired:
                pass

        timed_out = line is None and process.poll() is None
        return MCPExchange(line=line, exit_code=process.poll(), timed_out=timed_out, spawn_error=None)

    def _close(self, process: subprocess.Popen) -> None:
        """Guarantee the child is gone, whatever `_talk` did or raised."""
        if process.poll() is None:
            process.kill()
        try:
            process.wait(timeout=SHUTDOWN_GRACE_SECONDS)
        except subprocess.TimeoutExpired:
            pass
        for stream in (process.stdin, process.stdout):
            if stream is not None:
                stream.close()

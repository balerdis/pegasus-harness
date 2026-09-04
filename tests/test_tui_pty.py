"""Proof that the loop itself, not just the pure layer it calls, shows
something before an engine call rather than freezing until it returns.

`test_tui_navigator` and `test_tui_view` already prove `busy_message_for`
and `render_busy` are correct in isolation, but neither can prove `app.run`
actually calls them in the right order -- that is exactly the defect this
change closes, and it lives in the loop, not in either pure module. Proving
it needs a real terminal, so this drives the real binary through a pty
against a throwaway home, the same real-filesystem discipline `real_home`
uses for the rest of the suite, just carried one layer further out to the
process boundary.
"""
from __future__ import annotations

import io
import os
import pty
import select
import signal
import sys
import tempfile
import time
import unittest
from pathlib import Path

from dataclasses import replace

import no_network  # noqa: F401  -- importing it is what installs the refusal
from pegasus import cli
from pegasus.adapters import available
from pegasus.core import journal as journal_module
from pegasus.core.types import Environment
from pegasus.infra.fs_posix import PosixFileSystem
from pegasus.infra.journal_store_file import FileJournalStore
from pegasus.tui import wordmark

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC = REPO_ROOT / "src"

# Unique to the frame `app.run` draws before probing every adapter, at
# startup, before there is even a `Navigator` yet to hold a screen.
STARTUP_NEEDLE = "Detecting installed CLIs"

# Unique to the frame shown before `session.step` runs `doctor` for real.
STATUS_BUSY_NEEDLE = "Running diagnostics"

# Unique to the doctor report itself -- never shown on the main menu, where
# the words "Status and diagnostics" already appear as an entry's own label,
# so that phrase alone could not tell the two frames apart.
STATUS_RESULT_NEEDLE = "enter: view snapshot generations to restore"


def _scratch_root() -> str | None:
    memory = Path("/dev/shm")
    return str(memory) if memory.is_dir() and os.access(memory, os.W_OK) else None


class _RealTerminalSession:
    """A real `pegasus` process, talking to a real pty, against a throwaway
    home. Bytes sent and received exactly as a person's terminal would."""

    def __init__(self, home: Path):
        self.pid, self.master = pty.fork()
        if self.pid == 0:  # pragma: no cover -- runs in the child, a separate process
            os.environ["HOME"] = str(home)
            os.environ["XDG_DATA_HOME"] = str(home / ".local" / "share")
            os.environ.setdefault("TERM", "xterm")
            # This is a real, separate process: `no_network`'s socket patch
            # is process-local and does not reach it. The background update
            # check would otherwise be the one place a test in this suite
            # could touch the real network, so it is switched off here
            # rather than left to depend on that machine's own connectivity.
            os.environ["PEGASUS_NO_UPDATE_CHECK"] = "1"
            os.chdir(str(REPO_ROOT))
            sys.path.insert(0, str(SRC))
            os.execv(
                sys.executable,
                [sys.executable, "-c", "from pegasus.cli import main; raise SystemExit(main([]))"],
            )
        self._buffer = b""

    def press(self, text: str) -> None:
        os.write(self.master, text.encode())

    def output_so_far(self, *, quiet_for: float = 0.3, timeout: float = 5.0) -> str:
        """Everything written to the terminal since the last call to this
        method, waited for until the stream has gone quiet -- long enough
        for a slow frame to arrive, short enough not to wait out the
        timeout on an idle, already-finished exchange. Delta, not
        cumulative: a caller that drains the settled main menu first must
        not see it again when it checks what a later key press produced.
        """
        start = len(self._buffer)
        deadline = time.monotonic() + timeout
        last_read = time.monotonic()
        received_any = False
        while time.monotonic() < deadline:
            ready, _, _ = select.select([self.master], [], [], 0.1)
            if ready:
                try:
                    chunk = os.read(self.master, 65536)
                except OSError:
                    break
                if not chunk:
                    break
                self._buffer += chunk
                last_read = time.monotonic()
                received_any = True
            elif received_any and time.monotonic() - last_read >= quiet_for:
                # Only a stream that has actually spoken can be judged quiet
                # -- otherwise a slow-starting child (interpreter start-up,
                # first import of the package) looks indistinguishable from
                # one that will never say anything at all.
                break
        return self._buffer[start:].decode("utf-8", errors="replace")

    def close(self) -> None:
        try:
            os.kill(self.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        os.waitpid(self.pid, 0)
        os.close(self.master)


class LiveFeedbackTest(unittest.TestCase):
    """Drives the actual `pegasus.tui.app.run` loop end to end. Any of these
    would fail against the frozen-screen version: nothing ties the busy
    frame to a particular moment, so with the old loop the first thing this
    ever sees for either wait is the finished result, straight after the
    previous screen -- `STARTUP_NEEDLE` and `STATUS_BUSY_NEEDLE` would each
    be entirely absent from the captured output.
    """

    def setUp(self):
        if os.geteuid() == 0:
            self.skipTest("root is not refused by permission bits, and Pegasus refuses to install as root")
        self.directory = tempfile.TemporaryDirectory(dir=_scratch_root())
        self.addCleanup(self.directory.cleanup)
        self.home = Path(self.directory.name)
        self.session = _RealTerminalSession(self.home)
        self.addCleanup(self.session.close)

    def test_a_startup_message_appears_before_the_first_menu(self):
        output = self.session.output_so_far()
        self.assertIn(STARTUP_NEEDLE, output)
        self.assertIn("Pegasus Harness", output)
        self.assertLess(
            output.index(STARTUP_NEEDLE),
            output.index("Pegasus Harness"),
            "the startup message must be drawn before the main menu it precedes",
        )

    def test_choosing_status_shows_what_is_happening_before_the_report(self):
        self.session.output_so_far()  # let the main menu settle first.
        # Install, Update, Upgrade, Configure models, Grant MCP servers, Status and diagnostics.
        self.session.press("jjjjj")
        self.session.press("\r")
        output = self.session.output_so_far()
        self.assertIn(STATUS_BUSY_NEEDLE, output, "no frame named the diagnostics run before it finished")
        self.assertIn(STATUS_RESULT_NEEDLE, output, "the diagnostics report itself never arrived")
        self.assertLess(
            output.index(STATUS_BUSY_NEEDLE),
            output.index(STATUS_RESULT_NEEDLE),
            "the busy frame must be drawn before the result it precedes, not after",
        )

    def test_plain_navigation_never_shows_a_busy_frame(self):
        self.session.output_so_far()
        self.session.press("jkjk")
        output = self.session.output_so_far(quiet_for=0.5)
        self.assertNotIn(STARTUP_NEEDLE, output)
        self.assertNotIn(STATUS_BUSY_NEEDLE, output)


class WordmarkRenderingTest(unittest.TestCase):
    """Proof that the real curses loop draws the wordmark itself, on a real
    terminal, rather than only proving `view.render` would produce it in
    isolation. An installed state is arranged here on purpose -- a throwaway
    home with nothing installed would only exercise the plain-title fallback
    `MenuWordmarkTest` in `test_tui_view` already covers, never the art this
    change adds, which is the one thing this file exists to catch that a
    pure-layer test cannot.
    """

    def setUp(self):
        if os.geteuid() == 0:
            self.skipTest("root is not refused by permission bits, and Pegasus refuses to install as root")
        self.directory = tempfile.TemporaryDirectory(dir=_scratch_root())
        self.addCleanup(self.directory.cleanup)
        self.home = Path(self.directory.name)
        cli_id = available().ids()[0]
        layout = available().get(cli_id).layout(Environment(home=self.home))
        layout.config_dir.mkdir(parents=True, exist_ok=True)
        runtime = cli.Runtime(
            filesystem=PosixFileSystem(),
            home=self.home,
            now="2026-08-14T00:00:00+00:00",
            out=io.StringIO(),
            variables={"PATH": ""},
        )
        cli.install(cli_id, runtime)
        self.session = _RealTerminalSession(self.home)
        self.addCleanup(self.session.close)

    def test_the_main_menu_draws_the_wordmark_once_something_is_installed(self):
        """The two halves of the mark are drawn as separate spans -- a dim
        `PEGASUS` and a plain `HARNESS` -- so a real terminal writes an
        attribute-reset escape between them, and the row no longer appears
        as one contiguous string the way `wordmark.wordmark_rows` builds it.
        Each half's own text, still contiguous within its own span, is what
        proves the real loop drew the art rather than only the pure layer.
        """
        output = self.session.output_so_far()
        pegasus_rows = wordmark.word_rows(wordmark.PEGASUS)
        harness_rows = wordmark.word_rows(wordmark.HARNESS)
        self.assertIn(pegasus_rows[0], output)
        self.assertIn(harness_rows[0], output)


class LocalUpdateNoticeTest(unittest.TestCase):
    """Proof that the real loop shows the local half of the update notice on
    its very first frame, straight off the journal, with the remote check
    (switched off for every pty test -- see `_RealTerminalSession`) never in
    the way of it."""

    def setUp(self):
        if os.geteuid() == 0:
            self.skipTest("root is not refused by permission bits, and Pegasus refuses to install as root")
        self.directory = tempfile.TemporaryDirectory(dir=_scratch_root())
        self.addCleanup(self.directory.cleanup)
        self.home = Path(self.directory.name)
        cli_id = available().ids()[0]
        layout = available().get(cli_id).layout(Environment(home=self.home))
        layout.config_dir.mkdir(parents=True, exist_ok=True)
        filesystem = PosixFileSystem()
        runtime = cli.Runtime(
            filesystem=filesystem,
            home=self.home,
            now="2026-08-14T00:00:00+00:00",
            out=io.StringIO(),
            variables={"PATH": ""},
        )
        cli.install(cli_id, runtime)

        # Backdate the journal's own recorded version, the same fact
        # `session.local_update_notice` reads, so the running binary looks
        # newer than what this installation was made with.
        store = FileJournalStore(filesystem, home=self.home, pegasus_version=cli.pegasus.__version__)
        journal = store.load()
        install = journal_module.install_for(journal, cli_id)
        store.save(journal_module.with_install(journal, replace(install, release={**install.release, "version": "0.0.1"})))

        self.session = _RealTerminalSession(self.home)
        self.addCleanup(self.session.close)

    def test_the_main_menu_names_update_as_the_remedy_for_a_stale_local_install(self):
        output = self.session.output_so_far()
        self.assertIn("0.0.1", output)
        self.assertIn("Update", output)
        # An install is recorded, so the main menu draws the wordmark rather
        # than the plain "Pegasus Harness" title -- this is what proves the
        # menu itself still rendered around the notice, not just the notice.
        self.assertIn("Install", output)
        self.assertIn("Exit", output)


if __name__ == "__main__":
    unittest.main()

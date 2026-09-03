"""Tests for install.sh, the release-asset installer.

Every test drives the real script with `subprocess`, inside a throwaway `HOME` and a
tightly controlled `PATH`, so the tests never touch this machine's actual Python,
Node, OpenCode or Pegasus, and never reach the network. Stubs are small shell
scripts placed on `PATH` ahead of anything real; `--verify` and `--no-run` are used
wherever a scenario would otherwise have to download or launch something for real.

Two things needed workarounds worth documenting up front:

* Stub scripts use `#!/bin/sh` (a fixed, absolute interpreter path) rather than
  `#!/usr/bin/env sh`. `env` needs to look up its argument on `PATH`, and these
  tests intentionally shrink `PATH` down to a stub directory (plus, where needed,
  the small set of real coreutils the script itself calls); an `env`-style shebang
  would fail to resolve inside that shrunk `PATH` for reasons that have nothing to
  do with the behaviour under test.
* The root-refusal test cannot use `sudo` (no such privilege is available to the
  agent running these tests, and none should be requested). Instead it uses
  `unshare --map-root-user --user`, which creates a new user namespace where the
  current unprivileged user is mapped to UID 0 inside that namespace -- a real
  `EUID == 0` process, obtained without any elevated privilege on the host. If
  `unshare` is unavailable in a given environment, that one test is skipped, and
  the reason is stated in the skip message rather than the test silently vanishing.
"""
from __future__ import annotations

import hashlib
import os
import pty
import select
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INSTALL_SH = ROOT / "install.sh"

# Resolved once, from this process's own (unrestricted) PATH, and always invoked
# by absolute path below. Tests deliberately hand the *script itself* a shrunk
# PATH via `env=`, which would otherwise make `bash` unresolvable too -- it is
# install.sh's dependencies that are under test, not bash's own.
BASH = shutil.which("bash") or "/bin/bash"

# The system directories the stubs themselves may legitimately need (`sh`, `sed`,
# `mkdir`, `cat`, and so on, used by install.sh's own plumbing) -- kept narrow on
# purpose so a missing tool fails loudly as "command not found" instead of quietly
# resolving to something real from a wider PATH.
SYSTEM_PATH = "/usr/bin:/bin"


def _write_stub(bin_dir: Path, name: str, body: str) -> None:
    path = bin_dir / name
    path.write_text(f"#!/bin/sh\n{body}\n", encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _snapshot(directory: Path) -> set[str]:
    """Every path under `directory`, as strings, so a before/after diff catches
    a file created anywhere in the tree -- not just at its top level."""
    return {str(p) for p in directory.rglob("*")}


def _make_release_fixture(directory: Path, *, content: bytes = b"#!/bin/sh\necho fake-pegasus\n",
                           corrupt_checksum: bool = False) -> str:
    """Lay out `pegasus` and `pegasus.sha256` in `directory`, and return the
    `file://` URL that stands in for `PEGASUS_INSTALL_BASE_URL` in a test.

    `install.sh` downloads with `curl -fL -o ... "$BASE_URL/pegasus"`; curl
    handles `file://` exactly like an http(s) URL for a GET, so this exercises
    the script's real download-then-verify-then-install code path without any
    of it ever reaching the network. `corrupt_checksum=True` writes a digest
    that does not match `content`, for testing the checksum-mismatch path.
    """
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "pegasus").write_bytes(content)
    digest = hashlib.sha256(content).hexdigest()
    if corrupt_checksum:
        digest = ("0" if digest[0] != "0" else "1") + digest[1:]
    (directory / "pegasus.sha256").write_text(f"{digest}  pegasus\n", encoding="utf-8")
    return f"file://{directory}"


class InstallScriptTestCase(unittest.TestCase):
    """Common throwaway HOME / PATH / marker-directory setup for every test below."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.home = root / "home"
        self.stub_bin = root / "stub-bin"
        self.markers = root / "markers"
        self.home.mkdir()
        self.stub_bin.mkdir()
        self.markers.mkdir()

    def run_install(
        self,
        *args: str,
        path: str | None = None,
        extra_env: dict[str, str] | None = None,
        start_new_session: bool = False,
    ) -> subprocess.CompletedProcess:
        env = {
            "HOME": str(self.home),
            "PATH": path if path is not None else f"{self.stub_bin}:{SYSTEM_PATH}",
        }
        if extra_env:
            env.update(extra_env)
        return subprocess.run(
            [BASH, str(INSTALL_SH), *args],
            env=env,
            cwd=str(ROOT),
            text=True,
            capture_output=True,
            timeout=30,
            # No test needs a real stdin, and a couple deliberately need to
            # prove there is no controlling terminal at all -- DEVNULL keeps
            # every run's stdin closed regardless of whatever tty (or lack
            # of one) this suite itself happens to be running under.
            stdin=subprocess.DEVNULL,
            # `start_new_session=True` (a setsid) additionally detaches the
            # child from any controlling terminal entirely, which a closed
            # stdin alone does not: a piped `curl ... | bash` normally KEEPS
            # the shell's controlling terminal even though its stdin is the
            # pipe -- that gap is exactly what /dev/tty (see confirmar) is
            # for. Only the "no terminal to ask at all" scenario needs this.
            start_new_session=start_new_session,
        )

    def stub(self, name: str, body: str) -> None:
        _write_stub(self.stub_bin, name, body)

    def marker(self, name: str) -> Path:
        return self.markers / name


class HelpTest(InstallScriptTestCase):
    def test_help_exits_zero_and_prints_usage(self):
        """`--help` must work with nothing else on PATH: it is the one thing a
        person is expected to run before any tool is confirmed to exist."""
        result = self.run_install("--help")
        self.assertEqual(result.returncode, 0)
        self.assertIn("install.sh", result.stdout)
        self.assertIn("--verify", result.stdout)


class VerifyWithOnlyOptionalToolsMissingTest(InstallScriptTestCase):
    def test_reports_optional_tools_absent_and_touches_nothing(self):
        """python3 and curl -- the two things install.sh refuses to guess at
        (see VerifyExitCodeMeansViableTest below) -- are stubbed present and
        valid here, so the environment IS viable; only node/opencode/pegasus
        are missing. --verify must exit 0, list all three as things that would
        be installed, and must leave the throwaway HOME byte-for-byte as it
        found it: no directories, no files, not even a `.local/bin` -- verify
        never writes anything, viable or not."""
        self.stub("python3", 'case "$2" in\n  *sys.exit*) exit 0 ;;\n  *) echo "3.12.4" ;;\nesac\n')
        self.stub("curl", "exit 0\n")

        before = _snapshot(self.home)
        result = self.run_install("--verify")
        after = _snapshot(self.home)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Node", result.stdout)
        self.assertIn("OpenCode", result.stdout)
        self.assertIn("pegasus", result.stdout.lower())
        self.assertEqual(before, after)


class VerifyExitCodeMeansViableTest(InstallScriptTestCase):
    """`--verify`'s exit code answers one question: can a real run proceed?

    It is not "did the report get produced" (the report is always produced,
    viable or not) and it does not distinguish "missing" from "present but
    wrong" -- both make the environment equally unable to proceed, so both
    must produce the same non-zero verdict. That is what makes
    `if install.sh --verify; then ...` usable as a precondition check, which
    is the only reason this report needs an exit code at all.
    """

    def test_a_python3_too_old_to_use_is_named_in_the_report_and_exits_nonzero(self):
        """A python3 that answers but reports 3.11 is a settled, unrecoverable
        fact about this environment -- not merely "not installed yet" -- so it
        blocks --verify exactly as an absent python3 does. curl is stubbed
        valid here so the failure is isolated to the Python version."""
        self.stub(
            "python3",
            'case "$2" in\n'
            "  *sys.exit*) exit 1 ;;\n"
            "  *) echo '3.11.4' ;;\n"
            "esac\n",
        )
        self.stub("curl", "exit 0\n")

        result = self.run_install("--verify")

        # Under --verify the report (naming both versions) goes to stdout, the
        # same as every other line of the preflight -- there is no separate
        # "error" stream here, only a report and, at the end, an exit code.
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("3.12", result.stdout)
        self.assertIn("3.11.4", result.stdout)

    def test_everything_absent_is_just_as_unviable_as_present_but_too_old(self):
        """The worse environment (nothing at all present) must not report
        success while the better one (python3 present but too old) reports
        failure. With python3 AND curl both absent, --verify must exit
        non-zero too -- and, since no real run could proceed, must say so
        plainly instead of printing an install plan or a launch line for a
        run that can never happen."""
        before = _snapshot(self.home)
        result = self.run_install("--verify", path=str(self.stub_bin))
        after = _snapshot(self.home)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("no encontrado", result.stdout)  # python3 is still reported, just not fatal alone
        self.assertNotIn("Se instalará", result.stdout)
        self.assertNotIn("lanzado", result.stdout.lower())
        self.assertEqual(before, after)


class VerifyIgnoresNoRunTest(InstallScriptTestCase):
    def test_verify_short_circuits_before_no_run_would_matter(self):
        """--verify never installs anything, with or without --no-run alongside
        it -- verify's own read-only nature makes --no-run a no-op here, which
        is exactly why this is a separate scenario from NoRunActuallyInstallsTest
        below: --no-run alone (this class's sibling) DOES install for real."""
        self.stub("python3", 'case "$2" in\n  *sys.exit*) exit 0 ;;\n  *) echo "3.12.4" ;;\nesac\n')
        self.stub("curl", "exit 0\n")

        result = self.run_install("--verify", "--no-run")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Node", result.stdout)
        self.assertIn("OpenCode", result.stdout)
        self.assertIn("pegasus", result.stdout.lower())
        self.assertFalse(self.marker("opencode-launched").exists())
        self.assertFalse(self.marker("pegasus-launched").exists())


class NoRunActuallyInstallsTest(InstallScriptTestCase):
    """`--no-run` must behave like a real run in every way except the final
    launch -- CRITICAL bug fixed here: it used to skip installing altogether,
    which meant the exact command `INSTALL_BY_AGENT.md` tells an agent to run
    (`--yes --no-run`) silently did nothing, while claiming success and
    claiming something had been installed. These tests drive the real
    download-verify-install code path for the `pegasus` binary through the
    `PEGASUS_INSTALL_BASE_URL` seam, pointed at a local `file://` fixture, so
    the fix is proven against the actual code path and not just its wording.
    Node and OpenCode are always stubbed present in this class specifically so
    that a still-missing seam for *them* can never make a test reach the real
    network -- only the seamed `pegasus` download is exercised for real.
    """

    def _stub_python_node_opencode_present(self):
        """`curl` is deliberately left real (from SYSTEM_PATH), never stubbed,
        in this class: instalar_pegasus's real `curl` calls are exactly what
        these tests drive through the `file://` fixture seam. node/opencode
        are stubbed present so their own `instalar_*` functions never run and
        never get a chance to call the *real* curl against the real network."""
        self.stub("python3", 'case "$2" in\n  *sys.exit*) exit 0 ;;\n  *) echo "3.12.4" ;;\nesac\n')
        self.stub("node", 'echo "v20.11.0"\n')
        self.stub(
            "opencode",
            f'if [ "$1" = "--version" ]; then echo "opencode 1.18.25"; exit 0; fi\n'
            f'touch "{self.marker("opencode-launched")}"\n',
        )

    def _stub_everything_present(self):
        self._stub_python_node_opencode_present()
        self.stub(
            "pegasus",
            f'if [ "$1" = "--version" ] || [ "$1" = "-V" ]; then echo "pegasus 5.12.1"; exit 0; fi\n'
            f'touch "{self.marker("pegasus-launched")}"\n',
        )

    def test_yes_no_run_with_everything_present_reports_nothing_missing_and_would_launch_opencode(self):
        """python3, curl, node, opencode and pegasus are all stubbed present, so
        there is nothing to install; the script must say so and must report it
        would have launched `opencode` -- a ready environment is for working in,
        not for reopening the Pegasus TUI to finish an installation that already
        finished."""
        self._stub_everything_present()

        result = self.run_install("--yes", "--no-run")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("ya está todo instalado", result.stdout)
        self.assertIn("opencode", result.stdout.lower())
        self.assertNotIn("Se habría lanzado: pegasus", result.stdout)
        self.assertFalse(self.marker("opencode-launched").exists())
        self.assertFalse(self.marker("pegasus-launched").exists())

    def test_no_run_with_pegasus_missing_actually_installs_it_and_would_launch_pegasus(self):
        """The critical-bug regression test. pegasus is the only thing missing;
        `--yes --no-run` must actually download it (through the seam, from a
        local fixture -- never the network), verify its checksum, and place it
        at `$BIN_DIR/pegasus` with mode 755 and byte-identical content -- and
        only then must it report it would have launched `pegasus` (not
        `opencode`) instead of actually launching it. Before the fix, none of
        the install steps ran at all under --no-run."""
        self._stub_python_node_opencode_present()
        fixture_dir = Path(self.tmp.name) / "release-fixture"
        content = b"#!/bin/sh\necho fixture-pegasus\n"
        base_url = _make_release_fixture(fixture_dir, content=content)

        result = self.run_install(
            "--yes", "--no-run", extra_env={"PEGASUS_INSTALL_BASE_URL": base_url}
        )

        installed = self.home / ".local" / "bin" / "pegasus"
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(installed.is_file(), result.stdout + result.stderr)
        self.assertEqual(installed.read_bytes(), content)
        self.assertEqual(stat.S_IMODE(installed.stat().st_mode), 0o755)
        self.assertIn("Se habría lanzado: pegasus", result.stdout)
        self.assertIn("se instaló algo nuevo", result.stdout)
        self.assertFalse(self.marker("opencode-launched").exists())
        self.assertFalse(self.marker("pegasus-launched").exists())

    def test_a_real_run_that_execs_pegasus_leaves_no_download_tmpdir_behind(self):
        """`exec` replaces the process image without running pending traps, so
        the `trap ... EXIT` guarding `PEGASUS_TMPDIR` never fires on the code
        path every real install actually takes: one that ends by `exec`ing
        pegasus or opencode, not by returning normally. Before the fix, every
        such run leaked its download directory (the binary and checksum) into
        `$TMPDIR` forever. This drives a REAL run (no `--no-run`, no `--verify`)
        so it actually reaches the `exec`, and checks `$TMPDIR` itself, not
        `PEGASUS_TMPDIR`'s own path (which the trap always cleans up on any
        path that returns instead of exec'ing, so asserting on it would not
        have caught this)."""
        self._stub_python_node_opencode_present()
        fixture_dir = Path(self.tmp.name) / "leak-check-fixture"
        base_url = _make_release_fixture(fixture_dir)
        tmpdir_root = Path(self.tmp.name) / "tmpdir-root"
        tmpdir_root.mkdir()
        before = _snapshot(tmpdir_root)

        result = self.run_install(
            "--yes",
            extra_env={"PEGASUS_INSTALL_BASE_URL": base_url, "TMPDIR": str(tmpdir_root)},
        )

        after = _snapshot(tmpdir_root)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(before, after, "a download directory was left behind under TMPDIR")

    def test_bin_dir_colliding_with_a_regular_file_fails_with_its_own_message(self):
        """`mkdir -p "$BIN_DIR"` used to have no `|| fallar` of its own, unlike
        every other fallible step in this function. If `--bin-dir` names a
        path where a regular file already sits, `mkdir -p` dies with its own
        raw stderr ("mkdir: cannot create directory '...': Not a directory" or
        similar) instead of this script's own friendly, `fallar`-formatted
        message -- still a non-zero exit either way, so this asserts on the
        message prefix, not just the exit code."""
        self._stub_python_node_opencode_present()
        colliding_file = Path(self.tmp.name) / "not-a-directory"
        colliding_file.write_text("this is a file, not a directory\n", encoding="utf-8")

        result = self.run_install("--yes", "--bin-dir", str(colliding_file))

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("ERROR:", result.stderr)
        self.assertIn(str(colliding_file), result.stderr)

    def test_corrupted_checksum_aborts_and_leaves_no_binary(self):
        """A `pegasus.sha256` that does not match the downloaded bytes must
        abort with a non-zero exit and must NOT leave anything at the
        destination -- a half-verified binary is worse than none, since a
        person or agent might otherwise trust it. Runs a real (non-`--no-run`)
        install so this exercises the same code path a genuine install would
        hit, still entirely through the local fixture seam."""
        self._stub_python_node_opencode_present()
        fixture_dir = Path(self.tmp.name) / "corrupt-release-fixture"
        base_url = _make_release_fixture(fixture_dir, corrupt_checksum=True)

        result = self.run_install(
            "--yes", extra_env={"PEGASUS_INSTALL_BASE_URL": base_url}
        )

        installed = self.home / ".local" / "bin" / "pegasus"
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(installed.exists())


class _InstallPtySession:
    """A real `install.sh` process, talking to a real pty, against a throwaway
    home -- the shape `tests/test_tui_pty.py`'s `_RealTerminalSession` uses for
    driving the real TUI binary, carried over here because `confirmar`'s fix
    (read from `/dev/tty`, not stdin) can only be proven true by a process that
    actually HAS a `/dev/tty`: a plain `subprocess.run` with a pipe for stdin,
    however it is dressed up, never gives the child a controlling terminal to
    read from, so it could never have caught the bug this session exists to
    exercise the fix for.
    """

    def __init__(self, *, env: dict[str, str], args: list[str]):
        self.pid, self.master = pty.fork()
        if self.pid == 0:  # pragma: no cover -- runs in the child, a separate process
            os.chdir(str(ROOT))
            os.execve(BASH, [BASH, str(INSTALL_SH), *args], env)
        self._buffer = b""

    def wait_for(self, needle: str, *, timeout: float = 10.0) -> str:
        """Read until `needle` has appeared in the cumulative output, or raise."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if needle in self._buffer.decode("utf-8", errors="replace"):
                return self._buffer.decode("utf-8", errors="replace")
            ready, _, _ = select.select([self.master], [], [], 0.2)
            if ready:
                try:
                    chunk = os.read(self.master, 65536)
                except OSError:
                    break
                if not chunk:
                    break
                self._buffer += chunk
        raise AssertionError(
            f"never saw {needle!r} within {timeout}s; output so far:\n"
            f"{self._buffer.decode('utf-8', errors='replace')}"
        )

    def press(self, text: str) -> None:
        os.write(self.master, text.encode())

    def drain(self, *, quiet_for: float = 0.5, timeout: float = 10.0) -> str:
        """Read until the stream has gone quiet, then return everything seen
        so far (cumulative -- this session is short-lived and only read once
        after the answer is sent, unlike the TUI session's delta reads)."""
        deadline = time.monotonic() + timeout
        last_read = time.monotonic()
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
            elif time.monotonic() - last_read >= quiet_for:
                break
        return self._buffer.decode("utf-8", errors="replace")

    def close(self) -> None:
        try:
            os.kill(self.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        os.waitpid(self.pid, 0)
        os.close(self.master)


class ConfirmationPromptTest(InstallScriptTestCase):
    """Coverage for the interactive path itself -- the path every other test
    in this file skips by passing `--yes`, which is exactly why the critical
    bug (`confirmar` dying silently under the documented `curl | bash`
    one-liner) went uncaught before: nothing exercised a real prompt.
    """

    def _stub_python_node_opencode_present(self):
        self.stub("python3", 'case "$2" in\n  *sys.exit*) exit 0 ;;\n  *) echo "3.12.4" ;;\nesac\n')
        self.stub("node", 'echo "v20.11.0"\n')
        self.stub('opencode', 'if [ "$1" = "--version" ]; then echo "opencode 1.18.25"; exit 0; fi\n')

    def test_piped_with_no_tty_and_no_yes_fails_naming_the_yes_flag(self):
        """The exact shape of the documented one-liner: no `--yes`, and no
        controlling terminal at all (a real `curl ... | bash` keeps the
        shell's controlling terminal even with stdin piped -- see `confirmar`
        -- so this test additionally detaches the session entirely, via
        `start_new_session=True`, to prove the OTHER case: a genuinely
        non-interactive context, such as CI, where there is no terminal to
        fall back to either). Before the fix this exited 1 with no message
        whatsoever; a test asserting only the exit code would still pass
        against that broken version, so this asserts on the message."""
        self._stub_python_node_opencode_present()  # pegasus left absent: something to confirm

        result = self.run_install(start_new_session=True)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("--yes", result.stderr)
        self.assertIn("terminal", result.stderr)
        self.assertNotIn("cancelado", result.stderr)  # never reached the case/fallar this bug used to skip
        self.assertFalse((self.home / ".local" / "bin" / "pegasus").exists())

    def test_answering_the_prompt_over_a_real_pty_proceeds_with_the_install(self):
        """Drives `install.sh --no-run` under a real pty (see `_InstallPtySession`),
        types "y" at the confirmation prompt exactly as a person would, and
        asserts the install actually proceeded -- through the same
        `PEGASUS_INSTALL_BASE_URL` fixture seam the non-interactive tests use,
        so this never reaches the network either."""
        self._stub_python_node_opencode_present()
        fixture_dir = Path(self.tmp.name) / "pty-release-fixture"
        base_url = _make_release_fixture(fixture_dir)

        env = {
            "HOME": str(self.home),
            "PATH": f"{self.stub_bin}:{SYSTEM_PATH}",
            "PEGASUS_INSTALL_BASE_URL": base_url,
            "TERM": "xterm",
        }
        session = _InstallPtySession(env=env, args=["--no-run"])
        self.addCleanup(session.close)

        session.wait_for("[y/N]")
        session.press("y\n")
        output = session.drain(timeout=15.0)

        self.assertIn("Se habría lanzado: pegasus", output)
        installed = self.home / ".local" / "bin" / "pegasus"
        self.assertTrue(installed.is_file(), output)
        self.assertEqual(stat.S_IMODE(installed.stat().st_mode), 0o755)


class LaunchGetsControllingTerminalTest(InstallScriptTestCase):
    """The core bug this fix closes: `lanzar` used to end with a bare
    `exec "$LANZAR"`, which inherits install.sh's own stdin. Under the
    documented `curl ... | bash`, that stdin is the pipe bash already
    drained, not a terminal -- so the launched program (pegasus or opencode,
    both TUIs) printed its usage line and exited immediately instead of
    opening. The fix execs with `< /dev/tty` explicitly, reusing the same
    controlling-terminal check `confirmar` already had.

    Each stub/fixture program records whether ITS OWN stdin is a tty
    (`[ -t 0 ]`) to a marker file -- that is the exact property the bug
    broke, so these assert that property directly rather than a proxy for it
    (such as "some output appeared").
    """

    def test_real_pty_run_execs_freshly_installed_pegasus_with_a_real_terminal(self):
        """Drives a real (non `--no-run`) install over a pty end to end:
        types "y" at the confirmation prompt, installs pegasus for real
        through the `PEGASUS_INSTALL_BASE_URL` fixture seam, and lets the
        script reach its actual `exec pegasus` -- the downloaded "binary"
        then checks its own stdin. Also checks the PATH guidance (see
        ClosingPathGuidanceTest) appears in the transcript BEFORE the exec:
        once exec happens, this script has nothing left to print."""
        self.stub("python3", 'case "$2" in\n  *sys.exit*) exit 0 ;;\n  *) echo "3.12.4" ;;\nesac\n')
        self.stub("node", 'echo "v20.11.0"\n')
        self.stub('opencode', 'if [ "$1" = "--version" ]; then echo "opencode 1.18.25"; exit 0; fi\n')
        marker = self.marker("pegasus-stdin")
        fixture_dir = Path(self.tmp.name) / "launch-pty-fixture"
        content = (
            b'#!/bin/sh\n'
            b'if [ "$1" = "--version" ] || [ "$1" = "-V" ]; then echo "pegasus fake"; exit 0; fi\n'
            b'if [ -t 0 ]; then echo tty > "' + str(marker).encode() + b'"; '
            b'else echo notty > "' + str(marker).encode() + b'"; fi\n'
            b'echo PEGASUS-LAUNCHED-WITH-TERMINAL\n'
        )
        base_url = _make_release_fixture(fixture_dir, content=content)

        env = {
            "HOME": str(self.home),
            "PATH": f"{self.stub_bin}:{SYSTEM_PATH}",
            "PEGASUS_INSTALL_BASE_URL": base_url,
            "TERM": "xterm",
        }
        session = _InstallPtySession(env=env, args=[])
        self.addCleanup(session.close)

        session.wait_for("[y/N]")
        session.press("y\n")
        output = session.wait_for("PEGASUS-LAUNCHED-WITH-TERMINAL", timeout=15.0)

        self.assertTrue(marker.exists(), output)
        self.assertEqual(marker.read_text(encoding="utf-8").strip(), "tty")
        path_idx = output.index("export PATH=")
        launch_idx = output.index("PEGASUS-LAUNCHED-WITH-TERMINAL")
        self.assertLess(path_idx, launch_idx, output)

    def test_real_pty_run_with_nothing_missing_execs_opencode_with_a_real_terminal(self):
        """`opencode` is a TUI too and needs exactly the same treatment. With
        everything already present, `lanzar` execs straight into opencode
        with no confirmation prompt in between."""
        self.stub("python3", 'case "$2" in\n  *sys.exit*) exit 0 ;;\n  *) echo "3.12.4" ;;\nesac\n')
        self.stub("node", 'echo "v20.11.0"\n')
        self.stub(
            "pegasus",
            'if [ "$1" = "--version" ] || [ "$1" = "-V" ]; then echo "pegasus 5.12.1"; exit 0; fi\n',
        )
        marker = self.marker("opencode-stdin")
        self.stub(
            "opencode",
            'if [ "$1" = "--version" ]; then echo "opencode 1.18.25"; exit 0; fi\n'
            f'if [ -t 0 ]; then echo tty > "{marker}"; else echo notty > "{marker}"; fi\n'
            'echo OPENCODE-LAUNCHED-WITH-TERMINAL\n',
        )

        env = {
            "HOME": str(self.home),
            "PATH": f"{self.stub_bin}:{SYSTEM_PATH}",
            "TERM": "xterm",
        }
        session = _InstallPtySession(env=env, args=[])
        self.addCleanup(session.close)

        output = session.wait_for("OPENCODE-LAUNCHED-WITH-TERMINAL", timeout=15.0)

        self.assertTrue(marker.exists(), output)
        self.assertEqual(marker.read_text(encoding="utf-8").strip(), "tty")


class LaunchWithoutTerminalTest(InstallScriptTestCase):
    """The other half of the fix: when there genuinely is no controlling
    terminal to hand the launched program (the CI / fully-detached-session
    case -- a real `curl ... | bash` from an interactive shell normally
    keeps one via `/dev/tty`; this is the case where there truly is none),
    `lanzar` must NOT exec into a program that will just print its usage and
    exit. It must say so plainly, print the exact command to run, and exit 0
    -- the install itself still succeeded."""

    def test_no_controlling_terminal_does_not_exec_and_prints_the_command(self):
        """Mirrors the exact reported bug: a fresh install (pegasus missing)
        run with no controlling terminal at all. Needs --yes since there is
        no terminal to confirm on either."""
        self.stub("python3", 'case "$2" in\n  *sys.exit*) exit 0 ;;\n  *) echo "3.12.4" ;;\nesac\n')
        self.stub("node", 'echo "v20.11.0"\n')
        self.stub('opencode', 'if [ "$1" = "--version" ]; then echo "opencode 1.18.25"; exit 0; fi\n')
        fixture_dir = Path(self.tmp.name) / "no-tty-launch-fixture"
        base_url = _make_release_fixture(fixture_dir)

        result = self.run_install(
            "--yes",
            extra_env={"PEGASUS_INSTALL_BASE_URL": base_url},
            start_new_session=True,
        )

        installed = self.home / ".local" / "bin" / "pegasus"
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(installed.is_file())  # the install itself must still succeed
        self.assertIn("no se lanza pegasus", result.stdout.lower())
        self.assertIn("pegasus", result.stdout)


class ClosingPathGuidanceTest(InstallScriptTestCase):
    """Rewrite of the old mid-run PATH nudge: the guidance now appears at the
    very end (after the launch decision, before any exec), names only the
    directories that actually apply to this run -- the pegasus bin dir
    and/or OpenCode's, only the ones just installed and not already on the
    PATH this run started with -- and hands over one copy-pasteable
    `export PATH=...` line plus why a new session picks both up on its own.
    """

    def _stub_curl_that_fakes_the_opencode_installer(self):
        """Stands in for `curl -fsSL https://opencode.ai/install | bash`:
        emits (to stdout, so the outer pipe's `bash` runs it) a script that
        creates a fake `opencode` binary at $OPENCODE_BIN_DIR, exactly what
        the real official installer does. Any other curl invocation (the
        pegasus download, which passes `-o` and a `file://` URL) is
        delegated to the real `curl` from SYSTEM_PATH so that seam still
        exercises the genuine download-then-verify code path."""
        self.stub(
            "curl",
            "case \"$*\" in\n"
            "  *opencode.ai/install*)\n"
            "    cat <<'EOS'\n"
            'mkdir -p "$HOME/.opencode/bin"\n'
            "cat > \"$HOME/.opencode/bin/opencode\" <<'BIN'\n"
            "#!/bin/sh\n"
            'if [ "$1" = "--version" ]; then echo "opencode 1.18.25"; exit 0; fi\n'
            "BIN\n"
            'chmod +x "$HOME/.opencode/bin/opencode"\n'
            "EOS\n"
            "    ;;\n"
            "  *)\n"
            '    exec /usr/bin/curl "$@"\n'
            "    ;;\n"
            "esac\n",
        )

    def test_both_dirs_named_leading_with_source_profile_and_export_as_fallback(self):
        """`source ~/.profile` (not `~/.bashrc` alone -- that only carries the
        line OpenCode's installer wrote there, not the pegasus bin dir) must
        lead, with the explicit `export PATH=...` offered only as the
        fallback for a shell that doesn't read `~/.profile`. Logging out is
        mentioned only as a background fact, never as the instruction to
        follow -- see the coordinator's refinement: telling someone to close
        their session is heavier than it needs to be."""
        self.stub("python3", 'case "$2" in\n  *sys.exit*) exit 0 ;;\n  *) echo "3.12.4" ;;\nesac\n')
        self.stub("node", 'echo "v20.11.0"\n')
        self._stub_curl_that_fakes_the_opencode_installer()
        fixture_dir = Path(self.tmp.name) / "both-dirs-fixture"
        base_url = _make_release_fixture(fixture_dir)

        result = self.run_install(
            "--yes", "--no-run", extra_env={"PEGASUS_INSTALL_BASE_URL": base_url}
        )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        bin_dir = str(self.home / ".local" / "bin")
        opencode_dir = str(self.home / ".opencode" / "bin")
        self.assertIn(bin_dir, result.stdout)
        self.assertIn(opencode_dir, result.stdout)
        self.assertIn(f'export PATH="{bin_dir}:{opencode_dir}:$PATH"', result.stdout)
        self.assertIn("source ~/.profile", result.stdout)
        self.assertNotIn("cerrá tu sesión", result.stdout.lower())
        self.assertNotIn("cerrar sesión", result.stdout.lower())
        source_idx = result.stdout.index("source ~/.profile")
        export_idx = result.stdout.index("export PATH=")
        self.assertLess(source_idx, export_idx, "source ~/.profile must lead, export PATH is the fallback")
        path_idx = result.stdout.index("=== PATH ===")
        end_idx = result.stdout.index("=== Para terminar ===")
        self.assertLess(path_idx, end_idx)

    def test_only_pegasus_dir_named_when_opencode_was_already_present(self):
        """OpenCode already on PATH (stubbed present) -- only the pegasus bin
        dir, the one this run actually just installed into, is named."""
        self.stub("python3", 'case "$2" in\n  *sys.exit*) exit 0 ;;\n  *) echo "3.12.4" ;;\nesac\n')
        self.stub("node", 'echo "v20.11.0"\n')
        self.stub('opencode', 'if [ "$1" = "--version" ]; then echo "opencode 1.18.25"; exit 0; fi\n')
        fixture_dir = Path(self.tmp.name) / "pegasus-only-fixture"
        base_url = _make_release_fixture(fixture_dir)

        result = self.run_install(
            "--yes", "--no-run", extra_env={"PEGASUS_INSTALL_BASE_URL": base_url}
        )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        bin_dir = str(self.home / ".local" / "bin")
        opencode_dir = str(self.home / ".opencode" / "bin")
        self.assertIn(bin_dir, result.stdout)
        self.assertNotIn(opencode_dir, result.stdout)
        self.assertIn("source ~/.profile", result.stdout)
        self.assertIn(f'export PATH="{bin_dir}:$PATH"', result.stdout)

    def test_custom_bin_dir_falls_back_to_plain_export_without_suggesting_profile(self):
        """`~/.profile`'s snippet only knows how to add `~/.local/bin` -- with
        `--bin-dir` pointing somewhere else, `source ~/.profile` would not
        actually fix anything, so it must not be suggested; the explicit
        `export PATH=...` is the only correct remedy here."""
        self.stub("python3", 'case "$2" in\n  *sys.exit*) exit 0 ;;\n  *) echo "3.12.4" ;;\nesac\n')
        self.stub("node", 'echo "v20.11.0"\n')
        self.stub('opencode', 'if [ "$1" = "--version" ]; then echo "opencode 1.18.25"; exit 0; fi\n')
        fixture_dir = Path(self.tmp.name) / "custom-bin-dir-fixture"
        base_url = _make_release_fixture(fixture_dir)
        custom_bin_dir = Path(self.tmp.name) / "custom-bin"

        result = self.run_install(
            "--yes", "--no-run", "--bin-dir", str(custom_bin_dir),
            extra_env={"PEGASUS_INSTALL_BASE_URL": base_url},
        )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(f'export PATH="{custom_bin_dir}:$PATH"', result.stdout)
        self.assertNotIn("source ~/.profile", result.stdout)

    def test_verify_mode_shows_no_closing_path_guidance(self):
        """--verify never installs anything for real, so there is nothing
        "just installed" to give closing PATH guidance about -- the only
        `=== PATH ===` section left is the pre-existing preflight one."""
        self.stub("python3", 'case "$2" in\n  *sys.exit*) exit 0 ;;\n  *) echo "3.12.4" ;;\nesac\n')
        self.stub("curl", "exit 0\n")

        result = self.run_install("--verify")

        self.assertEqual(result.stdout.count("=== PATH ==="), 1)


class NvmDirectoryParentTest(InstallScriptTestCase):
    """Found by running the script for real against a genuinely empty home.

    `NVM_DIR` follows nvm's own snippet: `$XDG_CONFIG_HOME/nvm` when that
    variable is set, `$HOME/.nvm` otherwise. nvm's installer then creates that
    directory with a plain `mkdir`, not `mkdir -p`, so if the parent does not
    exist yet the install dies with "Failed to create directory". A freshly
    created Linux account -- `useradd` from `/etc/skel`, which is exactly the
    environment this script exists for -- has no `~/.config` until something
    makes one, and nothing had.

    No stub-based test could have caught this: it only appears when the home
    really is empty and the real installer really runs. The contract asserted
    here is therefore narrow and exact -- the parent of `NVM_DIR` exists by
    the time the installer is invoked -- rather than a simulation of nvm.
    """

    def test_the_parent_of_nvm_dir_exists_before_the_installer_runs(self):
        config_home = self.home / ".config"
        self.assertFalse(config_home.exists(), "the point of this test is that it does not exist yet")
        self.stub("python3", 'case "$2" in\n  *sys.exit*) exit 0 ;;\n  *) echo "3.12.4" ;;\nesac\n')
        # Stands in for `curl -o- <nvm url> | bash`: records whether the
        # directory nvm is about to `mkdir` into was already there, then fails
        # the way a broken download would, so the run stops right here.
        self.stub(
            "curl",
            f'if [ -d "{config_home}" ]; then echo existe > "{self.marker("nvm-parent")}";'
            f' else echo ausente > "{self.marker("nvm-parent")}"; fi\n'
            f'exit 1\n',
        )

        self.run_install("--yes", extra_env={"XDG_CONFIG_HOME": str(config_home)})

        self.assertEqual(self.marker("nvm-parent").read_text(encoding="utf-8").strip(), "existe")


class RootRefusalTest(InstallScriptTestCase):
    def test_refuses_to_run_as_root(self):
        """EUID 0 must be refused before anything else runs: files it would then
        create belong to root inside a normal user's home, silently breaking the
        account. `sudo` is not available to (and must not be invoked by) this
        test, so a real EUID-0 process is obtained instead through
        `unshare --map-root-user --user`, a user-namespace trick that needs no
        privilege on the host. If `unshare` itself is unavailable, this test is
        skipped rather than faked -- see the module docstring."""
        if shutil.which("unshare") is None:
            self.skipTest("unshare is not available in this environment; root refusal was not exercised")

        result = subprocess.run(
            [
                "unshare", "--map-root-user", "--user",
                BASH, str(INSTALL_SH), "--verify",
            ],
            env={"HOME": str(self.home), "PATH": f"{self.stub_bin}:{SYSTEM_PATH}"},
            cwd=str(ROOT),
            text=True,
            capture_output=True,
            timeout=30,
        )
        if result.returncode == 127 or "unshare:" in result.stderr:
            self.skipTest(
                f"unshare could not create a user namespace here ({result.stderr.strip()!r}); "
                "root refusal was not exercised"
            )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("root", result.stderr.lower())


class NoStaleReleaseTagTest(unittest.TestCase):
    """No shipped document may hardcode a release tag inside a download URL.

    This is a structural guard, in the spirit of test_engram_convention.py: rather
    than judging whether the prose around a version number is accurate (a moving
    target that would need updating every release, and that this suite cannot
    verify anyway), it checks a fact the docs must never state: a `vX.Y.Z` segment
    baked into a GitHub download URL, or a variable assignment that only exists to
    feed one. That is the exact defect this change fixes -- `INSTALL.md` and
    `INSTALL_BY_AGENT.md` used to hardcode `RELEASE_TAG="v5.9.0"` and go stale the
    moment a new release shipped -- and it is the shape of mistake that is easy to
    reintroduce by example: someone copies a "here is how you'd download tag
    v5.9.0" snippet back in while explaining something else.

    Deliberately NOT flagged: a tag named to illustrate an unrelated command's
    shape rather than to build a download URL. `INSTALL_BY_AGENT.md` discusses
    `tools/build_release_evidence.py --tag v5.9.0` and shows the manifest text
    that command would print (`coincide con v5.9.0 <commit>`) -- neither line
    downloads anything named by that tag; they are examples of a tool's own
    argument and output. The regex below only matches a tag that appears as part
    of a URL path or as the right-hand side of an assignment whose name suggests
    it feeds one (`RELEASE_TAG`, `BASE_URL`, `DOWNLOAD_URL`, ...), which is
    exactly what a download instruction looks like and what a `--tag` argument or
    a printed confirmation line does not.
    """

    DOCS = [
        ROOT / "INSTALL.md",
        ROOT / "INSTALL_BY_AGENT.md",
        ROOT / "docs" / "release-distribution.md",
    ]

    #: A release tag inside something that looks like a download URL: either the
    #: URL itself (`releases/download/v5.9.0/...` or `.../v5.9.0`), or an
    #: assignment to a variable whose name says it feeds a download
    #: (`RELEASE_TAG="v5.9.0"`, `BASE_URL=".../download/v5.9.0"`).
    import re as _re

    TAG_IN_URL = _re.compile(r"releases/download/v\d+\.\d+\.\d+\b")
    TAG_ASSIGNMENT = _re.compile(
        r"\b(?:RELEASE_TAG|BASE_URL|DOWNLOAD_URL)\w*\s*=\s*[\"']?[^\"'\n]*v\d+\.\d+\.\d+"
    )

    def test_no_download_instruction_hardcodes_a_release_tag(self):
        offenders = []
        for path in self.DOCS:
            if not path.exists():
                continue
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if self.TAG_IN_URL.search(line) or self.TAG_ASSIGNMENT.search(line):
                    offenders.append(f"{path.relative_to(ROOT).as_posix()}:{number}: {line.strip()}")
        self.assertEqual(offenders, [])

    def test_the_guard_itself_would_catch_the_original_bug(self):
        """Sanity-check the regex against the exact line that used to ship, so a
        future edit to the pattern cannot silently stop catching the bug it
        exists for."""
        self.assertTrue(self.TAG_ASSIGNMENT.search('RELEASE_TAG="v5.9.0"'))
        self.assertTrue(
            self.TAG_IN_URL.search(
                "https://github.com/balerdis/pegasus-harness/releases/download/v5.9.0/pegasus"
            )
        )
        # And the illustrations this guard must leave alone:
        self.assertFalse(
            self.TAG_IN_URL.search("tools/build_release_evidence.py --tag v5.9.0")
            or self.TAG_ASSIGNMENT.search("tools/build_release_evidence.py --tag v5.9.0")
        )
        self.assertFalse(
            self.TAG_IN_URL.search("release-manifest.json: coincide con v5.9.0 57d58ccd2d942043a32a20f7696c48fc075e6e5d")
            or self.TAG_ASSIGNMENT.search(
                "release-manifest.json: coincide con v5.9.0 57d58ccd2d942043a32a20f7696c48fc075e6e5d"
            )
        )


if __name__ == "__main__":
    unittest.main()

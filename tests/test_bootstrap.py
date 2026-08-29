"""Provisioning the private venv: pure arithmetic, a fake provisioner, and the PATH check."""
from __future__ import annotations

import subprocess
import unittest
from pathlib import Path

from fakes import FakeVenvProvisioner
from pegasus.core import bootstrap
from pegasus.infra.fs_posix import PosixFileSystem
from pegasus.ports.venv_provisioner import VenvProvisionerError

DATA_DIR = Path("/home/probe/.local/share/pegasus-harness")
BIN_DIR = Path("/home/probe/.local/bin")


class VenvDirTest(unittest.TestCase):
    def test_venv_dir_sits_inside_the_data_dir(self):
        self.assertEqual(bootstrap.venv_dir(DATA_DIR), DATA_DIR / "venv")


class ProvisionTest(unittest.TestCase):
    def test_provision_creates_then_installs_in_order(self):
        provisioner = FakeVenvProvisioner()
        venv = DATA_DIR / "venv"
        requirements = Path("/repo/requirements.txt")
        source = Path("/repo")
        bootstrap.provision(provisioner, venv=venv, requirements=requirements, source=source)
        self.assertEqual(provisioner.created, [venv])
        self.assertEqual(provisioner.installed, [(venv, requirements, source)])

    def test_provision_is_idempotent_across_reruns(self):
        provisioner = FakeVenvProvisioner()
        venv = DATA_DIR / "venv"
        requirements = Path("/repo/requirements.txt")
        source = Path("/repo")
        bootstrap.provision(provisioner, venv=venv, requirements=requirements, source=source)
        bootstrap.provision(provisioner, venv=venv, requirements=requirements, source=source)
        self.assertEqual(provisioner.created, [venv, venv])
        self.assertEqual(len(provisioner.installed), 2)

    def test_provision_never_reaches_install_when_create_fails(self):
        venv = DATA_DIR / "venv"
        provisioner = FakeVenvProvisioner(fail_create={venv})
        with self.assertRaises(VenvProvisionerError):
            bootstrap.provision(
                provisioner, venv=venv, requirements=Path("/repo/requirements.txt"), source=Path("/repo")
            )
        self.assertEqual(provisioner.installed, [])

    def test_provision_propagates_an_install_failure(self):
        venv = DATA_DIR / "venv"
        provisioner = FakeVenvProvisioner(fail_install={venv})
        with self.assertRaises(VenvProvisionerError):
            bootstrap.provision(
                provisioner, venv=venv, requirements=Path("/repo/requirements.txt"), source=Path("/repo")
            )


class PathWarningTest(unittest.TestCase):
    def test_no_warning_when_bin_dir_is_on_path(self):
        self.assertIsNone(bootstrap.path_warning(BIN_DIR, f"/usr/bin:{BIN_DIR}:/bin"))

    def test_warns_when_bin_dir_is_absent_from_path(self):
        warning = bootstrap.path_warning(BIN_DIR, "/usr/bin:/bin")
        self.assertIsNotNone(warning)
        self.assertIn(str(BIN_DIR), warning)

    def test_warns_on_an_empty_path(self):
        self.assertIsNotNone(bootstrap.path_warning(BIN_DIR, ""))

    def test_does_not_match_a_longer_sibling_directory_by_substring(self):
        """`/home/x/.local/binary` on PATH must never satisfy `/home/x/.local/bin`."""
        warning = bootstrap.path_warning(BIN_DIR, str(BIN_DIR) + "ary")
        self.assertIsNotNone(warning)


if __name__ == "__main__":
    unittest.main()


class ShimAgreesWithThePortTest(unittest.TestCase):
    """The shim resolves the venv by hand, and this is what keeps it honest.

    It cannot ask the port where the venv lives: it runs before there is an
    interpreter to import Pegasus with, so it mirrors the POSIX branch of
    `data_dir` in shell. A comment asking for that to be kept in sync is
    exactly the kind of thing that stops being true quietly, so instead the
    two answers are compared directly — the shim is run, and what it resolves
    has to be what the port would have said.
    """

    SHIM = Path(__file__).resolve().parents[1] / "bin" / "pegasus"

    def resolved_by_the_shim(self, variables: dict[str, str], home: Path) -> Path:
        """What the shim would exec, without letting it exec anything.

        The shim's last line is the only part that needs a real venv; every
        line before it is the arithmetic under test. Running it with the
        interpreter check guaranteed to fail makes it report the path it
        computed and stop there.
        """
        finished = subprocess.run(
            ["sh", str(self.SHIM)],
            capture_output=True,
            text=True,
            env={"HOME": str(home), "PATH": "/usr/bin:/bin", **variables},
        )
        self.assertEqual(finished.returncode, 1, finished.stderr)
        prefix, _, rest = finished.stderr.partition("no private virtual environment at ")
        return Path(rest.split(" --")[0])

    def test_the_shim_and_the_port_name_the_same_venv_without_an_override(self):
        home = Path("/nonexistent/probe-home")
        expected = PosixFileSystem().data_dir(home) / "venv"
        self.assertEqual(self.resolved_by_the_shim({}, home), expected)

    def test_the_shim_and_the_port_agree_when_the_data_directory_is_overridden(self):
        home = Path("/nonexistent/probe-home")
        override = "/nonexistent/elsewhere"
        expected = PosixFileSystem({"XDG_DATA_HOME": override}).data_dir(home) / "venv"
        self.assertEqual(self.resolved_by_the_shim({"XDG_DATA_HOME": override}, home), expected)

    def test_the_shim_ignores_a_relative_override_exactly_as_the_port_does(self):
        home = Path("/nonexistent/probe-home")
        expected = PosixFileSystem({"XDG_DATA_HOME": "somewhere"}).data_dir(home) / "venv"
        self.assertEqual(self.resolved_by_the_shim({"XDG_DATA_HOME": "somewhere"}, home), expected)

"""Fetching, verifying and placing a `download`- or `npm`-distributed MCP server."""
from __future__ import annotations

import io
import json
import tarfile
import unittest
from pathlib import Path, PurePosixPath

from fakes import FakeDownloader, FakeFileSystem, FakeNpmInstaller

from pegasus.core import dependencies
from pegasus.core import ownership
from pegasus.core.content import Distribution, Mcp

DEPENDENCIES_DIR = Path("/home/probe/.local/share/pegasus-harness/mcp")
AT = "2026-08-14T00:00:00+00:00"
INTEGRITY = "sha512-" + "a" * 86 + "=="


def make_archive(entries: dict[str, bytes], *, symlinks: dict[str, str] | None = None) -> bytes:
    """A gzip-compressed tar built from ``entries``, for a test to fetch as bytes.

    ``symlinks`` adds a symlink member, name -> target, when the escaping
    case under test needs a link rather than a plain path.
    """
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        for name, content in entries.items():
            info = tarfile.TarInfo(name=name)
            info.size = len(content)
            archive.addfile(info, io.BytesIO(content))
        for name, target in (symlinks or {}).items():
            info = tarfile.TarInfo(name=name)
            info.type = tarfile.SYMTYPE
            info.linkname = target
            archive.addfile(info)
    return buffer.getvalue()


def download_server(**overrides) -> Mcp:
    content = overrides.pop("content", b"the real binary bytes")
    fields = dict(
        name="probe",
        description="d",
        body="convention",
        distribution=Distribution.DOWNLOAD,
        endpoint="https://example.test/releases/probe-linux-x64",
        source=PurePosixPath("mcp/probe.md"),
        version="1.2.3",
        checksum=ownership.digest_of_bytes(content),
    )
    fields.update(overrides)
    return Mcp(**fields), content


class TargetPathTest(unittest.TestCase):
    def test_the_target_directory_is_named_by_id_and_version(self):
        item, _ = download_server()
        self.assertEqual(
            dependencies.target_dir(DEPENDENCIES_DIR, item), DEPENDENCIES_DIR / "probe" / "1.2.3"
        )

    def test_the_binary_lands_under_the_target_directory_named_by_the_endpoint(self):
        item, _ = download_server()
        self.assertEqual(
            dependencies.binary_path(DEPENDENCIES_DIR, item),
            DEPENDENCIES_DIR / "probe" / "1.2.3" / "probe-linux-x64",
        )


class MaterializeTest(unittest.TestCase):
    def setUp(self):
        self.filesystem = FakeFileSystem()

    def materialize(self, item, downloader):
        return dependencies.materialize(self.filesystem, downloader, DEPENDENCIES_DIR, item, at=AT)

    def test_a_verified_download_is_placed_at_the_binary_path(self):
        item, content = download_server()
        downloader = FakeDownloader({item.endpoint: content})
        self.materialize(item, downloader)
        target = dependencies.binary_path(DEPENDENCIES_DIR, item)
        self.assertEqual(self.filesystem.files[target], content)

    def test_the_placed_binary_is_executable(self):
        item, content = download_server()
        downloader = FakeDownloader({item.endpoint: content})
        self.materialize(item, downloader)
        target = dependencies.binary_path(DEPENDENCIES_DIR, item)
        self.assertEqual(self.filesystem.modes[target], self.filesystem.mode_for(executable=True))

    def test_the_record_identifies_what_was_fetched(self):
        item, content = download_server()
        downloader = FakeDownloader({item.endpoint: content})
        record = self.materialize(item, downloader)
        self.assertEqual(record.id, "dependency:probe")
        self.assertEqual(record.kind, "dependency-tree")
        self.assertEqual(record.target, dependencies.target_dir(DEPENDENCIES_DIR, item))
        self.assertEqual(record.after_digest, item.checksum)

    def test_the_record_also_names_the_program_a_cli_would_run_and_its_digest(self):
        """A bare binary *is* the program, so its digest is read back from the
        very bytes `write_atomic` placed -- proof this is not just repeating
        `item.checksum` under a new name.
        """
        item, content = download_server()
        downloader = FakeDownloader({item.endpoint: content})
        record = self.materialize(item, downloader)
        self.assertEqual(record.program_relpath, "probe-linux-x64")
        self.assertEqual(record.program_digest, ownership.digest_of_bytes(content))

    def test_a_checksum_mismatch_is_refused_naming_expected_and_arrived(self):
        item, _ = download_server()
        wrong = b"not the bytes anyone pinned"
        downloader = FakeDownloader({item.endpoint: wrong})
        with self.assertRaises(dependencies.MaterializeError) as raised:
            self.materialize(item, downloader)
        message = str(raised.exception)
        self.assertIn(item.checksum, message)
        self.assertIn(ownership.digest_of_bytes(wrong), message)

    def test_a_checksum_mismatch_leaves_nothing_on_disk(self):
        item, _ = download_server()
        downloader = FakeDownloader({item.endpoint: b"not the bytes anyone pinned"})
        with self.assertRaises(dependencies.MaterializeError):
            self.materialize(item, downloader)
        self.assertEqual(self.filesystem.files, {})
        self.assertEqual(self.filesystem.writes, [])

    def test_a_fetch_failure_names_the_server_and_the_url(self):
        item, _ = download_server()
        downloader = FakeDownloader({})  # nothing registered for item.endpoint
        with self.assertRaises(dependencies.MaterializeError) as raised:
            self.materialize(item, downloader)
        self.assertIn(item.name, str(raised.exception))
        self.assertIn(item.endpoint, str(raised.exception))

    def test_a_remote_server_is_refused_rather_than_fetched(self):
        item, content = download_server(distribution=Distribution.REMOTE, version=None, checksum=None)
        with self.assertRaises(dependencies.MaterializeError):
            self.materialize(item, FakeDownloader({item.endpoint: content}))


class MaterializeProgressTest(unittest.TestCase):
    """`materialize`'s own `on_progress` is nothing but a pass-through to
    `downloader.fetch` -- proving that pass-through is this module's whole
    job here, since the byte-counting itself is `HttpDownloader`'s.
    """

    def setUp(self):
        self.filesystem = FakeFileSystem()

    def test_omitting_on_progress_changes_nothing(self):
        item, content = download_server()
        downloader = FakeDownloader({item.endpoint: content})
        dependencies.materialize(self.filesystem, downloader, DEPENDENCIES_DIR, item, at=AT)
        target = dependencies.binary_path(DEPENDENCIES_DIR, item)
        self.assertEqual(self.filesystem.files[target], content)

    def test_on_progress_is_forwarded_to_the_downloader(self):
        item, content = download_server()
        downloader = FakeDownloader({item.endpoint: content}, chunk_reports=[(4, 10), (10, 10)])
        observed: list[tuple[int, int | None]] = []
        dependencies.materialize(
            self.filesystem, downloader, DEPENDENCIES_DIR, item, at=AT,
            on_progress=lambda done, total: observed.append((done, total)),
        )
        self.assertEqual(observed, [(4, 10), (10, 10)])


def archive_server(**overrides) -> tuple[Mcp, bytes]:
    entries = overrides.pop("entries", {"probe": b"the real program bytes", "README.md": b"read me"})
    archive = make_archive(entries, symlinks=overrides.pop("symlinks", None))
    fields = dict(
        name="probe",
        description="d",
        body="convention",
        distribution=Distribution.DOWNLOAD,
        endpoint="https://example.test/releases/probe-linux-x64.tar.gz",
        source=PurePosixPath("mcp/probe.md"),
        version="1.2.3",
        checksum=ownership.digest_of_bytes(archive),
        archive_members=tuple(entries) if "archive_members" not in overrides else overrides.pop("archive_members"),
        archive_executable="probe",
    )
    fields.update(overrides)
    return Mcp(**fields), archive


class MaterializeArchiveTest(unittest.TestCase):
    def setUp(self):
        self.filesystem = FakeFileSystem()

    def materialize(self, item, downloader):
        return dependencies.materialize(self.filesystem, downloader, DEPENDENCIES_DIR, item, at=AT)

    def test_every_declared_member_is_placed_under_the_target_directory(self):
        item, archive = archive_server()
        downloader = FakeDownloader({item.endpoint: archive})
        self.materialize(item, downloader)
        target = dependencies.target_dir(DEPENDENCIES_DIR, item)
        self.assertEqual(self.filesystem.files[target / "probe"], b"the real program bytes")
        self.assertEqual(self.filesystem.files[target / "README.md"], b"read me")

    def test_only_the_declared_executable_member_is_executable(self):
        item, archive = archive_server()
        downloader = FakeDownloader({item.endpoint: archive})
        self.materialize(item, downloader)
        target = dependencies.target_dir(DEPENDENCIES_DIR, item)
        self.assertEqual(self.filesystem.modes[target / "probe"], self.filesystem.mode_for(executable=True))
        self.assertEqual(
            self.filesystem.modes[target / "README.md"], self.filesystem.mode_for(executable=False)
        )

    def test_the_record_still_identifies_the_whole_tree_by_the_archives_own_digest(self):
        item, archive = archive_server()
        record = self.materialize(item, FakeDownloader({item.endpoint: archive}))
        self.assertEqual(record.id, "dependency:probe")
        self.assertEqual(record.kind, "dependency-tree")
        self.assertEqual(record.target, dependencies.target_dir(DEPENDENCIES_DIR, item))
        self.assertEqual(record.after_digest, item.checksum)

    def test_the_record_names_the_declared_executable_member_not_the_archive(self):
        """The archive's own digest (`after_digest`) identifies the whole
        tarball; the program a CLI's configuration actually runs is one
        member inside it, whose bytes hash to something else entirely --
        proof the two are never conflated.
        """
        item, archive = archive_server()
        record = self.materialize(item, FakeDownloader({item.endpoint: archive}))
        self.assertEqual(record.program_relpath, "probe")
        self.assertEqual(record.program_digest, ownership.digest_of_bytes(b"the real program bytes"))
        self.assertNotEqual(record.program_digest, record.after_digest)

    def test_a_checksum_mismatch_is_refused_before_the_archive_is_ever_opened(self):
        item, _ = archive_server()
        downloader = FakeDownloader({item.endpoint: b"not the archive anyone pinned"})
        with self.assertRaises(dependencies.MaterializeError):
            self.materialize(item, downloader)
        self.assertEqual(self.filesystem.files, {})

    def test_a_declared_member_missing_from_the_archive_is_refused_naming_it(self):
        item, archive = archive_server(archive_members=("probe", "README.md", "ghost"))
        with self.assertRaises(dependencies.MaterializeError) as raised:
            self.materialize(item, FakeDownloader({item.endpoint: archive}))
        self.assertIn("ghost", str(raised.exception))
        self.assertEqual(self.filesystem.files, {})

    def test_a_member_whose_symlink_escapes_the_target_directory_is_refused(self):
        """The archive's checksum matches -- these are the exact bytes that
        were pinned -- but one member is a symlink pointing outside the
        directory it would be extracted into. Verifying the digest proves the
        bytes are the ones that were pinned; it says nothing about whether a
        member inside them is safe to place on disk, which is what this
        proves is checked separately.
        """
        item, archive = archive_server(
            entries={"README.md": b"read me"},
            symlinks={"probe": "../../../../etc/passwd"},
            archive_members=("probe", "README.md"),
        )
        with self.assertRaises(dependencies.MaterializeError) as raised:
            self.materialize(item, FakeDownloader({item.endpoint: archive}))
        self.assertIn("probe", str(raised.exception))
        self.assertEqual(self.filesystem.files, {})
        self.assertEqual(self.filesystem.writes, [])

    def test_a_write_failure_partway_through_leaves_nothing_behind(self):
        item, archive = archive_server()
        target = dependencies.target_dir(DEPENDENCIES_DIR, item)
        self.filesystem.fail_always.add(target / "README.md")
        with self.assertRaises(dependencies.MaterializeError):
            self.materialize(item, FakeDownloader({item.endpoint: archive}))
        self.assertEqual(self.filesystem.files, {})
        self.assertFalse(
            any(target in candidate.parents or candidate == target for candidate in self.filesystem.directories)
        )


#: A real lockfile pins more than the top package alone -- ``probe-core`` here
#: stands in for the driver a synthesized, single-package lockfile could never
#: have named, which is exactly the gap `materialize_npm` must not reintroduce.
NPM_LOCKFILE = (
    b'{"name": "pegasus-probe", "lockfileVersion": 3, "requires": true, "packages": {'
    b'"": {"name": "pegasus-probe", "dependencies": {"probe-mcp": "1.2.3"}}, '
    b'"node_modules/probe-mcp": {"version": "1.2.3", '
    b'"resolved": "https://registry.npmjs.org/probe-mcp/-/probe-mcp-1.2.3.tgz", '
    b'"integrity": "' + INTEGRITY.encode("ascii") + b'", '
    b'"dependencies": {"probe-core": "9.9.9"}}, '
    b'"node_modules/probe-core": {"version": "9.9.9", '
    b'"resolved": "https://registry.npmjs.org/probe-core/-/probe-core-9.9.9.tgz", '
    b'"integrity": "sha512-' + (b"c" * 86) + b'=="}}}'
)


def npm_server(**overrides) -> Mcp:
    fields = dict(
        name="probe",
        description="d",
        body="convention",
        distribution=Distribution.NPM,
        endpoint="https://registry.npmjs.org/probe-mcp/-/probe-mcp-1.2.3.tgz",
        source=PurePosixPath("mcp/probe.md"),
        version="1.2.3",
        package="probe-mcp",
        integrity=INTEGRITY,
        entry="cli.js",
        npm_lockfile=NPM_LOCKFILE,
        npm_package_name="pegasus-probe",
    )
    fields.update(overrides)
    return Mcp(**fields)


class NpmScriptPathTest(unittest.TestCase):
    def test_the_script_lands_under_node_modules_by_package_and_entry(self):
        cases = {
            "probe-mcp": "node_modules/probe-mcp/cli.js",
            "@playwright/mcp": "node_modules/@playwright/mcp/cli.js",
        }
        for package, expected in cases.items():
            with self.subTest(package=package):
                item = npm_server(package=package)
                self.assertEqual(
                    dependencies.npm_script_path(DEPENDENCIES_DIR, item),
                    DEPENDENCIES_DIR / "probe" / "1.2.3" / expected,
                )


class MaterializeNpmTest(unittest.TestCase):
    def setUp(self):
        self.filesystem = FakeFileSystem()

    def materialize(self, item, installer, *, node_present=True):
        return dependencies.materialize_npm(
            self.filesystem, installer, DEPENDENCIES_DIR, item, node_present=node_present, at=AT
        )

    def test_a_successful_install_runs_npm_ci_in_the_target_directory(self):
        item = npm_server()
        installer = FakeNpmInstaller()
        self.materialize(item, installer)
        target = dependencies.target_dir(DEPENDENCIES_DIR, item)
        self.assertEqual(installer.calls, [target])

    def test_the_lockfile_is_written_verbatim_from_the_descriptor(self):
        item = npm_server()
        installer = FakeNpmInstaller()
        self.materialize(item, installer)
        target = dependencies.target_dir(DEPENDENCIES_DIR, item)
        self.assertEqual(self.filesystem.files[target / "package-lock.json"], item.npm_lockfile)

    def test_the_written_lockfile_still_pins_a_package_the_descriptor_never_names(self):
        """`probe-core` is a transitive dependency, not anything `npm_server`
        declares as its own `package` -- proof this is the real, shipped
        lockfile and not one synthesized from the descriptor's own fields,
        which could only ever have named the one package it does declare.
        """
        item = npm_server()
        installer = FakeNpmInstaller()
        self.materialize(item, installer)
        target = dependencies.target_dir(DEPENDENCIES_DIR, item)
        lock = self.filesystem.files[target / "package-lock.json"].decode("utf-8")
        self.assertIn("probe-core", lock)

    def test_a_missing_lockfile_is_refused_before_anything_is_written(self):
        item = npm_server(npm_lockfile=None)
        with self.assertRaises(dependencies.MaterializeError) as raised:
            self.materialize(item, FakeNpmInstaller())
        self.assertIn("lockfile", str(raised.exception).lower())
        self.assertEqual(self.filesystem.files, {})
        self.assertEqual(self.filesystem.writes, [])

    def test_a_missing_package_name_is_refused_before_anything_is_written(self):
        item = npm_server(npm_package_name=None)
        with self.assertRaises(dependencies.MaterializeError) as raised:
            self.materialize(item, FakeNpmInstaller())
        self.assertIn("lockfile", str(raised.exception).lower())
        self.assertEqual(self.filesystem.files, {})
        self.assertEqual(self.filesystem.writes, [])

    def test_package_json_names_itself_after_the_lockfiles_own_name_not_the_descriptors_stem(self):
        """The descriptor's file stem (``item.name``, here ``probe``) and the
        real, npm-generated lockfile's own root name need not agree -- the
        shipped `playwright.md` descriptor and its `pegasus-playwright-mcp`
        lockfile are exactly such a pair. `package.json`'s own `name` has to
        come from the lockfile `npm ci` will check it against, not from the
        stem, or the two would disagree on any descriptor whose file is not
        named after its lockfile's own package.
        """
        item = npm_server(npm_package_name="totally-different-from-the-stem")
        installer = FakeNpmInstaller()
        self.materialize(item, installer)
        target = dependencies.target_dir(DEPENDENCIES_DIR, item)
        manifest = json.loads(self.filesystem.files[target / "package.json"])
        self.assertEqual(manifest["name"], "totally-different-from-the-stem")

    def test_the_record_identifies_what_was_installed(self):
        item = npm_server()
        record = self.materialize(item, FakeNpmInstaller())
        self.assertEqual(record.id, "dependency:probe")
        self.assertEqual(record.kind, "dependency-tree")
        self.assertEqual(record.target, dependencies.target_dir(DEPENDENCIES_DIR, item))
        self.assertEqual(record.after_digest, item.integrity)

    def test_a_fake_installer_that_writes_nothing_leaves_the_program_unrecorded(self):
        """`FakeNpmInstaller` never touches the filesystem -- real `npm ci`
        would have written the entry script this reads back, so with the
        fake there is nothing there to read. `materialize_npm` must not
        raise over that; it is `npm ci`'s own write being absent, not this
        module's, and the fields it cannot fill are exactly what a journal
        written before they existed also carries.
        """
        item = npm_server()
        record = self.materialize(item, FakeNpmInstaller())
        self.assertIsNone(record.program_relpath)
        self.assertIsNone(record.program_digest)

    def test_the_record_names_the_entry_script_when_it_is_there_to_read(self):
        """Standing in for what a real `npm ci` would have placed: the entry
        script written directly into the fake filesystem, at exactly the path
        `npm_script_path` names, before `materialize_npm` ever reads it back.
        """
        item = npm_server()
        script = b"#!/usr/bin/env node\nconsole.log('probe');\n"
        self.filesystem.write_atomic(dependencies.npm_script_path(DEPENDENCIES_DIR, item), script)
        record = self.materialize(item, FakeNpmInstaller())
        self.assertEqual(record.program_relpath, "node_modules/probe-mcp/cli.js")
        self.assertEqual(record.program_digest, ownership.digest_of_bytes(script))

    def test_a_missing_node_is_refused_before_anything_is_written(self):
        item = npm_server()
        with self.assertRaises(dependencies.MaterializeError) as raised:
            self.materialize(item, FakeNpmInstaller(), node_present=False)
        self.assertIn("node", str(raised.exception).lower())
        self.assertEqual(self.filesystem.files, {})
        self.assertEqual(self.filesystem.writes, [])

    def test_a_failed_install_leaves_nothing_on_disk(self):
        item = npm_server()
        target = dependencies.target_dir(DEPENDENCIES_DIR, item)
        installer = FakeNpmInstaller(failures={target: "registry unreachable"})
        with self.assertRaises(dependencies.MaterializeError) as raised:
            self.materialize(item, installer)
        self.assertIn("registry unreachable", str(raised.exception))
        self.assertEqual(self.filesystem.files, {})
        self.assertFalse(
            any(target in candidate.parents or candidate == target for candidate in self.filesystem.directories)
        )

    def test_a_remote_server_is_refused_rather_than_installed(self):
        item = npm_server(distribution=Distribution.REMOTE, version=None, package=None, integrity=None, entry=None)
        with self.assertRaises(dependencies.MaterializeError):
            self.materialize(item, FakeNpmInstaller())

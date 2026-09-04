"""`on_progress`: the seam a caller uses to render a real progress bar.

`cli.install` is the only place a total can be known -- it is the one that
holds the plan, the dependency set and the retirement set together -- so this
is where the arithmetic is proven. The planner-level notification itself
(once per `Step`, once per retired record) is proven in `test_planner.py`;
this module only proves the composition: that the total spans every
countable phase, that `done` is monotonic and ends at the total, and that a
dry run or an omitted callback change nothing.

Real disk and a real download path, same discipline as `test_cli_downloads.py`
-- this suite refuses the network structurally (see `no_network.py`), so a
`download`-distributed server is proven against a descriptor built by the
test itself and a `FakeDownloader`.
"""
from __future__ import annotations

import io
import unittest
from pathlib import PurePosixPath
from unittest.mock import patch

from fakes import FakeDownloader

from pegasus import cli
from pegasus.adapters import available
from pegasus.core import ownership
from pegasus.core.content import Content, Distribution, Mcp
from pegasus.core.types import Environment
from real_home import RealHomeTestCase as _RealHomeTestCase

AT = "2026-08-14T00:00:00+00:00"
CLI = available().ids()[0]
NO_BINARY = {"PATH": ""}
BYTES = b"the real released binary"
CHECKSUM = ownership.digest_of_bytes(BYTES)

PROBE = Mcp(
    name="probe",
    description="A downloaded probe server",
    body="Convention body.",
    distribution=Distribution.DOWNLOAD,
    endpoint="https://example.test/releases/probe-linux-x64",
    source=PurePosixPath("mcp/probe.md"),
    version="1.2.3",
    checksum=CHECKSUM,
)
PROBE_CONTENT = Content(mcp=(PROBE,))


class RealHomeTestCase(_RealHomeTestCase):
    def runtime(self, downloader=None) -> cli.Runtime:
        return cli.Runtime(
            filesystem=self.filesystem,
            home=self.home,
            now=AT,
            out=io.StringIO(),
            variables=NO_BINARY,
            downloader=downloader or FakeDownloader({PROBE.endpoint: BYTES}),
        )

    def environment(self) -> Environment:
        return Environment(home=self.home, data_dir=self.filesystem.data_dir(self.home))

    def layout(self):
        return available().get(CLI).layout(self.environment())

    def present(self) -> None:
        self.layout().config_dir.mkdir(parents=True, exist_ok=True)


class PlainInstallProgressTest(RealHomeTestCase):
    """No MCP server named -- nothing to fetch, nothing to retire."""

    def test_a_dry_run_emits_nothing(self):
        self.present()
        events = []
        cli.install(CLI, self.runtime(), dry_run=True, on_progress=events.append)
        self.assertEqual(events, [])

    def test_on_progress_none_is_the_default_and_changes_nothing(self):
        self.present()
        report = cli.install(CLI, self.runtime())
        self.assertEqual(report["status"], "installed")

    def test_the_first_emission_carries_the_real_total_before_any_unit_is_done(self):
        self.present()
        events = []
        cli.install(CLI, self.runtime(), on_progress=events.append)
        self.assertTrue(events)
        first = events[0]
        self.assertEqual(first.done, 0)
        self.assertGreater(first.total, 0)

    def test_done_is_monotonic_and_the_last_emission_reaches_the_total(self):
        self.present()
        events = []
        cli.install(CLI, self.runtime(), on_progress=events.append)
        total = events[0].total
        # Every emission increments `done` by exactly one unit of work, so the
        # sequence is the whole range from zero to the total, in order.
        self.assertEqual([event.done for event in events], list(range(total + 1)))
        self.assertEqual(events[-1].done, total)
        self.assertTrue(all(event.total == total for event in events))

    def test_the_total_accounts_for_the_snapshot_and_the_journal_write(self):
        """A plain install fetches nothing and retires nothing, so the total
        is exactly the placement count plus the two fixed units."""
        self.present()
        dry = cli.install(CLI, self.runtime(), dry_run=True)
        placements = len(dry["created"]) + len(dry["updated"])
        events = []
        cli.install(CLI, self.runtime(), on_progress=events.append)
        self.assertEqual(events[0].total, placements + 2)

    def test_phases_used_are_the_documented_ones(self):
        self.present()
        events = []
        cli.install(CLI, self.runtime(), on_progress=events.append)
        seen_phases = {event.phase for event in events[1:]}  # events[0] is the announcement
        self.assertLessEqual(seen_phases, {"snapshot", "artifacts", "journal"})

    def test_progress_fraction_and_percent_reflect_done_over_total(self):
        self.present()
        events = []
        cli.install(CLI, self.runtime(), on_progress=events.append)
        halfway = events[len(events) // 2]
        self.assertAlmostEqual(halfway.fraction, halfway.done / halfway.total)
        self.assertAlmostEqual(halfway.percent, 100 * halfway.done / halfway.total)


@patch("pegasus.core.content.load", return_value=PROBE_CONTENT)
class DependencyProgressTest(RealHomeTestCase):
    """A `download` server is one or two units of work regardless of how long
    the fetch actually takes on the wire -- the whole reason the total has to
    include it rather than counting only artifacts."""

    def test_a_freshly_fetched_dependency_is_one_more_unit_in_the_total(self, _load):
        self.present()
        dry = cli.install(CLI, self.runtime(), dry_run=True, mcp=["probe"])
        placements = len(dry["created"]) + len(dry["updated"])
        events = []
        cli.install(CLI, self.runtime(), mcp=["probe"], on_progress=events.append)
        self.assertEqual(events[0].total, placements + 1 + 2)

    def test_the_dependency_phase_names_the_server(self, _load):
        self.present()
        events = []
        cli.install(CLI, self.runtime(), mcp=["probe"], on_progress=events.append)
        dependency_events = [event for event in events if event.phase == "dependencies"]
        self.assertEqual([event.unit for event in dependency_events], ["probe"])

    def test_done_still_reaches_the_total_with_a_dependency_in_play(self, _load):
        self.present()
        events = []
        cli.install(CLI, self.runtime(), mcp=["probe"], on_progress=events.append)
        total = events[0].total
        self.assertEqual([event.done for event in events], list(range(total + 1)))


@patch("pegasus.core.content.load", return_value=PROBE_CONTENT)
class DownloadByteProgressTest(RealHomeTestCase):
    """The bytes/total fields on `Progress` -- populated only while a
    `download` server's fetch is actually in flight, absent everywhere else.
    """

    def test_a_download_with_a_fake_that_reports_no_progress_leaves_bytes_fields_none(self, _load):
        """The default `FakeDownloader` behaviour -- no `chunk_reports` given
        -- must still install cleanly with every `Progress` carrying no byte
        fields at all, exactly like every progress test above already
        expects. This is the regression guard for adding the fields."""
        self.present()
        events = []
        cli.install(CLI, self.runtime(), mcp=["probe"], on_progress=events.append)
        self.assertTrue(all(event.bytes_downloaded is None for event in events))
        self.assertTrue(all(event.bytes_total is None for event in events))

    def test_a_downloads_byte_progress_reaches_progress_with_the_servers_name(self, _load):
        downloader = FakeDownloader({PROBE.endpoint: BYTES}, chunk_reports=[(4, len(BYTES)), (len(BYTES), len(BYTES))])
        events = []
        self.present()
        cli.install(CLI, self.runtime(downloader=downloader), mcp=["probe"], on_progress=events.append)
        byte_events = [event for event in events if event.bytes_downloaded is not None]
        self.assertEqual([(event.bytes_downloaded, event.bytes_total, event.unit) for event in byte_events],
                          [(4, len(BYTES), "probe"), (len(BYTES), len(BYTES), "probe")])

    def test_byte_progress_events_do_not_advance_done(self, _load):
        """A byte-level tick reports how far *into* the current unit the
        fetch has gotten -- it must never be mistaken for a whole unit
        finishing, or `done` would run ahead of what was actually placed."""
        downloader = FakeDownloader({PROBE.endpoint: BYTES}, chunk_reports=[(4, len(BYTES)), (len(BYTES), len(BYTES))])
        events = []
        self.present()
        cli.install(CLI, self.runtime(downloader=downloader), mcp=["probe"], on_progress=events.append)
        byte_events = [event for event in events if event.bytes_downloaded is not None]
        dependency_tick = next(event for event in events if event.phase == "dependencies" and event.bytes_downloaded is None)
        self.assertTrue(all(event.done == dependency_tick.done - 1 for event in byte_events))

    def test_a_non_download_unit_never_carries_byte_fields(self, _load):
        self.present()
        events = []
        cli.install(CLI, self.runtime(), on_progress=events.append)  # no mcp: nothing to fetch
        self.assertTrue(all(event.bytes_downloaded is None and event.bytes_total is None for event in events))


@patch("pegasus.core.content.load", return_value=PROBE_CONTENT)
class RetirementProgressTest(RealHomeTestCase):
    """Dropping `--mcp probe` on a reinstall is the case that actually
    exercises the retire phase: nothing new to place, one dependency tree and
    its artifacts to retire."""

    def test_a_reinstall_that_retires_a_server_counts_it_in_the_total(self, _load):
        self.present()
        cli.install(CLI, self.runtime(), mcp=["probe"])
        dry = cli.install(CLI, self.runtime(), dry_run=True)
        placements = len(dry["created"]) + len(dry["updated"])
        retirements = len(dry["retired"])
        self.assertGreater(retirements, 0)
        events = []
        cli.install(CLI, self.runtime(), on_progress=events.append)
        self.assertEqual(events[0].total, placements + retirements + 2)

    def test_the_retire_phase_appears_and_done_still_reaches_the_total(self, _load):
        self.present()
        cli.install(CLI, self.runtime(), mcp=["probe"])
        events = []
        cli.install(CLI, self.runtime(), on_progress=events.append)
        self.assertIn("retire", {event.phase for event in events})
        total = events[0].total
        self.assertEqual([event.done for event in events], list(range(total + 1)))


if __name__ == "__main__":
    unittest.main()

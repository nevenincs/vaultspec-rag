"""Byte-level coverage for the progress the long-running CLI verbs emit.

Every assertion here reads the characters a ``Console`` actually wrote. A test
that inspected the string a helper returned would pass while the console it was
handed rendered nothing at all, which is the exact failure mode this surface
was built to fix.

Two matchers earn their keep. ``_plain`` strips the ANSI control bytes so an
assertion binds to text rather than to cursor motion - starting and stopping a
live region emits about a dozen bytes of cursor hide/show whatever the console
does, so any assertion on output LENGTH stays green through a region that
painted nothing. ``_SPINNER_RE`` matches the braille glyphs Rich's "dots"
spinner draws and nothing else the CLI prints does, which is what separates a
live frame from a plain line.

The hub's own bar machinery and a real ``thread_map`` construct the download
tracker here rather than a hand-rolled caller, because the contract being
tested is the one those two entry points impose.
"""

from __future__ import annotations

import contextlib
import io
import json
import re
import urllib.error
import zipfile
from typing import TYPE_CHECKING, Any, cast

import pytest
from typer.testing import CliRunner

from ..cli._core import _build_console
from ..cli._hf_progress import SnapshotProgress
from ..cli._progress import StartupStatusReporter

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

pytestmark = [pytest.mark.unit]

runner = CliRunner()

_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[a-zA-Z]|\x1b\][^\x07]*\x07")
_SPINNER_RE = re.compile(r"[⠀-⣿]")

_MIB = 1 << 20


def _plain(raw: str) -> str:
    return _ANSI_RE.sub("", raw)


def _reporter(
    buffer: io.StringIO,
    *,
    interactive: bool = False,
    json_mode: bool = False,
) -> StartupStatusReporter:
    """Build a reporter writing into *buffer* through the CLI's own console."""
    return StartupStatusReporter(
        json_mode=json_mode,
        console=_build_console(interactive=interactive, file=buffer),
        interactive=interactive,
        static_interval_s=0.0,
    )


class _Clock:
    """Hand-advanced monotonic clock for the tracker's emit rate limit."""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def _byte_bar(bar_class: type[Any], *, desc: str) -> Any:
    """Build one byte bar exactly as ``snapshot_download`` builds its own.

    Through the hub's own factory rather than a hand-written call: that factory
    is what decides whether a custom bar class is handed ``disable`` and
    ``name``, and getting that wrong is how a bar class silently stops
    counting.
    """
    from huggingface_hub.utils.tqdm import (
        _create_progress_bar,  # pyright: ignore[reportPrivateUsage, reportUnknownVariableType]  # huggingface_hub stubs partially unknown
    )

    create = cast("Callable[..., Any]", _create_progress_bar)
    return create(
        cls=bar_class,
        log_level=20,
        name=desc,
        desc=desc,
        total=0,
        initial=0,
        unit="B",
        unit_scale=True,
        bar_format="{l_bar}",
    )


def _seed_totals(bars: list[Any], totals: list[int]) -> None:
    """Grow each bar's total the way the hub's per-file adapter grows them."""
    for bar, total in zip(bars, totals, strict=True):
        bar.total = (bar.total or 0) + total


def _drive_snapshot_bars(
    tracker: SnapshotProgress,
    *,
    transfer_total: int = 3 * _MIB,
    reconstruct_total: int = 3 * _MIB,
    files: int = 3,
) -> None:
    """Run the hub's three bars through a download-shaped sequence."""
    from tqdm.contrib.concurrent import (  # pyright: ignore[reportMissingTypeStubs]
        thread_map,
    )

    bar_class = tracker.tqdm_class
    assert bar_class is not None, "premise: tqdm ships with the hub"
    transfer = _byte_bar(bar_class, desc="Downloading bytes")
    reconstruct = _byte_bar(bar_class, desc="Reconstructing")
    _seed_totals([transfer, reconstruct], [transfer_total, reconstruct_total])
    reconstruct.update(_MIB)
    transfer.update(_MIB // 2)
    thread_map(
        lambda _item: None,
        range(files),
        desc=f"Fetching {files} files",
        max_workers=2,
        tqdm_class=bar_class,
    )


class TestModelWarmupProgress:
    """``server warmup``: the hub's own counters, rendered as one line."""

    def test_a_terminal_gets_a_painted_frame_carrying_both_counts(self):
        """The determinate numbers reach the terminal inside a live frame.

        Three assertions, none redundant. The byte fragment proves the byte
        bars were read, the file fragment proves the ``thread_map`` bar was,
        and the spinner glyph proves a live frame - not a plain fallback line -
        is what carried them.
        """
        buffer = io.StringIO()
        reporter = _reporter(buffer, interactive=True)
        with (
            reporter,
            SnapshotProgress(
                reporter.heartbeat, prefix="Downloading Dense (1/3)", min_interval_s=0.0
            ) as tracker,
        ):
            _drive_snapshot_bars(tracker)

        rendered = buffer.getvalue()
        plain = _plain(rendered)
        assert "1.0 MiB of 3.0 MiB" in plain
        assert "3/3 files" in plain
        assert _SPINNER_RE.search(rendered) is not None

    def test_a_pipe_gets_the_same_numbers_as_plain_lines(self):
        """Off a terminal the counts still land, with no frame around them."""
        buffer = io.StringIO()
        reporter = _reporter(buffer, interactive=False)
        with (
            reporter,
            SnapshotProgress(
                reporter.heartbeat, prefix="Downloading Dense (1/3)", min_interval_s=0.0
            ) as tracker,
        ):
            _drive_snapshot_bars(tracker)

        rendered = buffer.getvalue()
        assert "1.0 MiB of 3.0 MiB" in _plain(rendered)
        assert _SPINNER_RE.search(rendered) is None

    def test_the_denominator_takes_the_smaller_declared_total(self):
        """The network bar's inflated total must never become the size shown.

        The hub grows the transfer bar's own total past the payload as a
        bar-width estimate whenever received bytes overrun the seed. That is
        display arithmetic; reporting it would tell the operator the download
        grew. This is the assertion that catches a future ``max`` or ``sum``
        over the two byte bars.
        """
        buffer = io.StringIO()
        reporter = _reporter(buffer, interactive=False)
        with (
            reporter,
            SnapshotProgress(
                reporter.heartbeat, prefix="Downloading", min_interval_s=0.0
            ) as tracker,
        ):
            _drive_snapshot_bars(
                tracker, transfer_total=8 * _MIB, reconstruct_total=3 * _MIB
            )

        plain = _plain(buffer.getvalue())
        assert "of 3.0 MiB" in plain
        assert "8.0 MiB" not in plain
        assert "11.0 MiB" not in plain

    def test_a_whole_download_writes_nothing_to_the_real_streams(self):
        """tqdm's own frames never reach the terminal the reporter owns.

        End-to-end over all three bars. Two mechanisms defend this - the bars
        are pointed at a throwaway buffer AND their draw method is replaced -
        so removing either one alone leaves this green; the single-bar case
        below is the one that binds to the buffer.
        """
        buffer = io.StringIO()
        out, err = io.StringIO(), io.StringIO()
        reporter = _reporter(buffer, interactive=True)
        with (
            contextlib.redirect_stdout(out),
            contextlib.redirect_stderr(err),
            reporter,
            SnapshotProgress(
                reporter.heartbeat, prefix="Downloading", min_interval_s=0.0
            ) as tracker,
        ):
            _drive_snapshot_bars(tracker)

        assert out.getvalue() == ""
        assert err.getvalue() == ""

    def test_closing_a_lone_bar_writes_nothing_to_the_real_streams(self):
        """Closing the first bar must not emit its carriage return.

        Deliberately one bar at position zero: that is the only shape in which
        tqdm's close writes to its stream directly rather than through the
        replaced draw method, so it is the case that proves the bars are
        pointed away from the real terminal. Adding a second bar renumbers the
        positions and the write stops happening, which would make this test
        stop testing anything.
        """
        buffer = io.StringIO()
        out, err = io.StringIO(), io.StringIO()
        reporter = _reporter(buffer, interactive=False)
        with (
            contextlib.redirect_stdout(out),
            contextlib.redirect_stderr(err),
            reporter,
            SnapshotProgress(
                reporter.heartbeat, prefix="Downloading", min_interval_s=0.0
            ) as tracker,
        ):
            bar_class = tracker.tqdm_class
            assert bar_class is not None
            bar = _byte_bar(bar_class, desc="Downloading bytes")
            _seed_totals([bar], [3 * _MIB])
            bar.update(_MIB)

        assert out.getvalue() == ""
        assert err.getvalue() == ""

    def test_the_emit_rate_limit_drops_ticks_inside_the_interval(self):
        """A per-chunk counter must not repaint the region per chunk."""
        buffer = io.StringIO()
        clock = _Clock()
        reporter = _reporter(buffer, interactive=False)
        with (
            reporter,
            SnapshotProgress(
                reporter.heartbeat, prefix="Downloading", min_interval_s=5.0, now=clock
            ) as tracker,
        ):
            _drive_snapshot_bars(tracker)

        # Everything after the first emission falls inside one interval, so the
        # counts never advance past their opening values.
        assert _plain(buffer.getvalue()).count("Downloading") == 1

    def test_finishing_silences_further_reports(self):
        """A report attempted after the block must not reach the console.

        The hub abandons its byte bars without closing them, so tqdm's
        finaliser closes them later - during interpreter shutdown, when the
        console's own modules are already gone, and the report raises from
        there. Leaving the block has to make that callback inert. The refresh
        is invoked directly, which is what the finaliser does and what makes
        this fail if the silencing is removed.
        """
        buffer = io.StringIO()
        reporter = _reporter(buffer, interactive=False)
        with reporter:
            with SnapshotProgress(
                reporter.heartbeat, prefix="Downloading", min_interval_s=0.0
            ) as tracker:
                bar_class = tracker.tqdm_class
                assert bar_class is not None
                bar = _byte_bar(bar_class, desc="Downloading bytes")
                _seed_totals([bar], [4 * _MIB])
                bar.update(_MIB)
            before = buffer.getvalue()
            assert "Downloading" in _plain(before), "premise: it reported while open"
            tracker.refresh()

        assert buffer.getvalue() == before

    def test_finishing_closes_every_bar_it_tracked(self):
        """The bars are closed on the way out, not left to the finaliser.

        Closing here is the half of the defence that removes the shutdown
        callback entirely rather than merely making it quiet, so it is
        asserted separately from the silencing above.
        """
        buffer = io.StringIO()
        reporter = _reporter(buffer, interactive=False)
        with SnapshotProgress(
            reporter.heartbeat, prefix="Downloading", min_interval_s=0.0
        ) as tracker:
            bar_class = tracker.tqdm_class
            assert bar_class is not None
            bar = _byte_bar(bar_class, desc="Downloading bytes")
            assert not bar.disable, "premise: the bar counts while open"

        # tqdm marks a closed bar disabled, which is what makes its finaliser
        # return before it can draw or report anything.
        assert bar.disable

    def test_json_mode_writes_nothing_at_all(self):
        """A machine-readable caller owes stdout exactly one envelope."""
        buffer = io.StringIO()
        reporter = _reporter(buffer, interactive=False, json_mode=True)
        with (
            reporter,
            SnapshotProgress(
                reporter.heartbeat, prefix="Downloading", min_interval_s=0.0
            ) as tracker,
        ):
            _drive_snapshot_bars(tracker)

        assert buffer.getvalue() == ""


def _zip_archive(path: Path, member: str, payload: bytes) -> Path:
    """Write a one-member zip, the shape the Windows release asset has."""
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr(member, payload)
    return path


class TestQdrantProvisionProgress:
    """``server qdrant install``: download, verify, and extract now speak."""

    def test_verification_is_reported_before_extraction(self, tmp_path: Path):
        """The reported sequence follows the enforced one.

        Order is the security property here: the digest is checked before the
        archive is unpacked. The report has to describe that order rather than
        invent a friendlier one.
        """
        from ..qdrant_runtime._provision import extract_verified_archive, file_sha256
        from ..qdrant_runtime._resolve import binary_filename

        archive = _zip_archive(
            tmp_path / "qdrant.zip", binary_filename(), b"not really a binary"
        )
        buffer = io.StringIO()
        reporter = _reporter(buffer, interactive=False)
        dest = tmp_path / "bin"
        dest.mkdir()
        with reporter:
            extract_verified_archive(
                archive,
                file_sha256(archive),
                dest,
                on_progress=reporter.stage,
            )

        plain = _plain(buffer.getvalue())
        verify_at = plain.find("Verifying the Qdrant download checksum")
        extract_at = plain.find("Extracting the Qdrant server")
        assert verify_at >= 0, plain
        assert extract_at > verify_at, plain

    def test_a_bad_digest_reports_verification_and_never_extraction(
        self, tmp_path: Path
    ):
        """A rejected archive must never be described as extracted.

        Matching the extraction line specifically, not just "some output
        appeared": a report that announced extraction before the digest was
        compared would still print plenty.
        """
        from ..qdrant_runtime._provision import (
            ChecksumMismatchError,
            extract_verified_archive,
        )
        from ..qdrant_runtime._resolve import binary_filename

        archive = _zip_archive(
            tmp_path / "qdrant.zip", binary_filename(), b"tampered payload"
        )
        buffer = io.StringIO()
        reporter = _reporter(buffer, interactive=False)
        dest = tmp_path / "bin"
        dest.mkdir()
        with reporter, pytest.raises(ChecksumMismatchError):
            extract_verified_archive(
                archive, "00" * 32, dest, on_progress=reporter.stage
            )

        plain = _plain(buffer.getvalue())
        assert "Verifying the Qdrant download checksum" in plain
        assert "Extracting the Qdrant server" not in plain
        assert not (dest / binary_filename()).exists()

    def test_the_stream_reports_bytes_against_the_declared_total(self, tmp_path: Path):
        """A transfer reports how far along it is, not merely that it runs."""
        from ..qdrant_runtime._provision import _stream_capped

        payload = b"x" * (9 << 20)
        buffer = io.StringIO()
        reporter = _reporter(buffer, interactive=False)
        target = tmp_path / "staged.bin"
        with reporter, target.open("wb") as out:
            written = _stream_capped(
                io.BytesIO(payload),
                out,
                declared=len(payload),
                on_progress=reporter.stage,
            )

        assert written == len(payload)
        plain = _plain(buffer.getvalue())
        assert "4.0 MiB of 9.0 MiB" in plain
        assert "9.0 MiB of 9.0 MiB" in plain

    def test_an_undeclared_length_reports_bytes_without_a_denominator(
        self, tmp_path: Path
    ):
        """A response with no ``Content-Length`` must not invent one."""
        from ..qdrant_runtime._provision import _stream_capped

        payload = b"y" * (5 << 20)
        buffer = io.StringIO()
        reporter = _reporter(buffer, interactive=False)
        target = tmp_path / "staged.bin"
        with reporter, target.open("wb") as out:
            _stream_capped(
                io.BytesIO(payload), out, declared=0, on_progress=reporter.stage
            )

        plain = _plain(buffer.getvalue())
        assert "5.0 MiB" in plain
        assert " of " not in plain

    def test_the_size_cap_still_refuses_an_oversized_stream(self, tmp_path: Path):
        """Reporting was added around the cap, not in place of it."""
        from ..qdrant_runtime import _provision

        payload = b"z" * (_provision._MAX_DOWNLOAD_BYTES + 1)
        target = tmp_path / "staged.bin"
        with (
            target.open("wb") as out,
            pytest.raises(urllib.error.URLError, match="byte cap"),
        ):
            _provision._stream_capped(
                io.BytesIO(payload),
                out,
                declared=len(payload),
                on_progress=lambda _line: None,
            )

    def test_json_install_emits_exactly_one_envelope(self, tmp_path: Path):
        """``--json`` keeps the reporter silent so the envelope stands alone."""
        from ..cli import app
        from ..config import EnvVar
        from .conftest import managed_env

        with managed_env(
            **{EnvVar.QDRANT_STORAGE_DIR.value: str(tmp_path / "qdrant" / "storage")}
        ):
            result = runner.invoke(
                app, ["server", "qdrant", "install", "--dry-run", "--json"]
            )

        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["command"] == "server.qdrant.install"
        assert "Installing the managed Qdrant server" not in result.output


class TestReconcileProgress:
    """``server reconcile``: a bounded wait that says what it waits for."""

    def test_every_unconverged_poll_reports_its_verdict(self):
        """The wait ticks with the reason it has not converged yet.

        A live singleton holder whose published pointer is not yet trustworthy
        is the state this verb exists for: neither converged nor stopped, so
        the loop keeps polling until the deadline. The clock and the sleep are
        supplied as the function's own parameters, so the whole wait is driven
        without any real elapsed time.
        """
        from ..serviceclient._discovery import (
            DISCOVERY_STATE_DEGRADED,
            MachineResolution,
        )
        from ..serviceclient._status import LivenessSignals, reconcile_discovery

        clock = _Clock()

        def _tick(_seconds: float) -> None:
            clock.now += 1.0

        unpublished = MachineResolution(
            state=DISCOVERY_STATE_DEGRADED,
            source="machine_lock",
            holder_pid=4321,
            reason="holder has not published a pointer",
        )
        buffer = io.StringIO()
        reporter = _reporter(buffer, interactive=False)
        with reporter:
            outcome = reconcile_discovery(
                lambda: unpublished,
                lambda _resolution: LivenessSignals(pid=4321, pid_alive=True),
                lambda _port: None,
                timeout_s=3.0,
                interval_s=1.0,
                sleep=_tick,
                monotonic=clock,
                on_attempt=lambda attempt, verdict: reporter.heartbeat(
                    f"Waiting for discovery: {verdict.label} (poll {attempt})"
                ),
            )

        assert not outcome.converged
        assert outcome.attempts > 1, "premise: the wait must actually loop"
        plain = _plain(buffer.getvalue())
        assert "Waiting for discovery:" in plain
        assert "(poll 1)" in plain

    def test_json_reconcile_emits_exactly_one_envelope(
        self, isolated_singleton_dirs: Path
    ):
        """No progress text may reach the machine-readable channel."""
        from ..cli import app

        del isolated_singleton_dirs
        result = runner.invoke(app, ["server", "reconcile", "--json", "--timeout", "0"])

        payload = json.loads(result.output)
        assert payload["command"] == "service.reconcile"
        assert "Waiting for service discovery" not in result.output


class TestStorageProgress:
    """``server storage``: the walks that used to run silent."""

    @staticmethod
    def _client_with(collections: tuple[str, ...]) -> Any:
        from qdrant_client import QdrantClient, models

        client = QdrantClient(":memory:")
        for name in collections:
            client.create_collection(
                name,
                vectors_config=models.VectorParams(
                    size=4, distance=models.Distance.COSINE
                ),
            )
        return client

    def test_survey_counts_collections_against_a_known_total(self):
        """The survey's per-collection round trips are reported N of M."""
        from ..storage_ops import gather_survey

        client = self._client_with(("r0123456789ab_docs", "r0123456789ab_code"))
        buffer = io.StringIO()
        reporter = _reporter(buffer, interactive=False)
        try:
            with reporter:
                gather_survey(client, None, on_progress=reporter.stage)
        finally:
            client.close()

        plain = _plain(buffer.getvalue())
        assert "Counting points (1/2 collections)" in plain
        assert "Counting points (2/2 collections)" in plain

    def test_reconcile_reports_the_geometry_read_it_starts_with(self):
        """The geometry read precedes any per-collection work."""
        from ..storage_ops import reconcile_collections

        client = self._client_with(("r0123456789ab_docs",))
        buffer = io.StringIO()
        reporter = _reporter(buffer, interactive=False)
        try:
            with reporter:
                reconcile_collections(
                    client,
                    storage_dir=None,
                    cap=10,
                    budget_s=1.0,
                    dry_run=True,
                    on_progress=reporter.stage,
                )
        finally:
            client.close()

        assert "Reading collection geometry" in _plain(buffer.getvalue())

    def test_migrate_names_each_collection_in_flight(self):
        """A copy that moves every point must say which one it is on."""
        from ..storage_ops import migrate_collections

        source = self._client_with(("r0123456789ab_docs",))
        target = self._client_with(())
        buffer = io.StringIO()
        reporter = _reporter(buffer, interactive=False)
        try:
            with reporter:
                migrate_collections(
                    source,
                    target,
                    {"r0123456789ab_docs": "docs"},
                    dry_run=True,
                    on_progress=reporter.stage,
                )
        finally:
            source.close()
            target.close()

        assert "Migrating 1/1: r0123456789ab_docs -> docs" in _plain(buffer.getvalue())

    def test_prune_names_each_orphaned_namespace(self, isolated_singleton_dirs: Path):
        """Reclamation reports the namespace it is working through."""
        from ..storage_manifest import record_root
        from ..storage_ops import prune_orphaned

        del isolated_singleton_dirs
        vanished = "C:/definitely/not/a/real/root/for/this/test"
        entry = record_root(vanished, backend="server")
        client = self._client_with((f"{entry.prefix}docs",))
        buffer = io.StringIO()
        reporter = _reporter(buffer, interactive=False)
        try:
            with reporter:
                result = prune_orphaned(
                    client, dry_run=True, storage_dir=None, on_progress=reporter.stage
                )
        finally:
            client.close()

        assert [r.prefix for r in result.results] == [entry.prefix]
        assert f"Planning orphaned namespace 1/1: {entry.prefix}" in _plain(
            buffer.getvalue()
        )

    def test_json_survey_emits_one_envelope_and_no_progress(
        self, isolated_singleton_dirs: Path
    ):
        """The survey's machine channel stays a single document."""
        from ..cli import app

        del isolated_singleton_dirs
        result = runner.invoke(app, ["server", "storage", "survey", "--json"])

        payload = json.loads(result.output)
        assert payload["command"] == "server.storage.survey"
        assert "Surveying stored index namespaces" not in result.output
        assert "Counting points" not in result.output

    @pytest.mark.parametrize(
        ("argv", "command"),
        [
            (
                ["server", "storage", "prune", "--json", "--yes", "--dry-run"],
                "server.storage.prune",
            ),
            (
                ["server", "storage", "reconcile", "--json", "--yes", "--dry-run"],
                "server.storage.reconcile",
            ),
        ],
    )
    def test_json_destructive_verbs_emit_exactly_one_envelope(
        self,
        argv: list[str],
        command: str,
        isolated_singleton_dirs: Path,
    ):
        """Each verb owes stdout one document, on the failure path too.

        Server mode is switched off so the run terminates inside the reporting
        block against a refused backend rather than reaching the operator's own
        store. That is the path where a progress line would corrupt the
        envelope, because it is emitted while the block is open.
        """
        from ..cli import app
        from ..config import EnvVar
        from .conftest import managed_env

        del isolated_singleton_dirs
        with managed_env(**{EnvVar.QDRANT_SERVER.value: "false"}):
            result = runner.invoke(app, argv)

        assert result.exit_code == 2, result.output
        payload = json.loads(result.output)
        assert payload["command"] == command
        assert payload["ok"] is False

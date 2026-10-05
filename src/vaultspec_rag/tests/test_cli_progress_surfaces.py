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
from typing import TYPE_CHECKING, Any, Protocol, cast

import pytest
from typer.testing import CliRunner

from ..cli._core import _build_console
from ..cli._progress import StartupStatusReporter
from ..cli._provision_progress import ReporterProvisionProgress
from ..commands._snapshot_progress import (
    SnapshotBars,
    SnapshotCounts,
    progress_line,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from qdrant_client import QdrantClient

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


class _ByteBar(Protocol):
    """The members this module drives on a hub-constructed tqdm bar."""

    total: int | float | None
    disable: bool

    def update(self, n: int) -> bool | None: ...


def _byte_bar(bar_class: type[Any], *, desc: str) -> _ByteBar:
    """Build one byte bar exactly as ``snapshot_download`` builds its own.

    Through the hub's own factory rather than a hand-written call: that factory
    is what decides whether a custom bar class is handed ``disable`` and
    ``name``, and getting that wrong is how a bar class silently stops
    counting. ``bar_class`` stays ``type[Any]`` because it is threaded straight
    through from the hub's own ``tqdm_class`` property, which is typed exactly
    that way against the hub's partially-unknown tqdm stubs.
    """
    from huggingface_hub.utils.tqdm import (
        _create_progress_bar,  # pyright: ignore[reportUnknownVariableType]  # huggingface_hub stubs partially unknown
    )

    create = cast("Callable[..., _ByteBar]", _create_progress_bar)
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


def _seed_totals(bars: list[_ByteBar], totals: list[int]) -> None:
    """Grow each bar's total the way the hub's per-file adapter grows them."""
    for bar, total in zip(bars, totals, strict=True):
        bar.total = (bar.total or 0) + total


def _drive_snapshot_bars(
    tracker: SnapshotBars,
    *,
    transfer_total: int = 3 * _MIB,
    reconstruct_total: int = 3 * _MIB,
    files: int = 3,
) -> None:
    """Run the hub's three bars through a download-shaped sequence."""
    from tqdm.contrib.concurrent import (
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


class TestModelDownloadProgress:
    """A model download: the hub's own counters, counted in one place and shown
    in another.

    The bars are built and counted in the process that downloads; the command
    that started it only receives the counts and renders them. Both halves are
    driven here - the counting with the hub's real bar factory, the rendering
    through the sink every fetching command hands the provisioning front door.
    """

    def test_a_terminal_gets_a_painted_frame_carrying_both_counts(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """The determinate numbers reach the terminal inside a live frame.

        Three assertions, none redundant. The byte fragment proves the byte
        bars were read, the file fragment proves the ``thread_map`` bar was,
        and the spinner glyph proves a live frame - not a plain fallback line -
        is what carried them.
        """
        monkeypatch.setenv("TERM", "xterm-256color")
        buffer = io.StringIO()
        reporter = _reporter(buffer, interactive=True)
        with SnapshotBars() as bars, ReporterProvisionProgress(reporter) as sink:
            _drive_snapshot_bars(bars)
            sink.downloading("Downloading Dense (1/3)", bars.counts())

        rendered = buffer.getvalue()
        plain = _plain(rendered)
        assert "1.0 MiB of 3.0 MiB" in plain
        assert "3/3 files" in plain
        assert _SPINNER_RE.search(rendered) is not None

    def test_a_pipe_gets_the_same_numbers_as_plain_lines(self):
        """Off a terminal the counts still land, with no frame around them."""
        buffer = io.StringIO()
        reporter = _reporter(buffer, interactive=False)
        with SnapshotBars() as bars, ReporterProvisionProgress(reporter) as sink:
            _drive_snapshot_bars(bars)
            sink.downloading("Downloading Dense (1/3)", bars.counts())

        rendered = buffer.getvalue()
        assert "Downloading Dense (1/3): 3/3 files, 1.0 MiB of 3.0 MiB" in _plain(
            rendered
        )
        assert _SPINNER_RE.search(rendered) is None

    def test_the_denominator_takes_the_smaller_declared_total(self):
        """The network bar's inflated total must never become the size shown.

        The hub grows the transfer bar's own total past the payload as a
        bar-width estimate whenever received bytes overrun the seed. That is
        display arithmetic; reporting it would tell the operator the download
        grew. This is the assertion that catches a future ``max`` or ``sum``
        over the two byte bars.
        """
        with SnapshotBars() as bars:
            _drive_snapshot_bars(
                bars, transfer_total=8 * _MIB, reconstruct_total=3 * _MIB
            )
            counts = bars.counts()

        assert counts == SnapshotCounts(
            files_done=3, files_total=3, bytes_done=_MIB, bytes_total=3 * _MIB
        )
        line = progress_line("Downloading", counts)
        assert "of 3.0 MiB" in line
        assert "8.0 MiB" not in line
        assert "11.0 MiB" not in line

    def test_bytes_past_the_declared_size_are_shown_without_a_denominator(self):
        """A count above the declared size is never shown as a fraction of it."""
        line = progress_line(
            "Downloading", SnapshotCounts(bytes_done=5 * _MIB, bytes_total=0)
        )

        assert line == "Downloading: 5.0 MiB"
        assert progress_line("Downloading", SnapshotCounts()) == "Downloading..."

    def test_a_whole_download_writes_nothing_to_the_real_streams(self):
        """tqdm's own frames never reach a stream somebody else owns.

        End-to-end over all three bars. Two mechanisms defend this - the bars
        are pointed at a throwaway buffer AND their draw method is replaced -
        so removing either one alone leaves this green; the single-bar case
        below is the one that binds to the buffer.
        """
        out, err = io.StringIO(), io.StringIO()
        with (
            contextlib.redirect_stdout(out),
            contextlib.redirect_stderr(err),
            SnapshotBars() as bars,
        ):
            _drive_snapshot_bars(bars)

        assert out.getvalue() == ""
        assert err.getvalue() == ""

    def test_closing_a_lone_bar_writes_nothing_to_the_real_streams(self):
        """Closing the first bar must not emit its carriage return.

        Deliberately one bar at position zero: that is the only shape in which
        tqdm's close writes to its stream directly rather than through the
        replaced draw method, so it is the case that proves the bars are
        pointed away from the real streams. Adding a second bar renumbers the
        positions and the write stops happening, which would make this test
        stop testing anything.
        """
        out, err = io.StringIO(), io.StringIO()
        with (
            contextlib.redirect_stdout(out),
            contextlib.redirect_stderr(err),
            SnapshotBars() as bars,
        ):
            bar_class = bars.tqdm_class
            assert bar_class is not None
            bar = _byte_bar(bar_class, desc="Downloading bytes")
            _seed_totals([bar], [3 * _MIB])
            bar.update(_MIB)

        assert out.getvalue() == ""
        assert err.getvalue() == ""

    def test_finishing_closes_every_bar_it_tracked(self):
        """The bars are closed on the way out, not left to the finaliser.

        The hub abandons its byte bars without closing them, so tqdm's
        finaliser would close them during interpreter shutdown, when the
        modules a bar draws with are already gone.
        """
        with SnapshotBars() as bars:
            bar_class = bars.tqdm_class
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
        with SnapshotBars() as bars, ReporterProvisionProgress(reporter) as sink:
            _drive_snapshot_bars(bars)
            sink.stage("Downloading Dense (1/3)...")
            sink.downloading("Downloading Dense (1/3)", bars.counts())

        assert buffer.getvalue() == ""

    def test_the_provisioning_sink_draws_nothing_until_it_reports(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """No live region opens before provisioning has something to say.

        ``install`` asks its questions before it provisions, and a region
        already animating would be drawn over the prompt. Entering the sink
        therefore writes nothing, and the first report is what opens it.

        Mutation check: with the region opened on entry, the terminal has
        already been written to when the first assertion runs, and it fails;
        restoring the lazy open passes.
        """
        monkeypatch.setenv("TERM", "xterm-256color")
        buffer = io.StringIO()
        reporter = _reporter(buffer, interactive=True)
        with ReporterProvisionProgress(reporter) as sink:
            assert buffer.getvalue() == "", "a live region opened before any report"
            sink.stage("Checking the cache for Dense (1/3)")
            assert _SPINNER_RE.search(buffer.getvalue()) is not None

        assert "Checking the cache for Dense (1/3)" in _plain(buffer.getvalue())


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
        from ..qdrant_runtime._download import _stream_capped

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
        from ..qdrant_runtime._download import _stream_capped

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
        from ..qdrant_runtime import _download

        payload = b"z" * (_download._MAX_DOWNLOAD_BYTES + 1)
        target = tmp_path / "staged.bin"
        with (
            target.open("wb") as out,
            pytest.raises(urllib.error.URLError, match="byte cap"),
        ):
            _download._stream_capped(
                io.BytesIO(payload),
                out,
                declared=len(payload),
                on_progress=lambda _line: None,
            )

    def test_json_install_emits_exactly_one_envelope(self, tmp_path: Path):
        """``--json`` keeps the reporter silent so the envelope stands alone."""
        from ..cli import app
        from ..config._types import EnvVar
        from .conftest import managed_env

        with managed_env(
            **{EnvVar.QDRANT_STORAGE_DIR.value: str(tmp_path / "qdrant" / "storage")}
        ):
            result = runner.invoke(
                app, ["server", "qdrant", "install", "--dry-run", "--json"]
            )

        assert result.exit_code == 0, result.output
        payload = cast("dict[str, object]", json.loads(result.output))
        assert payload["command"] == "server.qdrant.install"
        assert "Installing the managed Qdrant server" not in result.output


class TestProvisionerIsReachedAtCallTime:
    """The condition every interception of the Qdrant provisioner rests on.

    The wiring between a start and its provisioning progress is driven in the
    start-provisioning module; what is held here is the one structural fact
    that makes that drive, and every other substitution of the provisioner,
    mean anything.
    """

    def test_the_provision_symbol_is_resolved_at_call_time(self):
        """No module between a command and the provisioner binds it at import.

        Its own reason to exist: a module-scope import would pull the qdrant
        runtime onto the CLI import path. Its reason to live HERE: it is also
        the single condition every interception of that symbol depends on, and
        an interception that has gone inert reports success while the real
        download runs against the operator's machine. The start command
        reaches the provisioner through the provisioning front door, so both
        hops are held to it.
        """
        from ..cli import _service_qdrant, _service_start
        from ..commands import _provision as front_door

        for module in (_service_start, _service_qdrant, front_door):
            assert not hasattr(module, "provision"), module.__name__


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
        from ..serviceclient._status import (
            LivenessSignals,
            ReconcileRequest,
            reconcile_discovery,
        )

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
                ReconcileRequest(
                    resolve=lambda: unpublished,
                    probe_liveness=lambda _resolution: LivenessSignals(
                        pid=4321, pid_alive=True
                    ),
                    probe_health=lambda _port: None,
                    timeout_s=3.0,
                    interval_s=1.0,
                    sleep=_tick,
                    monotonic=clock,
                    on_attempt=lambda attempt, verdict: reporter.heartbeat(
                        f"Waiting for discovery: {verdict.label} (poll {attempt})"
                    ),
                )
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

        payload = cast("dict[str, object]", json.loads(result.output))
        assert payload["command"] == "service.reconcile"
        assert "Waiting for service discovery" not in result.output


class TestStorageProgress:
    """``server storage``: the walks that used to run silent."""

    @staticmethod
    def _client_with(collections: tuple[str, ...]) -> QdrantClient:
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
        from ..storage_survey_ops import gather_survey

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
        from ..storage_reconciliation import reconcile_collections

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
        from ..storage_migration import migrate_collections

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

    def test_prune_names_each_orphaned_namespace(
        self, tmp_path: Path, isolated_singleton_dirs: Path
    ):
        """Reclamation reports the namespace it is working through."""
        from ..storage_manifest import record_root
        from ..storage_survey_ops import prune_orphaned

        del isolated_singleton_dirs
        vanished = str(
            tmp_path
            / "definitely"
            / "not"
            / "a"
            / "real"
            / "root"
            / "for"
            / "this"
            / "test"
        )
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
        from ..config._types import EnvVar
        from ._qdrant_warnings import VERSION_WARNING, await_client_warnings
        from .conftest import managed_env

        del isolated_singleton_dirs
        with (
            managed_env(**{EnvVar.QDRANT_URL.value: "http://127.0.0.1:9"}),
            pytest.warns(
                UserWarning, match="Failed to obtain server version"
            ) as captured,
        ):
            result = runner.invoke(app, ["server", "storage", "survey", "--json"])
            await_client_warnings(captured, [VERSION_WARNING])

        payload = cast("dict[str, object]", json.loads(result.output))
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
        from ..config._types import EnvVar
        from .conftest import managed_env

        del isolated_singleton_dirs
        with managed_env(**{EnvVar.QDRANT_SERVER.value: "false"}):
            result = runner.invoke(app, argv)

        assert result.exit_code == 2, result.output
        payload = cast("dict[str, object]", json.loads(result.output))
        assert payload["command"] == command
        assert payload["ok"] is False

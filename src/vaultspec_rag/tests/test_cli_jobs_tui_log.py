"""Tests for the structured log pane of the interactive jobs interface.

The parsing and rendering functions are exercised directly; everything an
operator sees is exercised through the real interface against the same real
loopback service the rest of the jobs-interface tests use, with the service
serving the log dialects the daemon actually produces - including hostile
content, because log lines are adversarial input.
"""

from __future__ import annotations

import re
import typing
from datetime import datetime

import pytest

if typing.TYPE_CHECKING:
    from pathlib import Path

from ..cli import _jobs_tui, _jobs_tui_log, _jobs_tui_status
from ..cli._jobs_tui_log import (
    _MAX_LINE_CHARS,
    _VALUE_CELLS,
    JobsLogView,
    parse_log_line,
    render_entry,
    sanitize_log_text,
)
from ..cli._jobs_tui_managed_logs import (
    managed_log_group_metadata,
    managed_log_safe_text,
)
from ..cli._jobs_tui_palette import (
    DARK_THEME_NAME,
    LIGHT_THEME_NAME,
    semantic_tones,
)
from ..logging_config import (
    MAX_MANAGED_LOG_RECORD_BYTES,
    query_managed_logs,
    validate_managed_log_payload,
)
from .test_cli_jobs_tui import (
    _app,
    _await_painted,
    _job,
    _JobService,
    _ready,
    _screen_text,
    _settle,
)

pytestmark = [pytest.mark.unit]

_WIDE = (200, 24)
_NARROW = (80, 24)

_APP_ERROR_LINE = (
    "2026-07-28 13:03:13,283 ERROR    vaultspec_rag.watcher: service.watcher "
    "event=reindex_failed source=code job_id=035fa1b2c3d4e5f6a7b8 state=running "
    "error=null pending_paths=7"
)
_ACCESS_POLL_LINE = 'INFO:     127.0.0.1:60085 - "GET /jobs?limit=20 HTTP/1.1" 200 OK'
_ACCESS_SIGNAL_LINE = (
    'INFO:     127.0.0.1:60099 - "POST /index/code HTTP/1.1" 202 Accepted'
)
_QDRANT_LINE = (
    "2026-07-28T12:23:49.079022Z  INFO actix_web::middleware::logger: "
    '127.0.0.1 "PUT /collections/a1b2c3_document_docs/index?wait=true&timeout=119 '
    'HTTP/1.1" 200 91 "-" "python-client/1.18.0 python/3.13.11" 0.009050'
)


@pytest.fixture
def control_service() -> typing.Iterator[_JobService]:
    server = _JobService()
    try:
        yield server
    finally:
        server.close()


class TestLogParsing:
    """Each dialect parses into its fields; nothing is ever invented."""

    def test_an_app_event_line_parses_into_its_fields(self) -> None:
        entry = parse_log_line(_APP_ERROR_LINE)

        assert entry.kind == "app"
        assert entry.level == "ERROR"
        assert entry.timestamp == "13:03:13"
        assert entry.origin == "vaultspec_rag.watcher"
        assert entry.event == "reindex_failed"
        assert entry.message == "service.watcher"
        assert ("source", "code") in entry.pairs
        assert ("pending_paths", "7") in entry.pairs
        assert entry.is_error

    def test_a_spaced_value_stays_whole_on_its_pair(self) -> None:
        entry = parse_log_line(
            "2026-07-28 09:00:00,000 ERROR    vaultspec_rag.jobs: "
            "event=job_failed error=CUDA out of memory"
        )

        assert ("error", "CUDA out of memory") in entry.pairs

    def test_an_access_line_parses_and_invents_no_timestamp(self) -> None:
        entry = parse_log_line(_ACCESS_POLL_LINE)

        assert entry.kind == "access"
        assert entry.method == "GET"
        assert entry.path == "/jobs?limit=20"
        assert entry.status == "200"
        assert entry.reason == "OK"
        # The line carries no timestamp and no duration, so the entry must
        # not either: absent is absent, never a stamp that looks reported.
        assert entry.timestamp is None
        assert entry.duration_ms is None

    def test_a_qdrant_line_parses_with_a_local_timestamp(self) -> None:
        entry = parse_log_line(_QDRANT_LINE)

        assert entry.kind == "qdrant"
        assert entry.method == "PUT"
        assert entry.status == "200"
        assert entry.duration_ms is not None
        assert entry.duration_ms == pytest.approx(9.05)
        # The stamp is UTC; the pane shows the operator's wall clock.
        expected = (
            datetime.fromisoformat("2026-07-28T12:23:49.079022Z")
            .astimezone()
            .strftime("%H:%M:%S")
        )
        assert entry.timestamp == expected

    def test_an_unrecognised_line_is_raw_with_every_field_absent(self) -> None:
        entry = parse_log_line("a completely unstructured line")

        assert entry.kind == "raw"
        assert entry.raw == "a completely unstructured line"
        assert entry.level is None
        assert entry.timestamp is None
        assert entry.pairs == ()
        assert not entry.is_error

    def test_only_this_views_own_polling_reads_as_noise(self) -> None:
        assert parse_log_line(_ACCESS_POLL_LINE).is_polling
        # A mutation is signal even on a polled route.
        assert not parse_log_line(_ACCESS_SIGNAL_LINE).is_polling
        # A route this view does not poll is signal.
        assert not parse_log_line(
            'INFO:     127.0.0.1:60085 - "GET /search HTTP/1.1" 200 OK'
        ).is_polling
        # The backend's traffic is never this view's own reflection.
        assert not parse_log_line(_QDRANT_LINE).is_polling


class TestSanitization:
    """Hostile log content renders inert. These are guards; each names the
    mutation it catches."""

    def test_ansi_escapes_are_stripped_whole(self) -> None:
        entry = parse_log_line("\x1b[31mboom\x1b[0m done \x1b]0;title\x07tail")

        # Catches removing the escape-sequence substitution from
        # ``sanitize_log_text``: the ESC bytes and the printable bodies of
        # the sequences would both survive into the rendered text.
        assert entry.raw == "boom done tail"
        assert "\x1b" not in entry.raw
        assert "[31m" not in entry.raw

    def test_control_characters_are_removed(self) -> None:
        cleaned = sanitize_log_text("bell\x07 null\x00 tab\there")

        # Catches removing the control-character translation from
        # ``sanitize_log_text``: the bell and NUL would survive, and the tab
        # would fuse its neighbours instead of separating them.
        assert cleaned == "bell null tab here"

    def test_an_absurdly_long_line_is_bounded_with_a_visible_mark(self) -> None:
        cleaned = sanitize_log_text("x" * (10 * _MAX_LINE_CHARS))

        # Catches removing the length bound from ``sanitize_log_text``: the
        # whole ten-fold line would come back untrimmed.
        assert len(cleaned) == _MAX_LINE_CHARS
        assert cleaned.endswith("…")

    def test_the_raw_managed_tank_keeps_a_full_sanitized_record(self) -> None:
        """The global tank neutralizes controls but has no diagnostic-pane cap."""
        record = "\x1b[31m" + "x" * (10 * _MAX_LINE_CHARS) + "\x1b[0m\tend"

        rendered = managed_log_safe_text(record)

        assert len(rendered) == 10 * _MAX_LINE_CHARS + len(" end"), (
            "the raw tank must retain every printable record character"
        )
        assert rendered.endswith("x end")
        assert "\x1b" not in rendered
        assert "[31m" not in rendered

    @pytest.mark.asyncio
    async def test_hostile_log_content_renders_inert_on_screen(
        self, control_service: _JobService
    ) -> None:
        """The guard holds through the real fetch-parse-paint path.

        Proven able to fail: removing the escape-sequence substitution from
        ``sanitize_log_text`` paints the CSI body as visible ``[31m`` garbage
        and fails the no-fragment assertion by name; restored, it passes.
        """
        control_service.log_lines = [
            "\x1b[31mhostile ansi payload\x1b[0m with \x07 control bytes"
        ]
        app = _app(control_service, [_job("abc123def456")])
        async with app.run_test(size=_WIDE, notifications=True) as pilot:
            await _ready(pilot, app)
            painted = await _await_painted(pilot, app, "hostile ansi payload")

        assert "\x1b" not in painted, "no escape byte may reach the screen"
        assert "[31m" not in painted, "no escape-sequence fragment may reach the screen"
        assert "hostile ansi payload with  control bytes" in painted, (
            "the line's text survives sanitization; only the hostility goes"
        )


class TestManagedLogTank:
    """The global tank renders the real grouped log contract without parsing it."""

    def test_real_managed_file_truncation_is_named_with_its_server_bounds(
        self,
        tmp_path: Path,
    ) -> None:
        """A real oversized producer record carries its truncation truth."""
        (tmp_path / "service.log").write_text(
            "x" * (MAX_MANAGED_LOG_RECORD_BYTES + 1), encoding="utf-8"
        )
        (tmp_path / "qdrant.log").write_text(
            "qdrant retained record\n", encoding="utf-8"
        )

        payload = query_managed_logs(5_000, source="all", status_dir=tmp_path)
        groups = validate_managed_log_payload(
            payload,
            source="all",
            limit=5_000,
            filters={},
        )

        assert groups is not None
        service_metadata = managed_log_group_metadata(groups[0])
        qdrant_metadata = managed_log_group_metadata(groups[1])
        assert "service: 1 records" in service_metadata
        assert "server cap 5,000 records / 2 MiB" in service_metadata
        assert "TRUNCATED by server" in service_metadata
        assert "shortened 1 records" in service_metadata
        assert "qdrant: 1 records" in qdrant_metadata
        assert "TRUNCATED" not in qdrant_metadata

    @pytest.mark.asyncio
    async def test_the_global_tank_fetches_both_raw_sources_without_a_job_filter(
        self,
        control_service: _JobService,
    ) -> None:
        """The real transport, validator, and pane keep producer groups apart."""
        control_service.log_lines = [
            "service raw record keeps every field=a=b and polling traffic"
        ]
        control_service.qdrant_log_lines = [
            "qdrant raw record keeps its separate producer identity"
        ]
        app = _app(control_service, [_job("abc123def456")])
        async with app.run_test(size=_WIDE, notifications=True) as pilot:
            await _ready(pilot, app)
            await pilot.press("m")
            await _await_painted(pilot, app, "qdrant raw record keeps")
            painted = _screen_text(app)

        all_source_requests = [
            path
            for method, path in control_service.requests
            if method == "GET" and "source=all" in path
        ]
        assert all_source_requests, "the global tank must request the all-source route"
        assert all("job_id=" not in path for path in all_source_requests), (
            "the global tank must not inherit the selected-job filter"
        )
        assert "[service]" in painted
        assert "service raw record keeps every field=a=b and polling traffic" in painted
        assert "[qdrant]" in painted
        assert "qdrant raw record keeps its separate producer identity" in painted
        assert painted.index("[service]") < painted.index("[qdrant]"), (
            "source groups must retain the server's stable producer order"
        )
        assert "server cap 5,000 records / 2 MiB" in painted
        assert "Managed log tank" in painted


class TestValueTruncation:
    """Long values are elided with their head and tail, expandably."""

    def test_a_long_value_is_elided_keeping_head_and_tail(self) -> None:
        token = "HEAD" + ("m" * 300) + "TAIL"
        entry = parse_log_line(
            f"2026-07-28 09:00:00,000 INFO     vaultspec_rag.jobs: "
            f"event=slot_scan token={token}"
        )
        lines = render_entry(entry, width=200)
        detail = lines[1].plain

        # Catches ``_elide_middle`` returning the value whole: the elision
        # mark would be absent and the full token would land on the line.
        assert "…" in detail
        assert token not in detail
        assert "HEAD" in detail, "the head names the value and must survive"
        assert "TAIL" in detail, "the tail discriminates it and must survive"
        shown = detail.split("token=", 1)[1]
        assert len(shown) == _VALUE_CELLS

    def test_expanded_rendering_shows_the_value_whole(self) -> None:
        token = "HEAD" + ("m" * 300) + "TAIL"
        entry = parse_log_line(
            f"2026-07-28 09:00:00,000 INFO     vaultspec_rag.jobs: "
            f"event=slot_scan token={token}"
        )
        lines = render_entry(entry, width=2000, expanded=True)

        assert token in lines[1].plain, (
            "the full entry must be reachable, not only the elided view"
        )


class TestSemanticTones:
    """Status colours resolve from the copied specification, per variant."""

    def test_dark_tones_are_the_published_text_steps(self) -> None:
        tones = semantic_tones(DARK_THEME_NAME)

        # The specification's dark-scale step-11 values, byte for byte.
        # Catches a palette value drifting from the published spec and the
        # resolver reading the wrong scale or step alike.
        assert tones["good"] == "#3dd68c"
        assert tones["attention"] == "#ffca16"
        assert tones["bad"] == "#ff9592"
        assert tones["neutral"] == "#70b8ff"
        assert tones["muted"] == "#b0b4ba"

    def test_light_tones_are_the_published_text_steps(self) -> None:
        tones = semantic_tones(LIGHT_THEME_NAME)

        # The same tokens against the light scales' published step-11
        # values. Catches the resolver ignoring the variant and answering
        # with one scale for both.
        assert tones["good"] == "#218358"
        assert tones["attention"] == "#ab6400"
        assert tones["bad"] == "#ce2c31"
        assert tones["neutral"] == "#0d74ce"
        assert tones["muted"] == "#60646c"

    def test_an_unknown_name_resolves_the_dark_variant(self) -> None:
        """A render outside the app still styles by meaning, on the default."""
        assert semantic_tones("") == semantic_tones(DARK_THEME_NAME)


class TestPaletteDiscipline:
    """One palette module; a colour literal anywhere else is a defect."""

    def test_no_colour_literal_outside_the_palette_module(self) -> None:
        import ast
        from pathlib import Path

        hex_re = re.compile(r"#[0-9a-fA-F]{6}\b")
        ansi_re = re.compile(
            r"^(?:(?:bold|italic|dim|strike)\s+)*"
            r"(?:red|green|yellow|blue|magenta|cyan|white|black)"
            r"(?:\s+(?:bold|italic|dim|strike))*$"
        )
        offenders: list[tuple[str, int, str]] = []
        for module in (_jobs_tui, _jobs_tui_log, _jobs_tui_status):
            source_path = Path(str(module.__file__))
            tree = ast.parse(source_path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Constant) and isinstance(node.value, str):
                    value = node.value
                    if hex_re.search(value) or ansi_re.match(value.strip()):
                        offenders.append((source_path.name, node.lineno, value))

        # Catches a colour stated outside the palette module - a planted
        # ``style="bold red"`` or a bare hex - which would fork the palette
        # into a second source the variants cannot switch together.
        assert offenders == [], f"colour literals outside the palette: {offenders}"


class TestLevelColours:
    """The badge carries the level's tone; errors read as errors."""

    def test_an_error_badge_carries_the_bad_tone(self) -> None:
        tones = semantic_tones(DARK_THEME_NAME)
        header = render_entry(parse_log_line(_APP_ERROR_LINE), width=120)[0]
        styles = [str(span.style) for span in header.spans]

        assert f"bold {tones['bad']}" in styles, (
            "an ERROR badge must carry the palette's bad tone, emboldened"
        )

    def test_an_info_badge_recedes_to_the_muted_tone(self) -> None:
        tones = semantic_tones(DARK_THEME_NAME)
        header = render_entry(parse_log_line(_ACCESS_SIGNAL_LINE), width=120)[0]
        styles = [str(span.style) for span in header.spans]

        assert tones["muted"] in styles, "an INFO badge must recede, not compete"


class TestNoiseCollapse:
    """The view's own polling reflections hide behind a visible marker."""

    @pytest.mark.asyncio
    async def test_polling_lines_collapse_behind_a_counted_marker(
        self, control_service: _JobService
    ) -> None:
        """Hidden lines are counted where they sat, and the title says so.

        Proven able to fail two ways: removing the marker write from
        ``_flush_hidden`` hides the run with no trace and fails on the marker
        assertion by name; removing the indicator from ``_refresh_log_title``
        fails on the title assertion by name. Restored, both pass.
        """
        control_service.log_lines = [
            _APP_ERROR_LINE,
            _ACCESS_POLL_LINE,
            _ACCESS_POLL_LINE,
            _ACCESS_POLL_LINE,
            _ACCESS_POLL_LINE,
            _ACCESS_SIGNAL_LINE,
        ]
        app = _app(control_service, [_job("abc123def456")])
        async with app.run_test(size=_WIDE, notifications=True) as pilot:
            await _ready(pilot, app)
            painted = await _await_painted(pilot, app, "reindex_failed")

        assert "GET /jobs?limit=20" not in painted, (
            "the view's own polling must not drown its signal"
        )
        assert "4 polling lines hidden — x shows them" in painted, (
            "hidden lines must be counted where they sat, never silent"
        )
        assert "4 polling hidden (x shows)" in painted, (
            "the active filter must be indicated in the pane's title"
        )
        assert "POST /index/code" in painted, (
            "a mutation on a polled route is signal and stays visible"
        )

    @pytest.mark.asyncio
    async def test_the_noise_key_reveals_and_rehides_the_polling(
        self, control_service: _JobService
    ) -> None:
        control_service.log_lines = [
            _APP_ERROR_LINE,
            _ACCESS_POLL_LINE,
            _ACCESS_POLL_LINE,
        ]
        app = _app(control_service, [_job("abc123def456")])
        async with app.run_test(size=_WIDE, notifications=True) as pilot:
            await _ready(pilot, app)
            await _await_painted(pilot, app, "reindex_failed")

            await pilot.press("x")
            shown = await _await_painted(pilot, app, "GET /jobs?limit=20")

            await pilot.press("x")
            rehidden = await _await_painted(pilot, app, "2 polling lines hidden")

        assert "polling shown (x hides)" in shown, (
            "the toggled-open state must be indicated too"
        )
        assert "polling lines hidden" not in shown
        assert "GET /jobs?limit=20" not in rehidden


class TestLogNavigation:
    """The pane is navigable, and a dead key answers instead of dying."""

    @staticmethod
    def _long_window() -> list[str]:
        filler = [f"filler line number {index}" for index in range(60)]
        return [*filler, _APP_ERROR_LINE, *(f"tail line {i}" for i in range(30))]

    @pytest.mark.asyncio
    async def test_top_bottom_and_error_jumps_move_the_pane(
        self, control_service: _JobService
    ) -> None:
        control_service.log_lines = self._long_window()
        app = _app(control_service, [_job("abc123def456")])
        async with app.run_test(size=_WIDE, notifications=True) as pilot:
            await _ready(pilot, app)
            await _await_painted(pilot, app, "tail line 29")
            log = app._log_view()
            assert log is not None
            await _settle(pilot)

            await pilot.press("g")
            await pilot.pause()
            top = log.scroll_offset.y

            await pilot.press("G")
            await pilot.pause()
            bottom = log.scroll_offset.y

            await pilot.press("n")
            await pilot.pause()
            at_error = log.scroll_offset.y

        assert top == 0, "g must return the pane to the top"
        assert bottom > 0, "G must take the pane to the end"
        assert at_error == log._error_offsets[0], (
            "n must land the pane on the error entry"
        )
        assert 0 < at_error < bottom, (
            "the error sits inside the window, so the jump is a real move"
        )

    @pytest.mark.asyncio
    async def test_the_error_key_answers_when_the_log_has_no_errors(
        self, control_service: _JobService
    ) -> None:
        """A greyed key that answers nothing reads as a broken interface.

        Proven able to fail: removing the error-count check from
        ``_check_log_action`` lets the binding invoke the action, nothing is
        painted, and the reason assertion fails by name; restored, it passes.
        """
        control_service.log_lines = ["a benign line", "another benign line"]
        app = _app(control_service, [_job("abc123def456")])
        async with app.run_test(size=_WIDE, notifications=True) as pilot:
            await _ready(pilot, app)
            await _await_painted(pilot, app, "a benign line")
            await pilot.press("n")
            painted = await _await_painted(pilot, app, "no error entries")

        assert "This log has no error entries." in painted, (
            "an unavailable jump must say why, not do nothing"
        )

    @pytest.mark.asyncio
    async def test_log_keys_answer_while_the_pane_is_closed(
        self, control_service: _JobService
    ) -> None:
        """The log keys must not go silent just because the pane is closed."""
        app = _app(control_service, [_job("abc123def456")])
        async with app.run_test(size=_NARROW, notifications=True) as pilot:
            await _ready(pilot, app)
            assert not app._log_visible()
            await pilot.press("x")
            painted = await _await_painted(pilot, app, "log pane is closed")

        # In two pieces: an 80-column toast wraps the sentence mid-way.
        assert "The log pane is closed" in painted
        assert "open it." in painted


class TestPaneFocusAndZoom:
    """The focus ring says where the keyboard is; zoom follows it."""

    @pytest.mark.asyncio
    async def test_zoom_fills_the_screen_with_the_focused_pane(
        self, control_service: _JobService
    ) -> None:
        control_service.log_lines = [_APP_ERROR_LINE]
        app = _app(control_service, [_job("abc123def456")])
        async with app.run_test(size=_WIDE, notifications=True) as pilot:
            await _ready(pilot, app)
            table = app.query_one("#jobs")
            assert app.focused is table, "the table takes the keyboard first"

            await pilot.press("z")
            await pilot.pause()
            zoomed_table = app.screen.maximized

            await pilot.press("z")
            await pilot.pause()
            restored = app.screen.maximized

            await pilot.press("tab")
            await pilot.pause()
            focused_after_tab = app.focused

            await pilot.press("z")
            await pilot.pause()
            zoomed_log = app.screen.maximized
            painted = _screen_text(app)

        assert zoomed_table is table, "z grows the pane holding the keyboard"
        assert restored is None, "z again gives the split back"
        assert isinstance(focused_after_tab, JobsLogView), (
            "tab hands the keyboard to the log pane"
        )
        assert zoomed_log is not None
        assert zoomed_log.id == "logpane", (
            "the zoom takes the pane with its title bar, not the bare widget"
        )
        assert "reindex_failed" in painted, "the zoomed log still shows its lines"
        assert "code index refresh" not in painted, (
            "the table yields the screen while the log is zoomed"
        )


class TestFormattedRendering:
    """What the operator reads is fields, not dumps."""

    @pytest.mark.asyncio
    async def test_each_dialect_renders_as_its_fields(
        self, control_service: _JobService
    ) -> None:
        # A short backend path, so the request summary fits the pane on one
        # line and the arrow assertion is not split across a wrap point.
        qdrant_line = (
            "2026-07-28T12:23:49.079022Z  INFO actix_web::middleware::logger: "
            '127.0.0.1 "PUT /collections/docs/index HTTP/1.1" 200 91 "-" '
            '"python-client/1.18.0 python/3.13.11" 0.009050'
        )
        control_service.log_lines = [
            _APP_ERROR_LINE,
            qdrant_line,
            _ACCESS_SIGNAL_LINE,
            "a completely unstructured line",
        ]
        app = _app(control_service, [_job("abc123def456")])
        async with app.run_test(size=_WIDE, notifications=True) as pilot:
            await _ready(pilot, app)
            painted = await _await_painted(pilot, app, "reindex_failed")

        assert "pending_paths=7" in painted, "the event's detail is on screen"
        assert "9ms" in painted, "the backend request's timing is legible"
        assert "→ 200" in painted, "the status is lifted out of the quotes"
        assert "→ 202 Accepted" in painted
        assert "a completely unstructured line" in painted, (
            "a line no dialect claims is shown as it stands, never dropped"
        )
        assert '" 200 91 "-"' not in painted, (
            "the raw quoted request dump must be gone from the formatted view"
        )


class TestHandlerFormattedAccessRecords:
    """Access records that reach the log through the service's own handler.

    The daemon declines the HTTP server's private log configuration, so its
    access records arrive timestamped and logger-tagged rather than in the
    server's own bare format. Read as ordinary application records they carry
    the server's INFO level, which would quietly cost this pane both its
    request fields and its ability to find a failed request.
    """

    def test_a_failed_request_is_still_an_error(self) -> None:
        entry = parse_log_line(
            "2026-07-29 13:01:17,110 INFO     uvicorn.access: "
            '127.0.0.1:49742 - "GET /search HTTP/1.1" 500'
        )

        assert entry.kind == "access"
        assert entry.is_error, "a 5xx must stay findable by the pane's error jump"
        assert entry.method == "GET"
        assert entry.path == "/search"
        assert entry.status == "500"
        assert entry.timestamp == "13:01:17"

    def test_a_polled_read_is_still_collapsible(self) -> None:
        entry = parse_log_line(
            "2026-07-29 13:01:15,339 INFO     uvicorn.access: "
            '127.0.0.1:49742 - "GET /jobs?limit=20 HTTP/1.1" 200'
        )

        assert entry.kind == "access"
        assert entry.is_polling
        assert not entry.is_error

    def test_a_mutation_is_never_collapsed(self) -> None:
        entry = parse_log_line(
            "2026-07-29 13:01:15,551 INFO     uvicorn.access: "
            '127.0.0.1:49742 - "POST /jobs HTTP/1.1" 201'
        )

        assert entry.kind == "access"
        assert not entry.is_polling, "a write to a polled route is not a poll"
        assert entry.method == "POST"

    def test_an_unparseable_tail_stays_an_application_record(self) -> None:
        """A record from that logger that is not a request is not invented into one."""
        entry = parse_log_line(
            "2026-07-29 13:01:15,551 INFO     uvicorn.access: something else entirely"
        )

        assert entry.kind == "app"
        assert entry.method is None

"""The watch's header: what it counts, and how it says the service is doing.

One mixin rather than a module of functions, because every method here reads
the app's own lanes - the jobs page, the served-search tallies, the machine
signals, the reported version - and composing a header from arguments would
mean threading all of them through every call.

Split from the app because rendering the header is not part of driving it: no
method here fetches, mutates a lane, or answers a keypress. They read what the
lanes already hold and return the line that describes it.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, cast

from rich.text import Text
from textual.widgets import Static

from ..jobs import count, measurement
from ..service_quiesce import QuiesceState
from ._cli_format import compact_duration
from ._jobs_tui_cells import (
    CONDITION_ORDER,
    CONDITION_TONES,
    append_pill,
    short_id,
    widest_line,
)
from ._jobs_tui_constants import (
    GROUP_SEPARATORS,
    HEALTH_PILLS,
    OTHER_PILL_GLYPHS,
    STATE_PILLS,
    SUMMARY_BUCKETS,
)
from ._jobs_tui_palette import pill_fill, semantic_tones, tone_style
from ._service_jobs_presentation import (
    degradation_evidence_lines,
    degradation_verdict,
)

if TYPE_CHECKING:
    from textual.app import App

    _MixinBase = App[None]
else:
    _MixinBase = object

if TYPE_CHECKING:
    from ._jobs_tui_state import (
        MachineSignals,
        SearchActivityState,
        ServiceVersion,
    )


class HeaderRenderingMixin(_MixinBase):
    """Composes the watch's header and summary from the lanes the app holds.

    Declares the lane state it reads so the mixin type-checks on its own terms
    rather than only once mixed in. The application owns every one of these;
    nothing here assigns to them.
    """

    _interval: float
    _jobs: list[dict[str, object]]
    _last_error: str | None
    _last_outcome: tuple[str, str] | None
    _last_refresh: float | None
    _port: int
    _search: SearchActivityState
    _service_estimates: bool
    _signals: MachineSignals
    _summary: object
    _total: int | None
    _version: ServiceVersion
    _watch_mode: str

    if TYPE_CHECKING:
        # Provided by the application this mixes into. Declared, not defined:
        # the block never runs, so the real implementations are the ones found
        # at runtime.
        def _header_glyph(self) -> str: ...

        def selected_job(self) -> dict[str, object] | None: ...

    def _header_counts(self) -> list[tuple[str, int]]:
        """Count what the service holds, not what fits on the page.

        The service tallies every record matching the filter; the page is at
        most twenty of them. Re-tallying the page produces numbers that
        describe neither the list nor the service and that do not move when
        anything outside the page changes - so a deletion from a
        two-hundred-record history shows nowhere at all.

        The residue is named rather than dropped. Counters that quietly omit
        every state they have no bucket for sum to nothing in particular, and
        an operator cannot tell a missing state from a zero one.
        """
        summary = self._summary
        if isinstance(summary, dict):
            counted = cast("dict[str, object]", summary)
            counts = [
                (label, count(counted.get(key)) or 0) for label, key in SUMMARY_BUCKETS
            ]
            tallied = sum(tally for _label, tally in counts)
            scope = self._total if self._total is not None else tallied
        else:
            states = [str(job.get("state", "")) for job in self._jobs]
            counts = [(label, states.count(key)) for label, key in SUMMARY_BUCKETS]
            scope = len(self._jobs)
        other = scope - sum(tally for _label, tally in counts)
        if other > 0:
            counts.append(("other", other))
        return counts

    def _unicode_glyphs(self) -> bool:
        """Whether the console's encoding can carry the pill glyphs."""
        encoding = str(getattr(self.console, "encoding", "") or "")
        return "utf" in encoding.lower()

    def _append_separator(self, line: Text, *, unicode_ok: bool) -> None:
        """A dim divider, so each header group reads as its own cell run."""
        glyph, fallback = GROUP_SEPARATORS
        line.append("  ")
        line.append(glyph if unicode_ok else fallback, style="dim")
        line.append(" ")

    def _append_state_pills(
        self,
        line: Text,
        fills: dict[str, tuple[str, str]],
        *,
        labelled: bool,
        unicode_ok: bool,
    ) -> None:
        """One pill per state bucket: glyph, count, and (wide) its label.

        A pill with work in it wears its token's solid fill; an empty one
        wears the muted fill so colour always means signal.
        """
        for key, tally in self._header_counts():
            spec = STATE_PILLS.get(key)
            if spec is None:
                # The residue bucket, in the same anatomy as its neighbours.
                glyph, fallback = OTHER_PILL_GLYPHS
                label, tone = key, "muted"
            else:
                glyph, fallback, label, tone, _bold = spec
            content = f"{glyph if unicode_ok else fallback} {tally}"
            if labelled:
                content += f" {label}"
            # One cell of air: the caps already separate pill from pill.
            line.append(" ")
            append_pill(
                line,
                content,
                fills[tone if tally else "muted"],
                unicode_ok=unicode_ok,
            )

    def _append_health_pills(
        self,
        line: Text,
        fills: dict[str, tuple[str, str]],
        *,
        labelled: bool,
        unicode_ok: bool,
        lead_separator: bool = True,
    ) -> None:
        """The service's job-health tallies, in their own group."""
        summary = self._summary
        if not isinstance(summary, dict):
            return
        counted = cast("dict[str, object]", summary)
        present = [spec for spec in HEALTH_PILLS if spec[0] in counted]
        if not present:
            # A daemon older than the tally; absent is not zero.
            return
        if lead_separator:
            self._append_separator(line, unicode_ok=unicode_ok)
        for index, (key, glyph, fallback, label, tone, _bold) in enumerate(present):
            tally = count(counted.get(key)) or 0
            content = f"{glyph if unicode_ok else fallback} {tally}"
            if labelled:
                content += f" {label}"
            if index:
                line.append(" ")
            append_pill(
                line,
                content,
                fills[tone if tally else "muted"],
                unicode_ok=unicode_ok,
            )

    def _append_search_activity(self, line: Text, tones: dict[str, str]) -> None:
        """Keep served-search lane counts visible even when narrow hides its table."""
        self._append_separator(line, unicode_ok=self._unicode_glyphs())
        if self._search.error is not None:
            line.append("search unavailable", style=tone_style(tones, "bad", bold=True))
            return
        if self._search.last_refresh is None:
            line.append("search loading", style="dim")
            return
        active = self._search.counts.get("active", 0)
        recent = self._search.counts.get("recent", 0)
        line.append(
            f"search {active} active · {recent} recent",
            style=tone_style(tones, "good", bold=active > 0),
        )

    def _service_condition(self) -> str:
        """The service's condition verdict for the header pill.

        Reachability first, then the worst active degradation verdict the
        service has stamped - taken from the service's own tally where the
        summary carries one, from the stamped records on the page otherwise.
        Nothing is computed here; the service is the authority on both.
        """
        if self._last_error is not None:
            return "unreachable"
        summary = self._summary
        if isinstance(summary, dict):
            counted = cast("dict[str, object]", summary)
            if "stalled" in counted or "degraded" in counted:
                if count(counted.get("stalled")):
                    return "stalled"
                if count(counted.get("degraded")):
                    return "degraded"
                return "healthy"
        stamped = [
            verdict
            for verdict in (degradation_verdict(job) for job in self._jobs)
            if isinstance(verdict, str) and verdict in CONDITION_ORDER
        ]
        if not stamped:
            # An older daemon stamps no verdicts; reachable is all it claims.
            return "reachable"
        return max(stamped, key=CONDITION_ORDER.index)

    def _gpu_cell(self) -> tuple[str, str, bool]:
        """The GPU pressure cell as (text, tone, bold), honest about absence.

        Never fake numbers: a daemon that does not send the block renders as
        a muted dash, and one that probed an unmeasurable host as ``n/a``.
        The tone shift at high pressure is presentation only; any verdict
        about what the pressure means stays with the service.
        """
        if not self._signals.gpu_reported:
            return "gpu —", "muted", False
        gpu = self._signals.gpu or {}
        utilization = measurement(gpu.get("utilization_percent"))
        used = measurement(gpu.get("memory_used_mib"))
        total = measurement(gpu.get("memory_total_mib"))
        parts: list[str] = []
        pressure = 0.0
        if utilization is not None:
            parts.append(f"{utilization:.0f}%")
            pressure = max(pressure, utilization / 100.0)
        if used is not None and total is not None and total > 0:
            parts.append(f"{used / 1024:.1f}/{total / 1024:.1f}G")
            pressure = max(pressure, used / total)
        if not parts:
            return "gpu n/a", "muted", False
        if pressure >= 0.9:
            return f"gpu {' '.join(parts)}", "bad", True
        if pressure >= 0.75:
            return f"gpu {' '.join(parts)}", "attention", False
        return f"gpu {' '.join(parts)}", "good", False

    def _pressure_cell(self) -> tuple[str, str] | None:
        """The machine pressure pill as (text, tone), or nothing to show.

        Three answers, the same three the plain feed gives, so the two
        surfaces can never disagree: a daemon that sends no tier says
        nothing, a nominal tier is the healthy steady state and says
        nothing either, and any other tier is a verdict an operator must
        see. Silence is not a claim of health - the condition and GPU cells
        still report - and it keeps the steady-state header at the width it
        already had, so a pill nobody needs never costs a label somebody
        does. The tier is rendered verbatim: a tier this build has no tone
        for is still shown, because a newer daemon naming a worse state
        must never be swallowed.
        """
        tier = (self._signals.pressure or {}).get("tier")
        if not isinstance(tier, str) or tier in ("", "nominal"):
            return None
        return f"pressure {tier}", "bad" if tier == "critical" else "attention"

    def _quiesce_cell(self) -> tuple[str, str] | None:
        """The controller-evidence pill as (text, tone), or nothing to show.

        Only service-reported evidence is rendered, never authority: this
        client repairs no block it was sent and derives no permission from
        one. What it does decide is whether the evidence is news, on the same
        rule the pressure pill keeps. A daemon that reports no controller
        block has made no observation, and a controller that is running, is
        holding its VRAM and has admitted no borrower is the steady state an
        operator already assumes; neither earns a cell, because a pill nobody
        needs never costs a label somebody does. Silence here is never a
        claim of safety - it is only the absence of a claim - and the detail
        row states the controller's whole answer on every render, absent,
        foreign or canonical alike, so nothing is lost by staying quiet.

        Everything else is news, and news is never shed and never abbreviated.
        A block this build cannot read is a contradiction between a daemon
        that owns a controller and a report nothing may be trusted from, so
        it is the loud tone rather than the muted one. Any other state, any
        released VRAM and any admitted borrower is exactly the window in
        which an operator needs all three facts at once.
        """
        if not self._signals.quiesce_reported:
            return None
        match self._signals.quiesce:
            case {
                "state": str(state),
                "vram_released": bool(vram_released),
                "safe_to_borrow_gpu": bool(safe_to_borrow_gpu),
            }:
                if (
                    state == QuiesceState.RUNNING
                    and not vram_released
                    and not safe_to_borrow_gpu
                ):
                    return None
                vram = "released" if vram_released else "held"
                safety = "safe" if safe_to_borrow_gpu else "unsafe"
                tone = "good" if safe_to_borrow_gpu else "attention"
                return f"quiesce {state} · vram {vram} · borrower safety {safety}", tone
            case _:
                return "quiesce unavailable", "bad"

    def _append_quiesce_detail(self, line: Text, tones: dict[str, str]) -> None:
        """State the controller's whole answer on its own unbounded row.

        The header pill is a summary that speaks only when the controller has
        news; this row is where the answer is readable whatever it is, so it
        is the one that carries an absence the pill does not paint. Both ways
        an answer can go missing read as ``quiesce unavailable`` and differ
        only in the reason given, because they leave an operator in the same
        position and one condition must not wear two names.
        """
        if self._signals.quiesce is not None:
            line.append("\nquiesce details: ", style="dim")
            line.append(str(self._signals.quiesce), style="dim")
        elif self._signals.quiesce_reported:
            line.append(
                "\nquiesce unavailable: invalid service response",
                style=tone_style(tones, "bad", bold=True),
            )
        else:
            line.append(
                "\nquiesce unavailable: no controller evidence reported",
                style="dim",
            )

    def _compose_header_line(
        self,
        tones: dict[str, str],
        *,
        state_labels: bool,
        health_labels: bool,
        split_before_service: bool = False,
        split_before_health: bool = False,
    ) -> Text:
        """Build the header row: grouped pills, condition, GPU, page count.

        The groups - state pills, health tallies, service condition, GPU, the
        exception cells, and the page count - are divided by dim separators so
        the row reads as cells rather than one cramped run. Labels are a width
        decision made by the caller; the condition and GPU cells are never
        dropped, and neither is an exception cell on the occasions it has
        something to report at all.
        ``split_before_service`` is the last width fallback: the row breaks
        deliberately at the service-group boundary instead of wherever the
        wrapper would land - never through the middle of a pill.
        """
        unicode_ok = self._unicode_glyphs()
        # The leading cell is identity: which daemon, at which release, on
        # which port. Identity is not signal, so it carries no semantic
        # tone - the version is the connected daemon's own report, and an
        # answering daemon that predates the field reads as unknown rather
        # than being filled from the local package.
        line = Text(f"{self._header_glyph()} vaultspec-rag", style="bold")
        if self._version.value:
            line.append(f" {self._version.value}")
        elif self._version.checked:
            line.append(" v?", style=tone_style(tones, "muted"))
        line.append(" · ", style="dim")
        line.append(f"port {self._port}", style="bold")
        fills = pill_fill(self.theme)
        self._append_state_pills(
            line, fills, labelled=state_labels, unicode_ok=unicode_ok
        )
        if split_before_health:
            line.append("\n")
        self._append_health_pills(
            line,
            fills,
            labelled=health_labels,
            unicode_ok=unicode_ok,
            lead_separator=not split_before_health,
        )
        if self._watch_mode == "server":
            self._append_search_activity(line, tones)
        if split_before_service:
            line.append("\n")
        else:
            self._append_separator(line, unicode_ok=unicode_ok)
        verdict = self._service_condition()
        condition_tone, _bold = CONDITION_TONES[verdict]
        append_pill(
            line,
            f"{'●' if unicode_ok else '*'} svc {verdict}",
            fills[condition_tone],
            unicode_ok=unicode_ok,
        )
        self._append_separator(line, unicode_ok=unicode_ok)
        quiesce_cell = self._quiesce_cell()
        if quiesce_cell is not None:
            quiesce_text, quiesce_tone = quiesce_cell
            append_pill(
                line,
                quiesce_text,
                fills[quiesce_tone],
                unicode_ok=unicode_ok,
            )
            self._append_separator(line, unicode_ok=unicode_ok)
        gpu_text, gpu_tone, _gpu_bold = self._gpu_cell()
        append_pill(line, gpu_text, fills[gpu_tone], unicode_ok=unicode_ok)
        pressure_cell = self._pressure_cell()
        if pressure_cell is not None:
            pressure_text, pressure_tone = pressure_cell
            self._append_separator(line, unicode_ok=unicode_ok)
            append_pill(
                line, pressure_text, fills[pressure_tone], unicode_ok=unicode_ok
            )
        self._append_separator(line, unicode_ok=unicode_ok)
        shown = len(self._jobs)
        if self._total is None:
            line.append(f"showing {shown}")
        else:
            # A page onto a longer list is marked, because every count above
            # is a count of the page rather than of the service's work - and
            # because it is the only place a deletion shows when the freed
            # slot is immediately backfilled from the remainder.
            line.append(
                f"showing {shown} of {self._total}",
                style=tone_style(tones, "attention", bold=True)
                if self._total > shown
                else "",
            )
        return line

    def _summary_width(self) -> int:
        """The header bar's content width, or zero before its first layout."""
        found = self.query("#summary")
        if not found:
            return 0
        return found.only_one(Static).content_size.width

    def _render_summary(self) -> None:
        tones = semantic_tones(self.theme)
        width = self._summary_width()
        # Widest fitting form wins: labels leave the state pills first, then
        # the health tallies. Counts, the condition and the GPU cell are
        # never shed, and neither are the quiesce and pressure pills on the
        # occasions they are painted at all - a cell that only speaks when it
        # has news has already paid for the width it takes, and shedding it
        # would hide the very thing it was painted to say; past the narrowest
        # form the bar wraps.
        line = self._compose_header_line(tones, state_labels=True, health_labels=True)
        if 0 < width < widest_line(line):
            line = self._compose_header_line(
                tones, state_labels=False, health_labels=True
            )
        if 0 < width < widest_line(line):
            line = self._compose_header_line(
                tones, state_labels=False, health_labels=False
            )
        if 0 < width < widest_line(line):
            # Narrower than even the unlabelled row: break it deliberately
            # at the service-group boundary, never through a pill.
            line = self._compose_header_line(
                tones,
                state_labels=False,
                health_labels=False,
                split_before_service=True,
            )
        if 0 < width < widest_line(line):
            # Still too narrow: the health group takes its own row too, so
            # every row of the header holds whole groups of whole pills.
            line = self._compose_header_line(
                tones,
                state_labels=False,
                health_labels=False,
                split_before_service=True,
                split_before_health=True,
            )
        # The age of the data is reported whether or not the last fetch
        # failed - it is exactly when the service stops answering that an
        # operator needs to know how old what they are reading is. Suppressing
        # it on the error branch leaves stale rows on screen with nothing
        # saying they are stale.
        if self._last_refresh is None:
            line.append("\nloading", style="dim")
        else:
            stamp = time.strftime("%H:%M:%S", time.localtime(self._last_refresh))
            age = time.time() - self._last_refresh
            line.append(f"\nrefreshed {stamp}", style="dim")
            if age > max(5.0, self._interval * 3):
                line.append(
                    f" ({compact_duration(age)} ago)",
                    style=tone_style(tones, "attention", bold=True),
                )
        if self._last_error is not None:
            line.append(
                f"  ·  {self._last_error}",
                style=tone_style(tones, "bad", bold=True),
            )
        if not self._service_estimates:
            # Said once in the header rather than implied by every row's
            # empty estimate, which reads as unmeasurable work instead of
            # an older daemon.
            line.append("  ·  this service does not report time estimates", style="dim")
        if self._last_outcome is not None:
            text, token = self._last_outcome
            line.append(f"\n{text}", style=tone_style(tones, token, bold=True))
        self._append_selected_degradation(line, tones)
        self._append_quiesce_detail(line, tones)
        summary = self.query("#summary")
        if summary:
            summary.only_one(Static).update(line)

    def _append_selected_degradation(self, line: Text, tones: dict[str, str]) -> None:
        """Show the selected job's unhealthy verdict and evidence in the header.

        The verdict and every finding come verbatim from the service payload
        through the same presentation helpers the CLI detail view renders -
        the header is the one place this view has room for whole sentences,
        and the row's own progress cell already carries the short form.
        """
        job = self.selected_job()
        if job is None:
            return
        verdict = degradation_verdict(job)
        if verdict is None or verdict == "healthy":
            return
        line.append(
            f"\n{short_id(job)} {verdict}", style=tone_style(tones, "bad", bold=True)
        )
        evidence = "  ·  ".join(degradation_evidence_lines(job))
        if evidence:
            line.append(f"  ·  {evidence}", style=tone_style(tones, "bad"))

    # -- selection and logs -------------------------------------------------

"""Fixed tables the jobs watch renders and reasons from.

Column weights, action vocabularies, pill glyph sets, summary buckets. They
are gathered here because the app, the cell renderers and the payload readers
all consult them, and a constant reached from three modules should be defined
in none of them.
"""

from __future__ import annotations

from ..job_models import DesiredJobState, JobState

#: Service codes meaning the record a row names is already gone.
GONE_CODES = frozenset({"job_not_found", "not_found"})

# Columns are laid out by relative weight, never by a fixed size: the table
# divides whatever width the terminal reports among these shares, so the same
# composition fills an 80-column shell and a 300-column one. The path column
# carries the largest share because it holds the longest value and is the one
# an operator most needs to read whole.
COLUMN_WEIGHTS: dict[str, float] = {
    # The state column carries the widest short string the view can show -
    # a pending control such as "pause requested" - so its share is set by
    # that, not by the header word.
    "state": 3.0,
    "job": 3.0,
    "path": 4.5,
    "progress": 3.5,
    "time": 2.0,
}
# A column narrower than this cannot show even a truncated value, so the
# division floors here rather than collapsing a column to nothing.
MIN_COLUMN_CELLS = 8
# The width at or above which two panes side by side are both still readable.
# Below it the layout shows one at a time instead of shrinking both.
SPLIT_MIN_CELLS = 110

# The search ledger itself is bounded by the service. This is the bounded
# operator page this screen asks it to project, independent from job and log
# refresh limits.
SEARCH_ACTIVITY_LIMIT = 100

SEARCH_COLUMN_WEIGHTS: dict[str, float] = {
    "state": 2.5,
    "request": 3.0,
    "query": 4.0,
    "time": 2.5,
}

# Action name -> (capability flag the service publishes, desired state).
# ``None`` marks an action that is not a desired-state transition.
STATE_ACTIONS: dict[str, tuple[str, DesiredJobState]] = {
    "pause": ("pausable", DesiredJobState.PAUSED),
    "resume": ("resumable", DesiredJobState.RUNNING),
    "stop": ("cancellable", DesiredJobState.CANCELLED),
}
PLAIN_ACTIONS: dict[str, str] = {"retry": "retryable", "delete": "deletable"}

# Derived from the canonical enum rather than listed again here, so a state
# added there cannot quietly start reading as non-terminal in this view.
TERMINAL_STATES = frozenset(state.value for state in JobState if state.is_terminal)

# Estimate fields a service older than this view does not publish at all.
# Absent is not the same answer as present-and-null: null is the service
# declining to estimate this job, absent is a service that never estimates.
# Reading them the same way would tell an operator their jobs are all
# unmeasurable when the truth is that their daemon predates the measurement.
ESTIMATE_KEY = "estimated_remaining_seconds"

# Key -> action, so a press that lands on an unavailable action can be
# answered. A disabled binding never invokes its action, so without this the
# only signal is a greyed footer entry, and an operator pressing the key gets
# silence - which reads as a broken interface rather than a refused request.
ACTION_KEYS: dict[str, str] = {
    "p": "job_pause",
    "u": "job_resume",
    "k": "job_stop",
    "y": "job_retry",
    "d": "job_delete",
    "x": "log_noise",
    "n": "log_next_error",
    "N": "log_prev_error",
    "g": "log_top",
    "G": "log_end",
    "f": "log_expand",
}

# Why each action is unavailable, in the operator's terms rather than the
# capability flag's.
ACTION_REASONS: dict[str, str] = {
    "job_pause": "Only running work can be paused.",
    "job_resume": "Only paused work can be resumed.",
    "job_stop": "Only running work can be cancelled.",
    "job_retry": "Only a finished or failed job can be retried.",
    "job_delete": "Only a finished or failed job can be deleted.",
    "log_next_error": "This log has no error entries.",
    "log_prev_error": "This log has no error entries.",
}

# What every log action answers with while the pane is closed. The keys must
# not go dead just because the pane is not on screen.
LOG_CLOSED_REASON = "The log pane is closed - press l to open it."

# Header counters, as (label, the canonical state they count). The service
# tallies these over every record matching the filter; the same names index
# both its summary and a record's own ``state``, so the fallback tally of the
# page on screen is the same reading of the same field.
SUMMARY_BUCKETS: tuple[tuple[str, str], ...] = (
    ("running", "running"),
    ("queued", "queued"),
    ("paused", "paused"),
    ("failed", "failed"),
    ("succeeded", "succeeded"),
)

# Header pills. One anatomy for every pill - glyph, count, then (width
# permitting) a label - so no cell has to be decoded differently from its
# neighbours, and the glyph is never the only signal. Tone is one mapping
# across the whole header: good, attention, bad, neutral, muted - and a
# pill's tone drops to muted at zero so colour always means signal. The
# ASCII fallback carries the same meaning on a terminal that cannot paint
# the glyph, and moves with the glyph whenever one changes.
#
# The glyph families keep the categories apart at a glance: activity states
# use playback marks (▶ run, ⋯ queued, ‖ paused) and outcome marks (✖ ✓),
# while the job-health tallies use an escalating warning-triangle family
# (△ hollow for degraded, ▲ solid for stalled) that cannot be misread as a
# state.
STATE_PILLS: dict[str, tuple[str, str, str, str, bool]] = {
    # state -> (glyph, ASCII fallback, label, tone, bold)
    "running": ("▶", ">", "running", "good", True),
    "queued": ("⋯", "..", "queued", "neutral", False),
    "paused": ("‖", "||", "paused", "neutral", False),
    "failed": ("✖", "x", "failed", "bad", True),
    "succeeded": ("✓", "v", "succeeded", "good", False),
}
# The residue bucket for states without a pill of their own; the label is
# the state name the tally reported.
OTHER_PILL_GLYPHS = ("□", "?")

# Job-health tallies the service publishes beside the state counts. Shown
# only when the summary carries the key: a daemon older than the tally is
# absent, not zero.
HEALTH_PILLS: tuple[tuple[str, str, str, str, str, bool], ...] = (
    # key -> (glyph, ASCII fallback, label, tone, bold)
    ("degraded", "△", "!", "degraded", "attention", False),
    ("stalled", "▲", "!!", "stalled", "bad", True),
)

# The dim divider between header groups: states, health, service, GPU, and
# the page count each read as their own cell run rather than one cramped row.
GROUP_SEPARATORS = ("│", "|")

# Rounded end-caps for the pills: half-circle glyphs painted in the pill's
# own fill colour, so a background-filled span reads as an actual pill
# rather than a hard-edged block. On a console whose encoding cannot carry
# them, the pill degrades to a space-padded filled span - soft, bracket
# free, and still a pill.
PILL_CAP_LEFT = "\ue0b6"
PILL_CAP_RIGHT = "\ue0b4"

# The blank cell that joins a pill's words. It is a glyph, not whitespace:
# both text wrappers on this path break at any Unicode whitespace - the
# no-break space included - so only a non-space blank keeps a pill in one
# piece at every width. It renders as an empty cell in the same braille
# block the busy spinner already draws from.
PILL_JOINER = "\u2800"

#: How many log lines the watch asks for in one fetch.
LOG_LINES = 200

#: Worker group every job control runs in, so one cancels the last.
CONTROL_GROUP = "jobs-control"

#: Worker groups: one fetch per pane at a time, so a new one cancels the last.
LOG_GROUP = "jobs-log"
MANAGED_LOG_GROUP = "managed-log-refresh"

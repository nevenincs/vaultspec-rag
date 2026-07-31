---
tags:
  - '#adr'
  - '#encode-liveness-coupling'
date: '2026-07-31'
modified: '2026-07-31'
body_schema: 'body-v1'
related:
  - '[[2026-07-31-issue-triage-research]]'
  - '[[2026-07-29-gpu-admission-gate-adr]]'
  - '[[2026-07-28-index-observability-adr]]'
  - '[[2026-07-28-pressure-management-adr]]'
---

# `encode-liveness-coupling` adr: `starved is distinguishable from gone on facts already published` | (**status:** `proposed`)

## Problem Statement

During the 2026-07-29 GPU-contention incident (GitHub issue 308) the service
produced two simultaneously correct, opposite verdicts. `/health` answered 200
`ready` from the event loop throughout while every real query starved behind the
blocked encode; discovery judged a heartbeat the daemon had stopped writing, and
once its age passed the 60-second window
(`src/vaultspec_rag/serviceclient/_discovery.py:66`) the operator surface reported
`crashed (heartbeat stale)` and the CLI refused every query with "no running
service", because a stale pointer refuses to hand out the address at all
(`src/vaultspec_rag/serviceclient/_discovery.py:728-737`, `:788-796`). The daemon
was alive, listening, and answering HTTP the whole time.
`2026-07-31-issue-triage-research` records that the admission-gate half of the
issue shipped separately and this observability half - the part that made the
incident take hours to see - is untouched. The decision needed: which facts
distinguish a starved daemon from a gone one, which surface owns each verdict,
and what a broker may conclude from them.

## Considerations

- Discovery already possessed the exculpatory evidence at the moment it declared
  death: the verdict ladder probes pid liveness, token-confirmed identity, and
  the listening port before it reads heartbeat age
  (`src/vaultspec_rag/serviceclient/_status.py:226-259`); all three passed during
  the incident, and the ladder then collapsed `heartbeat_stale` into the same
  `crashed` family as a dead pid.
- The probe quadruple is already implemented in the status adapter: pid alive,
  token-confirmed HTTP identity, TCP accept, heartbeat age
  (`src/vaultspec_rag/cli/_status_render.py:146-178`; `LivenessSignals` at
  `src/vaultspec_rag/serviceclient/_status.py:89-104`).
- A per-job forward-pass age is already published: the forward window is written
  before the pass begins precisely so a minutes-long pass under contention is
  visible (`src/vaultspec_rag/jobs.py:789-818`), and it is shaped into
  `age_seconds`, `in_flight`, and `thread_alive`
  (`src/vaultspec_rag/jobs.py:1197-1235`). The accepted
  `2026-07-28-index-observability-adr` owns that telemetry and the three-way
  per-job verdict (`src/vaultspec_rag/server/_routes_jobs.py:427-474`, thresholds
  at `src/vaultspec_rag/_job_errors.py:36-46`). The canonical-code discipline
  forbids a second implementation of either.
- `/health` is not a pure ping today: it already computes `degraded` from
  registry, qdrant, and a jobs rollup - but that rollup consumes only the
  300-second hard `stalled` count and generation-scoped failures
  (`src/vaultspec_rag/server/_lifespan.py:1147-1192`), never the 60-second
  encode-path `degraded` verdict, so a starved forward keeps `/health` green for
  five minutes and a starved-but-still-ticking run keeps it green indefinitely.
- A health poll must stay cheap and never probe the backend
  (`src/vaultspec_rag/service.py:2093-2108`); the GPU discipline forbids any
  probe path from taking the GPU lock or initialising CUDA.
- The service-surface discipline puts verdicts in the service domain with
  adapters rendering them; the composition/probing split already exists
  (`compose_discovery_status` versus the adapter probes above).
- The operator-status vocabulary already reserves a degraded family for
  "singleton held, the daemon may well be serving fine"
  (`src/vaultspec_rag/serviceclient/_status.py:29-39`) - the starved verdict has
  a home.
- The incident's own timeline undercuts writer-side fixes: `last_heartbeat`
  froze at 09:16Z while job progress continued to 11:14Z, so the heartbeat
  freeze preceded the starvation by two hours and its cause is not established.
  The verdict must be robust to a frozen heartbeat of any cause, which points at
  reader-side facts, not at making the writer more honest.
- The GPU admission gate is decided elsewhere and is not re-opened here
  (`2026-07-29-gpu-admission-gate-adr`); the observe-only-first stance - report a
  verdict, let nothing act on it until it has earned trust - is established
  (`2026-07-28-pressure-management-adr`).
- The storage discipline's rejection of restart-if-degraded branches applies
  with equal force to liveness: an observability surface must not grow a
  remediation arm.

## Considered options

Health surface shape:

- **`/health` keeps its cheap-rollup shape; the encode-path verdict feeds its
  degraded reasons (chosen).** The already-computed per-job `degraded`/`stalled`
  verdict - which reads `forward.age_seconds` - becomes a degraded reason on
  `/health`, so the rollup moves within 60 seconds of a starved forward. No new
  probe, no new numeral.
- **`/health` as a pure liveness ping, with the distinction living only in
  status.** Rejected: `/health` already rolls up degradation, so "pure ping"
  would be a regression, not a simplification; and it is the one indicator
  supervisors poll - leaving it blind to this incident class preserves the
  defect.
- **A canary encode per health poll.** Rejected: a real encode serialises on the
  GPU lock behind the very forward that is starving, so the poll hangs exactly
  when it is needed; it also violates the GPU discipline and the
  health-never-probes contract.

Starved-versus-gone signal:

- **The fact quadruple discovery already probes (chosen).** Starved: heartbeat
  age exceeds the payload-carried `stale_after_s` while the recorded pid is
  alive, the port accepts, and the token-confirmed HTTP probe answers with the
  matching service token. Gone: any of pid dead, PID reused, port silent, or
  probe unanswered. Zero new probes, zero new constants.
- **The daemon publishes forward-pass age into the discovery file on each
  beat.** Rejected: the heartbeat is the failing writer; a frozen writer cannot
  testify about itself, and in the incident it froze two hours before the
  starve.
- **An independent watchdog thread writing its own beat.** Rejected: a second
  liveness publication that keeps beating over a dead event loop masks real
  deadness, and duplicates the publication the heartbeat owns.
- **A new starved-specific threshold.** Rejected: `stale_after_s` (60 s) and
  `DEGRADED_THRESHOLD_SECONDS` (60 s) exist and fit; a third numeral is
  calibration surface carrying no new information.

Discoverability of a starved daemon:

- **Stays discoverable, flagged (chosen).** A stale pointer whose holder is live
  and whose pointer pid matches the holder is handed out with the degraded
  verdict attached rather than refused; clients attempt queries under their
  existing bounded timeouts, and a failure while flagged reports the starved
  verdict instead of "no running service".
- **Keep refusing the address (today's behaviour).** Rejected: refusal converts
  degradation into a fabricated total outage and invites the operator to start
  a second daemon that can only lose the singleton race - the status vocabulary
  itself warns of exactly this.

Verdict-to-action coupling:

- **Report only; remediation stays manual (chosen).** No path restarts, kills,
  pauses, or drains a starved daemon.
- **Restart-if-starved.** Rejected: the restart-if-degraded shape is forbidden
  in maintenance for reasons that transfer wholesale - a wrong verdict plus an
  automatic arm turns transient contention into a self-inflicted outage, and a
  restart under GPU contention forfeits resident models for a full reload into
  the same contention.

## Constraints

- Verdict composition stays service-domain (`compose_discovery_status`);
  pid/port/token probing stays in the adapter layer. No CLI- or MCP-only
  verdict, no entry point owning a phase the service does not.
- Every probe on these paths remains torch-free and GPU-lock-free; the forward
  fact is read from the jobs registry, never sampled fresh.
- The forward-evidence shaping and the per-job degradation verdict remain the
  single implementations of the encode-path fact and its classification; this
  record adds consumers, not copies.
- `stale_after_s` remains payload-carried so mixed-release readers keep judging
  by the writing daemon's window
  (`src/vaultspec_rag/serviceclient/_discovery.py:419-427`).
- Parent stability: the forward telemetry and per-job verdict are accepted and
  landed (`2026-07-28-index-observability-adr`); the admission gate
  (`2026-07-29-gpu-admission-gate-adr`) is neither depended on nor re-decided.
  The heartbeat writer, its 15-second interval
  (`src/vaultspec_rag/server/_state.py:120`), and the staleness window are
  unchanged.
- The implementation cites nothing back to this record or any vault document.

## Implementation

Three layers, each consuming a fact the layer below already publishes.

**Jobs to health.** The `/health` jobs rollup gains the encode-path verdict: a
running job whose service-domain verdict is `degraded` or `stalled` contributes
a degraded reason naming the cause (starved forward, collapsed rate, silent
progress), sourced from the same evidence blocks the jobs surface publishes.
`/health` keeps its status vocabulary and its probe-free shape, and now moves
within `DEGRADED_THRESHOLD_SECONDS` of a starved forward.

**Probes to status.** The status ladder splits the terminal heartbeat branch:
`heartbeat_stale` with pid alive, identity token confirmed, and port accepting
classifies as a degraded starved state - a label in the mould of "degraded
(starved: heartbeat stale, process alive and answering)" - instead of `crashed
(heartbeat stale)`. The crashed labels survive for the cases that earn them:
pid dead, PID reused, port silent, probe unanswered. The verdict envelope
carries the evidence quadruple plus the newest running-job forward age, so the
operator line names the cause, not just the state.

**Resolution to clients.** Machine resolution keeps refusing missing, invalid,
and foreign pointers. A stale pointer whose holder is live and whose pointer
pid matches the holder is handed out flagged rather than refused; the client's
existing token probe confirms identity before use, queries run under existing
bounded timeouts, and a failure while flagged reports the starved verdict.

**Broker and operator contract.** `status` against a starved daemon exits
non-zero with the existing fault code - the requested serving state is not
achieved - and emits exactly one structured envelope; healthy `running` remains
exit 0. `start` against a starved holder is neither already-satisfied nor
achievable: it exits non-zero with the envelope naming the live holder and the
starved verdict, and never treats the machine as stopped. `start` against a
healthy running daemon remains exit 0 already-running; `stop` proceeds as
today. Every exit path emits exactly one envelope, identical through CLI and
MCP.

**Explicit non-goals.** No restart-if-degraded arm anywhere - not in
maintenance, not in the broker, not in a supervisor loop. No GPU-lock
acquisition or CUDA initialisation on any probe path. No canary encode. No
second implementation of the forward fact. No new threshold numerals. No change
to heartbeat cadence or staleness window. The root cause of the incident's
early heartbeat freeze is out of scope and remains an open unknown.

## Rationale

The fact quadruple wins on a knockout: every distinguishing fact is already
probed on the status path today, and the incident is the proof they suffice -
pid alive, token match, port listening, and an answering `/health` all held
while the heartbeat was stale, which is precisely the starved signature and
precisely the evidence the current ladder discards by collapsing into
`crashed`. Every writer-side alternative fails on the incident's own timeline:
the heartbeat froze hours before the encode starved, so only reader-side facts
are robust to the freeze's unestablished cause.

Feeding `/health` from the existing per-job verdict wins for the same reason
the index-observability record put the verdict in the service domain: the
classification exists, is evidence-attributed, and is published beside the
numbers that earned it. `/health` consuming it is one rollup line, while every
alternative either re-derives the verdict (a forbidden duplicate) or probes
fresh (forbidden on a health path).

Keeping a starved daemon discoverable follows from what refusal actually
bought: nothing. It fabricated "stopped" over a live singleton holder, priced
the incident at hours instead of one degraded status line, and pointed the
operator at a start that could only lose. Reporting without remediating
follows the observe-first precedent: a verdict this new must accumulate trust
before anything acts on it, and the acting, if ever, is a separate decision
with its own record.

## Consequences

- The incident class becomes visible on every surface within a minute:
  `/health` degrades on the starved forward, `status` names starved-not-gone
  with evidence, and the CLI stops telling operators a live daemon does not
  exist. The two-verdict contradiction is structurally closed because both
  surfaces now read the same facts.
- `crashed (heartbeat stale)` narrows to daemons that do not answer. Some of
  today's instant local refusals become a bounded query attempt against a
  starved daemon plus an honest failure - a latency cost per query during
  degradation, accepted as the price of not fabricating an outage.
- A daemon whose event loop answers while its workers are dead now reports
  starved indefinitely rather than crashed, and nothing auto-remediates it, by
  design. Operator action stays manual; the envelope's evidence is what makes
  the manual call quick.
- The starved verdict inherits the fidelity of the forward window: an encode
  stage that never entered a forward (a CPU-bound step) degrades on
  progress-age instead, which is coarser. Accepted - the jobs surface already
  states expected-forward-absence explicitly.
- Broker semantics stay stable: exit codes keep their meanings; the only change
  is which label rides the fault code for an answering-but-stale daemon, so
  existing brokers misread nothing.
- Opens: the degraded envelope's evidence block is the natural composition
  point for the admission gate's device-load reading - turning "starved" into
  "starved by what" - without re-deciding anything here.

---
tags:
  - '#audit'
  - '#operator-feedback-hardening'
date: '2026-07-24'
modified: '2026-07-24'
body_hash: 'sha256:a554b417ec51c6dff4b6a982b9b71e842476ba081b76d782fa7319c3581964ab'
related: []
---

# `operator-feedback-hardening` audit: `why four operator surfaces reported nothing`

## Scope

Triggered by an operator report that `server start` printed nothing and then
failed with `Waited: 300s`. The investigation widened once the first cause was
found, because the same failure mode appeared on every surface examined. Audited:
the CLI console construction and every live-region consumer, the start health
wait, the `/health` status derivation, the `server status` renderer, the jobs
watch loop, the index disk pre-flight, and the daemon startup failure path.
Measurements were taken on the reporting machine against the live service.

## Findings

### dead-render-channel | critical | Every live region in the CLI rendered zero bytes

The shared console was constructed with interactivity forced off. Rich renders a
transient live region only while its console reports itself interactive, so
every spinner and progress bar in the CLI emitted nothing. Measured on the
pinned Rich version: identical code produced 0 bytes with the flag and 159 bytes
without it. The `server start` spinner, the search spinner, the model-download
spinner, and the indexer's progress bars were all affected by this single
construction. The comment above it asserted that status messages still printed
once; a transient region on a non-interactive console renders zero times.

### stale-verdict-blocks-start | critical | A serving daemon was reported as a start timeout

`server start` polled until `/health` reported the literal status `ready`, but
that status is also lowered by job history. On the reporting machine the daemon
was serving - models resident, backend live, no active jobs - while a single
failed indexing job held the status at `degraded`. The cited failure finished
5.78 hours before the daemon reporting it had started, read from a job record
that persists across restarts. The command therefore waited its full 300-second
budget and exited non-zero against a healthy service, deterministically, on
every start. The same daemon was already treated as an attachable success by the
idempotent path, so the two paths disagreed about one state.

### silent-refusal | high | A daemon that refused to start explained nothing

The machine-singleton claim raises an error naming the winning process and the
remedy. The startup failure handler exits through a process-level exit, which
makes the re-raise after it unreachable, and the exception was never logged. A
second service therefore exited non-zero with only a generic backstop line. The
diagnostic existed in full and was discarded.

### wrong-volume-preflight | high | The disk pre-flight measured the wrong volume

The index admission check measured free space on the indexed tree's volume while
enforcing a requirement about the vector store, then labelled the reading
"storage reports". On the reporting machine those are different physical
volumes: the measured one had 33.67 GiB free, the store's had 276.85 GiB, and an
index that would have fit was refused. The refusal also printed raw byte
integers and repeated its own error kind twice.

### unreadable-diagnostics | medium | Operator text rendered container reprs and mislabelled units

Several surfaces interpolated structures and raw integers directly. The status
command printed a nested dictionary repr for index generations, byte counts as
bare integers, and mebibyte values suffixed "MB" - the last understating every
figure by about 5 percent at that scale. A storage helper divided by 1024 while
labelling the result "GB". A degraded service named no cause and offered
`--verbose` as its remedy while the daemon was supplying the cause, the failing
job's identity, and its age.

### uninterruptible-watch | medium | Ctrl+C could not stop a watch or a start

Both the jobs watch loop and the start health wait performed their network poll
on the main thread. An interrupt only becomes an exception at an interpreter
check, which a thread blocked in a socket read never reaches. Measured with a
real console interrupt: an interruptible sleep responded in 0.007s, a blocked
socket read ignored the interrupt for 58.5s and then raised a timeout instead,
and the real watch loop against an unresponsive daemon absorbed it for 29.004s.
The watch also exited zero on interrupt, reporting a success never delivered.

### verification-measured-the-producer | critical | Three prior corrective attempts closed green without rendering anything

The governing decision record for startup feedback is accepted and its plan
closed every step. Three commits over six weeks enriched the published stage
string. None of them rendered. The step whose stated purpose was verifying that
stages render live confirmed the daemon's published status view by polling it -
observing the producer across the process boundary, never a terminal. A
sibling step recorded a guard proof that is a string comparison between two
literals. Six unit tests assert the return value of the label function and
construct no console. Every one of them was green throughout the period in which
no operator saw a stage. Absent coverage invites inspection; coverage that
reports success on the wrong side of the boundary consumes the attention that
would have gone looking.

## Recommendations

Resolve interactivity once, from the real output stream rather than from
terminal detection that environment variables can move, so one answer governs
every consumer. A follow-on decision record must also settle where progress is
written relative to the parseable result channel, and whether a live region may
be driven by a console other than the one printing around it - the second is not
a style question, since two consoles cannot coordinate one region and the
observed result is foreign text welded onto a spinner frame.

Separate the two questions `/health` currently answers with one word. A
follow-on decision must state what condition gates a start, and must bound a
job-history verdict to the process generation that earned it while keeping the
record itself reportable.

Make refusal paths state their cause before exiting, ordered so the actionable
sentence survives a truncated tail.

Measure the volume the requirement is about, and name the path and volume
measured in the refusal.

Route every size and structure through one rendering vocabulary, and pair every
degradation cause with a command that addresses it.

Perform blocking polls off the thread that must remain interruptible.

The load-bearing recommendation is the last finding's: a test whose subject is
that an operator sees something must assert on bytes captured from a console,
never on the return value of the code that produced the string, and must be
shown to fail when the rendering is removed. Asserting only that output is
non-empty does not satisfy this - a live region emits cursor control codes
whether or not it ever paints, so a byte-count assertion stays green through the
regression it exists to catch.

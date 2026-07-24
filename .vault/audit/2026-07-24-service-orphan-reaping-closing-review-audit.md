---
tags:
  - '#audit'
  - '#service-orphan-reaping'
date: '2026-07-24'
modified: '2026-07-25'
related:
  - "[[2026-07-23-service-orphan-reaping-plan]]"
  - "[[2026-07-23-service-orphan-reaping-adr]]"
  - "[[2026-07-24-service-orphan-reaping-launcher-daemon-pair-reference]]"
---

# `service-orphan-reaping` audit: `closing review of the lifecycle and stop surface`

## Scope

The lifecycle and stop surface this feature changed: the daemon's startup guard
and forced-exit backstop in `src/vaultspec_rag/server/_lifespan.py`, the
entrypoint backstop in `src/vaultspec_rag/server/_main.py`, and the whole
signature-scoped reap in `src/vaultspec_rag/cli/_service_stop.py` -
`_expected_singleton_port`, `_orphan_daemon_pids`, `_pid_terminated`,
`_reap_orphan_daemons`, and the `--orphans` wiring. The tests added for it are in
scope too.

Every gate was run whole-tree and is green: ruff check, ruff format, ty,
basedpyright at zero errors, the three complexity gates, the citation gate, the
absolute-import scan, and both markdown gates over the feature's documents. The
module-length gate is report-only and its findings are noted below.

The reap and structured-stop suites pass: twenty-two tests across the
envelope-shape suite and the reap-safety suite, and the non-GPU tests of the
integration lifecycle module. GPU-loading daemon tests were deliberately not
run - the operator's resident service was live on this machine throughout, and a
second GPU daemon would contend with it for the single device. That service was
confirmed untouched after the work, still on its pre-existing uptime.

The review found the shipped safety properties sound and the completeness
properties weaker than the command's own help text implies. Nothing here
contradicts the decision; the findings are about the enumeration the decision
rests on.

## Findings

### safety-anchors-are-computed-outside-the-sweep | low | The must-never-kill set does not degrade with a degraded enumeration, which makes every enumeration weakness below one-directional

Worth recording as a finding because it is what bounds the severity of the three
that follow. The anchor set is built from the machine-lock holder, the discovery
pointer, and the pid answering health on the port. None of those come from the
host-wide sweep, so a sweep that truncates, misses a process, or returns nothing
at all can only cause an orphan to be MISSED. It cannot cause the singleton to
be selected, because a process absent from the match set is never a candidate.
Under-reaping is recoverable by running the command again. The inverse would not
be, and the design does not permit it.

### zero-is-treated-as-an-anchor | medium | An absent lock holder, pointer, or serving pid enters the anchor set as zero, so any process whose parent id reads as zero is spared as an anchor's child

The anchor set is assembled from four values, three of which are zero when the
corresponding evidence is absent - which is the normal case for an isolated
config, and the case on any machine with no resident service. The pair
protection then treats "this process's parent is an anchor" as grounds for
sparing it. A process whose parent id is zero therefore reads as the child of an
anchor. This is not hypothetical bookkeeping: the enumerator itself substitutes
zero whenever it cannot read a real parent id, so an unreadable parent converts
directly into protection. The direction is conservative - a matched pid can
never itself be zero, so the singleton is never endangered - but under-reaping
is precisely the failure this command exists to prevent.

### orphan-pair-launcher-intermittently-survives-the-reap | medium | The reap twice reported a single reaped pid while the orphan it was given was a launcher and worker pair, leaving the shim launcher alive

Observed twice while running the integration lifecycle module: the envelope
named one pid, the worker, and the spawned shim launcher was still running. The
same test reaped both when run alone, and the dedicated pair-safety test, which
asserts the whole orphan pair terminates, passed in the same session. So the
behaviour is intermittent rather than absent, which is consistent with either of
two mechanisms in the same function - the zero anchor above, or the silent
truncation below - and the precise one was not isolated. The consequence is a
stranded shim process rather than a surviving daemon: the process that runs the
service is reaped. It still contradicts the flag's help text, which promises to
clear the daemons it finds, and a stranded witness enumerates into every
subsequent sweep.

### enumeration-truncates-silently | medium | One failure anywhere in the host walk abandons the remainder and returns a partial match set with no signal

The enumeration wraps its ENTIRE loop in a blanket exception suppression, so a
single failure on the third process of a thousand returns whatever was collected
before it and reports success. The caller cannot distinguish "no orphans on this
port" from "the walk died early". Given that this project measured a walk of
this shape returning nothing at all on a live target, the suppression is
covering a real and recurring condition rather than a theoretical one.

### reap-runs-for-tens-of-seconds-with-no-operator-feedback | low | One reap costs about thirty-nine seconds cold on this host and prints nothing until it finishes

Measured: about thirty-nine seconds on a first call against roughly a thousand
processes, four to six seconds on a warm repeat inside the same interpreter.
Because the command is a fresh process every time it always pays the cold cost,
and essentially all of it is reading command lines - enumerating pids alone
costs two milliseconds. This is the longest-running path on the stop surface and
the only one with no progress output, so it presents to an operator exactly as a
hang. Recent work across the CLI added progress reporting to long-running
commands and did not reach this one.

### test-module-is-well-past-the-length-threshold | low | The integration lifecycle module is roughly two and a half thousand lines against a thousand-line advisory threshold

Pre-existing and made slightly worse here: this work added about a hundred and
twenty lines to a module that was already more than twice the threshold. The
gate is report-only, so nothing fails, but the module is now the natural place
every new lifecycle test lands and it will keep growing.

## Recommendations

Build the anchor set from positive evidence only, discarding any non-positive
pid before it becomes an anchor, so an absent holder cannot confer protection
and an unreadable parent id cannot masquerade as an anchor's child. This is the
smallest change that removes one of the two candidate mechanisms behind the
intermittent survival, and it is worth taking on its own merits regardless of
which mechanism is responsible.

Narrow the enumeration's exception suppression to the per-process body so one
unreadable process is skipped rather than ending the walk, and record when it
happens, so a partial sweep is visible instead of indistinguishable from an
empty one. Together with the previous recommendation this should be followed by
re-running the pair-safety suite repeatedly rather than once, since the defect
it targets appears intermittently.

Derive the pair relationship for the anchors from the operating system's own
process tree rather than from the match set. Today an anchor's parent is only
protected when the anchor itself was successfully enumerated, so the same
enumeration weakness that costs completeness also carries the pair protection.
Reading the anchor's parent directly costs one process lookup and removes that
coupling.

Give the reap the progress reporting the rest of the long-running CLI surface
now has, and consider whether the walk can be narrowed - the parent-id-only
enumeration is three orders of magnitude cheaper, and command lines are needed
only for the small set of candidates that survive a cheaper first pass.

None of these is architecturally significant and none needs a decision record.
They are corrections to an enumeration whose shipped safety direction is already
correct.

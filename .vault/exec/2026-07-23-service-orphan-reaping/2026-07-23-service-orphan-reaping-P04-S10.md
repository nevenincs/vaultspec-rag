---
tags:
  - '#exec'
  - '#service-orphan-reaping'
date: '2026-07-24'
modified: '2026-07-25'
step_id: 'S10'
related:
  - "[[2026-07-23-service-orphan-reaping-plan]]"
  - "[[2026-07-24-service-orphan-reaping-launcher-daemon-pair-reference]]"
---

# Reconcile the reap envelope with the broker and control-plane structured-stop regression suite

## Scope

- `src/vaultspec_rag/tests/integration/test_service_lifecycle.py`
- `src/vaultspec_rag/tests/test_cli_server_stop.py`

## Description

- Add an envelope scanner that returns EVERY parseable outcome envelope in a
  command's output, so a second envelope is caught rather than discarded by a
  first-or-last-line search.
- Add four integration tests holding the reap to the broker contract: the
  idempotent no-op success, the human-mode silence, the refusal when the reap
  cannot resolve its own scope, and a real out-of-process reap whose single
  envelope names the pids it terminated.
- Extend the envelope-shape suite with the reap's success status and pin the
  incomplete-reap fault shape, including its surviving pids, through the real
  failure helper.

## Outcome

The reap now answers to the same structured-stop contract as its peers, at both
tiers. Each exit path emits exactly one envelope in json mode and none in human
mode; an already-satisfied reap is a success at exit 0; the real terminating
reap carries its count, its reaped pids, its port, and the initiator attribution
the other terminating stops carry.

The refusal test is the one worth calling out. Without an explicit port the reap
resolves its own scope and, when it cannot, must refuse rather than substitute a
default - a substituted default would aim a terminating sweep at whatever
service happens to hold that port on the machine, which is the single outcome a
port-scoped reap exists to prevent. That path was reachable but untested.

Three guard assertions were proven bidirectionally, each as one scripted
mutate-run-restore sequence:

- Permitting the default-port substitution makes the refusal test fail on its
  exit-code assertion, with the envelope showing a silent success against the
  substituted port instead of a refusal.
- Forcing the success renderer into json mode unconditionally makes the
  human-mode test fail on its no-envelope assertion.
- Emitting the success envelope twice makes the idempotent-success test fail on
  its exactly-one-envelope assertion, at two rather than one.

Every proof restored the source and verified the restoration before exiting.

## Notes

The four integration tests take about two minutes together, which is dominated
by the reap's host-wide command-line sweep rather than by anything the tests do.
The out-of-process reap is given a budget well past the measured cold sweep so
host load cannot turn into a spurious failure, and its witness sleeps far longer
than one sweep, because a process that exits mid-sweep is dropped from the
enumeration entirely.

The real reap runs OUT of process deliberately. The witness is the test's own
child, and an in-process reap would spare it as the descendant of an anchor -
a confound absent in production, where the reap is never the orphans' parent.

Every test pins an explicit ephemeral port under isolated singleton paths. That
is a safety property rather than a convenience: the port is the reap's blast
radius, and the operator's resident service was live on its own port throughout.
It was confirmed untouched afterwards, still on its original uptime.

The incomplete-reap fault is pinned at the helper rather than end to end. Staging
it live needs a process that survives a force-kill, which cannot be produced
honestly; the surrounding suite pins its other failure shape the same way.

The envelope-shape suite sits outside the Step's declared scope. Extending it was
the direct reading of reconciling the reap envelope WITH that regression suite,
rather than leaving the new statuses covered only at the integration tier.

One incident, recorded because it recurs in a shared worktree: a concurrent
session staged the mutated file during one proof's window, so the index briefly
held the mutation. The working tree was already restored; the index was
corrected by re-staging that one file, and nothing from the concurrent session
was lost - index and worktree differed on the mutated line alone.

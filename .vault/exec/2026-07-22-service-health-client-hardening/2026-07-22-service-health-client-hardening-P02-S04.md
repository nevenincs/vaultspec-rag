---
tags:
  - '#exec'
  - '#service-health-client-hardening'
date: '2026-07-22'
modified: '2026-07-22'
body_hash: 'sha256:a3a8fc8864555d62100d7a640e53fa2974f18293fb66516678590a0150e7ee25'
step_id: 'S04'
related:
  - "[[2026-07-22-service-health-client-hardening-plan]]"
---

# Enumerate every caller of the general transport entry point and record which rely on the absent default timeout, treating each as an unbounded credential-exposure window rather than a bookkeeping entry

## Scope

- `src/vaultspec_rag/serviceclient/_transport.py`

## Description

- Enumerate every caller of the general entry point in
  `src/vaultspec_rag/serviceclient/_transport.py` and classify each by whether
  it supplies a bound.
- Establish whether the one unbounded caller's omission is deliberate or
  neglected, by reading the route it calls.

## Outcome

Seven production call sites exist, all within the transport itself. Six already
supply a bound: the clean path at `_transport.py:473` and the generic admin path
at `:509` pass a resolved administrative timeout, the admin router at `:760`
receives one from its only caller, the jobs and health summaries at `:878` and
`:903` pass one second each, and search at `:1183` passes a resolved search
timeout. The admin router deserves a note because it looked like a gap: it takes
its bound from a value in its argument mapping, which would be absent if it were
called directly, but it has exactly one caller and that caller always sets it.

One caller supplies nothing. The reindex helper at `_transport.py:441` calls the
entry point with no timeout argument, and it is reached from both public
surfaces - the index command, and the agent-facing reindex tools through their
shared delegation helper. Before this Step, that call could wait indefinitely.

The substantive question was whether that omission was neglect or design, and it
was resolved rather than assumed. A reindex can legitimately run for a long time,
so a bound imposed on a call that blocked until the work finished would abort
legitimate rebuilds - a regression that would be attributed to the wrong cause
later, and one arriving inside a change whose stated purpose is a safety fix. The
route settles it: it is a validated adapter over job creation, and it answers
with a queued status and a job identifier rather than waiting for the index to be
rebuilt. The call is therefore short by construction. The absent bound is
neglect, and bounding it carries none of the risk that would have justified an
exemption.

Roughly twenty further call sites exist in tests. They are not a production risk,
but they inherit whatever default is set, so a bound short enough to matter would
have turned integration tests red for reasons unrelated to their subject. The
resolved default is generous enough that none of them is affected.

## Notes

The enumeration was performed by reading, not by instrumenting: the call sites
were found by searching for the entry point across the package and each was
classified by reading its arguments. No call was executed and no timing was
measured, so "six are bounded" is a claim about what the code passes rather than
about observed behaviour.

The reindex route's non-blocking nature was likewise established by reading the
route and its response shape. It answers with a queued status, which is strong
evidence but not the same as having watched a long rebuild return promptly. A
verifier wanting certainty should exercise a real reindex against a live daemon;
that was not done.

That reading was independently repeated by a second reader who reached the same
conclusion from the same route, and who added a corroborating detail this author
had not used: the command reference already tells a caller to consult the jobs
verb for progress, which only makes sense if the request returns before the work
finishes. Two independent readings agreeing is not the same as an execution, but
it is a materially stronger basis than one.

This enumeration was carried out before the Step was formally started, as
preparatory reading while waiting on a commit, and its finding was reported to
the coordinator before any code was changed. It is recorded here in full so the
record does not depend on that message surviving.

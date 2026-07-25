---
tags:
  - '#adr'
  - '#service-release-compat'
date: '2026-07-25'
modified: '2026-07-25'
related:
  - '[[2026-07-25-service-release-compat-reference]]'
---

# `service-release-compat` adr: `Client/server release compatibility signal` | (**status:** `accepted`)

## Problem Statement

A client and the daemon it drives are separate installs that drift independently: a
globally installed tool beside a project-local environment, a machine carrying several
checkouts, or an upgrade that replaces the client while the previous daemon keeps serving.
Nothing on the wire lets either side notice.

Two distinct gaps produce that. The package release never crosses a process boundary at
all - it is published on no route and in no discovery record, so a client has no datum to
compare. And the one discriminator that does cross, the discovery file's
`(schema, version)` pair, is stamped by both writers and compared by no reader, so the
published instruction to pin on the pair and refuse a file you do not understand is prose
the project's own client code does not honour.

The consequence is silent, not loud. The attach-to-existing-daemon path confirms identity
by token and executable name, both of which a foreign build of the same tool satisfies, so
an operator who just installed a new client is told `already_running` about a daemon from
the install they replaced.

## Considerations

- Identity and release are different questions. The existing token check proves a daemon
  is *ours*; it cannot prove it is *this build*.
- The daemon already fails closed on a version mismatch when it attaches to its own
  Qdrant, and refuses even when the version merely cannot be read. The same codebase has
  no equivalent gate when its own clients attach to it.
- The ungated health route is the only surface reachable before a client holds a token, so
  any pre-authentication handshake has to ride it.
- A discovery record already carries the interpreter version, which nothing reads. A
  second unread version field would repeat that.
- The service-surface rule places this behaviour in the service domain with entry points
  adapting to it, and requires an already-satisfied request to stay a zero-exit success.
- A file shape written before the discriminator existed is a legitimate pre-upgrade state,
  not a foreign build.

## Considered options

- **Publish nothing, document harder.** Rejected: the gap is the absent datum, not absent
  prose. The instruction to pin already exists and changed no behaviour.
- **Hard-gate every client call on a release match.** Rejected: a client that refuses to
  talk to a differently-released daemon also cannot stop it, so the operator is locked
  inside the mismatch being reported. It converts a recoverable skew into an outage.
- **Reuse the schema `version` integer to also mean the release.** Rejected: the two are
  bumped on different events - a shape break against every release - and fusing them would
  force a shape bump on every publish.
- **Publish the release and enforce the shape pin, as two signals of different strength.**
  Chosen. The shape question has a safe refusal; the release question does not.
- **Move every route onto typed request models so an unknown field is rejected.** Deferred,
  not rejected: it addresses a third failure mode - a newer client's fields silently
  dropped by an older daemon - and is a large independent change.

## Constraints

- Additive fields only. The discovery schema version is not bumped: the published contract
  states additive fields do not bump it, and bumping would make every existing file
  unreadable by the very gate being added.
- Backward compatibility runs both ways. An older daemon publishing no release must be
  reported as unconfirmed rather than mismatched, and a file predating the discriminator
  must still be read.
- The client layer must stay import-light and torch-free; it is shared by the CLI fast
  path and the MCP stdio shell.
- Resolving installed package metadata is the dominant cost of importing this package, so
  it must stay lazy and cached rather than paid at import in every spawn worker.

## Implementation

One shared module in the import-light client layer owns both halves of the contract, so no
entry point computes its own verdict.

The release half publishes a `package_version` field - named apart from the schema
discriminator and the storage-schema version already travelling those surfaces - from the
process that writes each record: on the ungated health route, on the readiness report, in
the daemon's discovery snapshot, and in the launcher's status write. A client compares the
published value against its own and gets one of three verdicts: matched, mismatched, or
unknown when the daemon published nothing. Unknown is deliberately not folded into
matched; an unconfirmed pairing is not an agreement. The verdict carries both releases so
an operator surface can name them rather than report a bare disagreement.

The shape half turns the documented pin into a real refusal at both readers of the
discovery record. A payload declaring neither half of the pair is the pre-discriminator
case and is accepted; a payload declaring one half, or declaring the pair with values this
build does not recognise, is refused without any of its remaining fields being read. Where
the refused record is the machine pointer of a live lock holder, the resolution is degraded
with its own reason rather than absent, because something does own the singleton.

The entry points adapt. The start verb reports the verdict as a structured field on every
outcome that reaches a daemon and prints a warning line whenever the pairing is not a
confirmed match - including the attach path, which remains a zero-exit already-running
success. The status verb renders the same verdict beside the environment line that already
identifies the daemon's install.

## Rationale

The two halves get different strengths because they have different safe failures.

Refusing a record whose shape this build cannot parse is safe, and is the only correct
move: the pid and port inside it are not this build's pid and port, so acting on them would
drive or kill a foreign process. There is no recovery cost, because refusing to read a file
does not prevent any verb from running.

Refusing to *talk* to a differently-released daemon has no safe failure. The client that
would refuse is also the only thing that can stop that daemon, so a hard gate strands the
operator. Reporting the pairing on the surfaces an operator already consults - and on the
attach path specifically, which is where a stale daemon is silently adopted - converts the
invisible case into an actionable one without removing the remedy.

Keeping unknown distinct from matched is what makes the signal honest. The failure being
removed is a mismatch reported as agreement; collapsing an unconfirmable pairing into
agreement would reintroduce that failure in a narrower form.

## Consequences

Gains: a client can name which build it is about to drive before it authenticates, and an
operator who upgraded a client while an old daemon kept serving now sees that on both start
and status instead of a bare already-running line. A discovery record written to a shape
this build does not understand can no longer be acted on.

Costs and honest limits: the release signal is advisory, so an operator who reads neither
start nor status output still drives a mismatched daemon. Field-level skew - a newer client
sending filters an older daemon drops on the floor - is untouched by this decision and
remains the open failure mode; it needs typed request models and is deferred to its own
work. The exact key sets asserted on the readiness report and on the launcher's status write
both grow by one field, and those assertions are deliberately exact so that growth is a
reviewed change rather than an accident.

Pathways opened: with a release on the wire and a verdict type in the shared layer, the MCP
surface can adopt the same signal without a second implementation, and a future decision to
harden any particular call path into a gate has the datum already published.

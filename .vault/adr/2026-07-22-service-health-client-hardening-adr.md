---
tags:
  - '#adr'
  - '#service-health-client-hardening'
date: '2026-07-22'
modified: '2026-07-22'
related:
  - "[[2026-07-22-service-health-client-hardening-research]]"
  - "[[2026-07-22-codebase-dedup-centralization-audit]]"
---

# `service-health-client-hardening` adr: `health call ownership, redirect policy, and error contract` | (**status:** `accepted`)

## Problem Statement

Two HTTP clients reach the service health endpoint, and they disagree on
redirect policy, timeout bounding, and how unreachability is signalled. The
`2026-07-22-service-health-client-hardening-research` establishes that the
justification previously offered for the split - that the command-line probe
runs before a status file exists and therefore cannot use the shared transport -
is false, and that in each of the three disagreements the command-line probe's
behaviour is the safer one.

A decision is needed now rather than at leisure because one of the
disagreements is a defect, not a preference: the shared transport follows
redirects on an endpoint where the project has already written a control that
refuses them, and the value that endpoint returns selects a process for
termination. The same research also found that the identity check guarding that
termination is self-referential, which makes the redirect policy load-bearing in
a way neither client's author appears to have intended. Consolidating the
duplication without settling redirect policy first would remove a control while
leaving what it compensates for in place, so ownership and sequencing cannot be
decided independently.

## Considerations

- The transport has no status-file dependency and already serves the health
  endpoint itself; the bootstrap-ordering premise does not exist
  (`2026-07-22-service-health-client-hardening-research`).
- All nine call sites consume parsed payload fields rather than a liveness
  verdict, so any owner must return the body with the same field availability.
- The transport addresses only loopback at a caller-supplied port, against a
  daemon this project ships; no route it calls emits a redirect today.
- Two of the nine sites are inside the service start and service stop verbs,
  which are bound by the codified requirement that a broker-facing verb emit
  exactly one structured outcome envelope on every exit path.
- The command-line probe's non-raising contract is what lets those verbs treat
  unreachability as an ordinary branch rather than an escape.
- The established codebase pattern already treats read-only health and metrics
  probes as a deliberate exception to a general rule, so an exception carved for
  health is idiomatic here rather than novel.
- The transport's unbounded default timeout is latent today because current
  health callers pass an explicit bound, but consolidation would aim nine more
  callers at that default.

## Considered options

**Redirect policy on the health path only.** Rejected. It corrects the call
whose consequence was traced while leaving the general request path - the one
that carries the bearer token - following redirects, so the inconsistency the
defect arises from survives in the larger half of the transport.

**Redirect policy across the whole transport.** Chosen. One policy, one owner,
no endpoint-by-endpoint reasoning about which calls are safe.

**Leave the split and document it honestly.** Rejected. Documentation would have
to describe a divergence that has no justification left once the
bootstrap-ordering premise is gone, and would preserve two clients that must
now be kept in step on redirect policy, timeout bounding, and error signalling.

**Move the call onto the general transport entry point.** Rejected. It converts
a sentinel contract into an exception contract at nine sites, two of them inside
verbs bound by the one-envelope requirement, and buys nothing the narrower
option below does not.

**Give the transport a dedicated health function that keeps the command-line
probe's contract.** Chosen. One owner, and the nine call sites keep the
non-raising sentinel they already branch on, so the contract change that made
consolidation expensive does not occur at all.

**Extract a third primitive both clients consume.** Rejected. It leaves two
public entry points to the same endpoint and adds a module without removing a
client, which is more surface than either the split or single ownership.

**Fix the redirect policy after or during consolidation.** Rejected as unsafe
ordering; see the sequencing constraint below.

## Constraints

- **Sequencing is binding, not advisory.** The redirect correction lands and is
  verified before any consolidation work begins. The no-redirect opener is
  currently the only thing confining a consistent responder to the local port,
  because the identity check it protects is self-referential
  (`2026-07-22-service-health-client-hardening-research`). Consolidating first
  would move the health call onto a redirect-following client and open that
  window for the duration of the refactor. An implementer may not reorder these
  without contradicting this record.
- The nine call sites must observe no behavioural change. Unreachability
  continues to be a returned sentinel, an unhealthy answer continues to carry
  its status and HTTP code, and no new exception type may escape into the start
  or stop verbs, whose one-envelope obligation is codified elsewhere and is not
  reopened here.
- The owning module must remain import-light and free of heavy dependencies, as
  the existing service-client and command-line service-control paths already
  require.
- This record depends on no immature or frontier technology. It changes how one
  standard-library HTTP opener is constructed and where one function lives; the
  parent features it touches - the transport, the service-control verbs, and the
  status renderer - are all shipped and stable.
- The transport transmits its bearer credential to a redirect target, because
  the standard library copies request headers across a redirect without host
  comparison or credential stripping
  (`2026-07-22-service-health-client-hardening-research`). Any policy that
  leaves the general request path following redirects therefore leaves a
  credential-disclosure path open, which bounds the acceptable scope of D1.

## Implementation

**D1 - The transport refuses redirects on every request.** The transport builds
its requests through an opener that declines to follow redirects, replacing the
bare standard-library opener used on both its request paths.

The policy is transport-wide rather than health-specific, on two independent
grounds. First, the transport speaks only to loopback, at a port the caller
names, against a daemon this project ships, and no route it calls emits a
redirect; a redirect arriving on any of its paths therefore indicates something
other than the intended service answering, which is a condition to refuse rather
than to follow. Second, and decisively for scope, the general request path
carries the service bearer credential, and the standard library copies request
headers onto a redirect target without host comparison or credential stripping
(`2026-07-22-service-health-client-hardening-research`). A health-only policy
would leave that path intact and with it a route by which the service token
reaches an attacker-chosen destination. Refusing redirects transport-wide closes
credential disclosure and endpoint misdirection with the same change.

A future route that genuinely needs redirect-following must justify it against
this record rather than inherit it silently, and any such justification must
address credential forwarding explicitly.

**D2 - The transport owns the health call and keeps the probe's contract.** A
dedicated health function in the service-client transport becomes the single
owner. It returns the parsed body on success, a structured error carrying the
HTTP code when the service answers unhealthily, and a sentinel when the service
is unreachable; it never raises for unreachability. It carries a bounded default
timeout equal to the command-line probe's present default, so behaviour at the
call sites is preserved rather than merely approximated. The command-line probe
ceases to be a second implementation: its nine call sites resolve to the new
owner, and the name they currently import may remain as a thin delegation if
that reduces churn, provided only one implementation exists behind it.

The general transport entry point keeps its exception contract for everything
else. The transport therefore exposes two failure idioms, separated by function
and documented at both: an exception contract for ordinary calls, and a
non-raising probe contract for health. This mirrors the established treatment of
read-only health and metrics probes as the deliberate exception elsewhere in the
codebase.

**D3 - Bounded timeouts are the default, and the general default is corrected.**
The health function's default is bounded. The general entry point's default,
which currently resolves to no timeout at all, is changed to a bounded value;
because the research established the passing habits only of the health callers,
the implementing plan must first enumerate every caller of that entry point and
record which rely on the absent default, rather than assuming the blast radius
is nil.

**D4 - The self-referential identity check is out of scope and deferred.** How
the service proves its identity to a client is a different decision from which
client makes the call: it concerns what secret is compared against what
independently sourced value, and its remedy - an expected token drawn from the
status file or from operating-system process ownership rather than from the same
response - changes the stop verb's semantics, not the transport's. It gets its
own record. Two things are decided here about it: this ADR's redirect
correction must not be described or recorded anywhere as fixing it, and the
open question the research left visible - whether other callers of the identity
helper already supply an independently sourced expected token, which would make
the weakness stop-path-specific rather than general - must be answered before
that record is authored.

**D5 - The transport's module docstring is corrected as a factual matter.** Its
claim that every call funnels through the general entry point is false today and
would remain imprecise afterwards. No decision is required; it is carried as
implementation work.

## Rationale

The knockout criterion is that the expensive part of consolidation turns out to
be optional. Every previous framing of this problem assumed that moving
ownership meant moving the call sites onto the general entry point, and
therefore converting a sentinel contract into an exception contract inside two
verbs that must emit exactly one envelope on every exit path. That cost is what
made the split look defensible. It is an artefact of choosing the wrong owner:
a health function that keeps the probe's contract collapses nine contract
changes to zero while still leaving one implementation. Single ownership and an
unchanged call-site contract were never actually in tension.

The redirect decision needs little defending on its own merits - the project
already decided this endpoint's redirect exposure was a risk and wrote the
control; the transport simply does not honour it. What the research changed is
its urgency and its scope.

Urgency, because the value the health endpoint returns reaches process
termination. Scope, because the general request path forwards the service bearer
credential to whatever host a redirect names. That second finding is what makes
the narrower option untenable rather than merely untidy: a health-only policy
would correct the consequence that was traced first while leaving open the one
that is worse. Ranked honestly, credential disclosure outranks
process-identifier confusion - the health endpoint is ungated and its response
is a value the client misreads, whereas on the request path a secret the client
holds leaves the machine. A single change to how the opener is constructed
closes both, so there is no efficiency argument for the narrower scope either.

Sequencing is elevated to a constraint rather than left as good practice
because, per `2026-07-22-service-health-client-hardening-research`, the control
being fixed is currently compensating for the defect being deferred. Ordering
these wrongly does not merely delay a benefit; it removes a mitigation while
its cause remains, which is a net regression during the window.

The identity check is deferred rather than absorbed because absorbing it would
let a security decision about how the service authenticates itself ride along
inside a refactor about client duplication - the same reasoning that keeps the
redirect fix out of the consolidation commit, applied one level up.

## Consequences

- The transport stops forwarding its bearer credential to redirect targets.
  This is the most consequential outcome of the record and is the reason D1 is
  scoped transport-wide rather than to the health path: it removes a
  credential-disclosure route, not merely a misdirection one.
- The health path stops sourcing a process identifier from an arbitrary
  redirect target, which removes the traced chain into process termination.
  This is the second-most consequential outcome; it was found first, but it is
  the lesser of the two.
- One implementation of the health call, with redirect refusal, a bounded
  timeout, and a documented failure contract, instead of two that must be kept
  in step by memory.
- The nine call sites change which name they import and nothing else. No verb
  bound by the one-envelope requirement changes its exit paths, which keeps this
  work outside that rule's blast radius.
- The transport gains a second failure idiom. This is a real cost: a reader must
  now know which of its two entry points raises. It is mitigated by the split
  being along an obvious line - probes do not raise, calls do - and by
  documenting the contract at both, but a future contributor who assumes one
  idiom covers the module will be wrong.
- A transport-wide redirect refusal may block a legitimate future need. The
  cost is bounded and visible: such a need must argue against this record, which
  is the intended failure mode rather than an oversight.
- Correcting the general default timeout may surface callers that depend,
  knowingly or not, on an unbounded wait. The enumeration required by D3 exists
  to find them before the change rather than after; if any legitimate caller
  needs no bound, it must pass that explicitly.
- The deferred identity decision leaves a known weakness in the stop path for as
  long as it remains unauthored, protected only by the redirect refusal this
  record installs. That protection is real but narrow - it confines the
  responder to the local port and does not make the check sound - and the delay
  should be treated as a scheduling debt with a named successor record, not as
  an acceptance of the weakness.
- The pathway this opens is a service-client transport that is safe to
  consolidate further onto. Once it refuses redirects, bounds its waits, and has
  a stated contract per entry point, the remaining duplicated probes in the
  command-line surface become candidates for the same treatment without
  relitigating any of the three decisions made here.

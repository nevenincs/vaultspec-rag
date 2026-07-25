---
tags:
  - '#adr'
  - '#service-release-compatibility'
date: '2026-07-25'
modified: '2026-07-25'
related:
  - '[[2026-07-25-service-release-compatibility-reference]]'
---

# `service-release-compatibility` adr: `client and service release compatibility` | (**status:** `accepted`)

## Problem Statement

A vaultspec-rag client and the daemon it drives are separate installs that can be
upgraded independently, and until now nothing in the service surface let either notice
that they were different releases. The package version reached no wire surface at all:
not the health route, not the readiness route, and not the discovery sidecar, which
published the interpreter version but never the package's. The one version field that did
exist - the discovery schema discriminator - was written by both writers and compared by
neither, despite the schema document instructing consumers to pin on the pair and refuse
a file they do not understand.

The consequence was silent behavioural mismatch rather than a detectable failure. Route
handlers read known keys off an untyped request body, so a field an older daemon does not
know is dropped rather than rejected: a newer client's search-noise filters were ignored
and the answer computed over a different candidate set, returned with a 200 and no
indication that anything had been discarded. The start verb confirmed an existing daemon
by process identity and token only, so it reported an idempotent already-running success
for a daemon belonging to an entirely different install.

A decision is needed now because the drift is routine, not exotic: a globally installed
tool alongside a project-local environment, one machine with several checkouts, or an
upgrade that replaces the client while the previous daemon keeps running all produce it.

## Considerations

- The daemon is a machine-global singleton; one running instance serves every root, so a
  foreign daemon is not an isolated per-project inconvenience.
- The project already has a precedent for this class of check: its own attach path to
  Qdrant fails closed on a version mismatch and refuses even when the version cannot be
  read, on the stated ground that attaching to an unconfirmable version defeats the check.
- Health, status, jobs, logs and search diagnostics are service-domain behaviour that
  entry points adapt to; a compatibility verdict computed differently by the CLI and the
  MCP would show operators conflicting names and remediation for one condition.
- Lifecycle verbs owe exactly one structured envelope per exit path, must treat an
  already-satisfied request as success, and must exit non-zero whenever the requested
  state was not achieved.
- The discovery sidecar and the machine pointer are read on every command; a version
  carried there is free to compare, whereas a version available only over HTTP costs a
  probe on paths that currently make none.

## Considered options

- **Publish the version and compare it client-side.** Chosen. The daemon stamps its
  release into everything it already publishes; one client-side module classifies it;
  each surface renders the verdict. Cheap, works on paths that make no HTTP call, and
  keeps the daemon free of any knowledge of its callers.
- **Have the daemon reject requests from incompatible clients.** Rejected. It requires
  every client to send its version on every request and a route-level gate to read it,
  which is a larger change than the detection it buys, and it cannot help the paths that
  matter most (attach and discovery) because those happen before any request.
- **Compare only the discovery schema pair.** Rejected. The pair describes the shape of
  the sidecar, not the release of the daemon. Two releases that agree on the file format
  and disagree on request fields - the actual observed failure - are indistinguishable
  under it. Enforced anyway, as a separate and narrower obligation.
- **Compatibility ranges rather than exact equality.** Rejected for now. A range needs a
  declared compatibility policy per release and a maintained matrix; nothing in the
  project declares one, so any range would encode a guess. Exact equality is the honest
  reading of "these are the same install", and the remediation is one command.
- **Warn but proceed.** Rejected. A warning on a path whose whole failure mode is silent
  degradation reproduces the problem: the operator gets a line of text and a result
  computed over the wrong candidate set. The issue is that the mismatch is undetectable,
  and a warning nobody must act on leaves it effectively undetected.

## Constraints

- No new dependency and no new probe: the version must travel on payloads that are
  already published and already read.
- The comparing module must stay torch-free and import-light, because the MCP server, the
  service client, and the CLI service-control commands all reach it and none may load the
  GPU stack.
- Backward compatibility cuts one way only. A daemon that reports no version cannot be
  made to report one retroactively, so the unreadable case must be a first-class state
  with its own diagnosis rather than being folded into "the versions differ".
- The stop verb must never be gated. It is the remediation for every incompatible state,
  and gating it would leave an operator unable to act on the verdict.
- This decision does not depend on any in-flight feature; it touches the publication
  sites and the client surfaces only.

## Implementation

One field name and one classifier are declared in a single import-light client module.
The daemon stamps that field into the health payload, the readiness report, and the
daemon-owned discovery snapshot - which is the source for both the sidecar and the
machine pointer, so one insertion covers both views - and the spawning parent stamps it
into its own initial sidecar write.

The classifier turns any published payload into a three-state verdict: matching,
mismatched, or unreported. The verdict carries both versions, a structured error code per
state, a one-line operator-facing reason, and the single remediation, so no surface
re-derives the comparison or invents its own wording.

Surfaces adapt to that verdict. The start verb's attach path classifies the health
response it already fetches and, when the verdict is incompatible, converges on the
shared lifecycle failure helper: one envelope, both versions in its data, the restart as
its next action, and a non-zero exit in both human and machine modes. The MCP's single
port-precondition helper classifies the discovery payload it already reads, so every tool
refuses with the same code the CLI uses and no extra round trip. The status verb prints
the release unconditionally and adds the reason and remediation when it is incompatible.
The doctor folds an incompatible release into its exit code at the same tier as a daemon
that is expected but not live.

Separately, the schema discriminator becomes enforced rather than merely written. A
payload declaring a pair this build does not implement resolves as degraded with its own
reason, distinct from absence, because a file this build cannot read may still describe a
running service and reporting it as stopped would invite a caller to start a second
daemon that must then lose the machine race. A payload carrying neither field predates
the discriminator and is still read on its other evidence.

## Rationale

Exact equality with a fail-closed unreadable case wins on the project's own precedent.
The Qdrant attach path already refuses a server whose version cannot be confirmed, and
the reason recorded there transfers without modification: a check that accepts an
unconfirmable value is not a check. Applying a weaker standard to the project's own
daemon than it applies to a third-party one would be incoherent.

Publishing on the discovery views rather than only over HTTP is what makes the gate
usable everywhere. The paths that most need it - resolving a port before a tool call, and
confirming an existing daemon before attaching - either make no HTTP call or make exactly
one they already make, so the comparison is free at every site.

Placing the classifier in the shared client layer rather than in either entry point is
what keeps the CLI and the MCP from drifting into two diagnoses of one condition, which
is the failure the service-surface constraint exists to prevent.

Refusing rather than warning follows from what the problem actually is. The mismatch was
already visible in principle - the identifying fields were published and read for display

- and it still went undetected because nothing had to act on them. A verdict that does
  not change an outcome would reproduce that exactly.

## Consequences

The gain is that client/server skew becomes a named, actionable condition with one
remediation, on every surface, instead of a silent difference in results.

The cost is a real behavioural break at the moment of upgrade. An operator who upgrades
the client while an older daemon is running will find that every MCP tool call and the
start verb refuse until the daemon is restarted, and a daemon predating this change
reports no version at all, so it is refused as unconfirmable rather than as mismatched.
That is the intended trade - it is the first upgrade at which the drift is visible - but
it is a harder edge than a warning, and the remediation has to stay one command for that
to be defensible.

Exact equality means every release bump invalidates a running daemon, including a patch
release that changes nothing about the wire surface. This is deliberately conservative
and can be relaxed later, but only once the project declares a compatibility policy that
a range could encode; relaxing it before then would replace a strict rule with a guess.

The gap this leaves open is the one the mismatch exploited: route handlers still read
known keys off untyped request bodies, so an unrecognised field is still dropped rather
than refused. The release gate makes the skew detectable, and it does not make the
dropped field visible. Moving those routes onto typed request models remains the durable
fix and is deliberately out of scope here, because it is a route-layer refactor with a
much wider blast radius than the compatibility signal.

Enforcing the schema pair also changes a previously permissive read path. Nothing in the
tree writes a pair this build does not implement, so there is no behaviour change today;
the effect is reserved for a future format bump, where a mixed-version machine now
degrades honestly instead of misreading a document it does not understand.

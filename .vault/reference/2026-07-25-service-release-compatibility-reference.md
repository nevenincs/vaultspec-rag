---
tags:
  - '#reference'
  - '#service-release-compatibility'
date: '2026-07-25'
modified: '2026-07-25'
related: []
---

# `service-release-compatibility` reference: `compatibility chain survey`

A survey of every place the running service publishes something that identifies itself,
and every place a client reads one of those values, taken before deciding how to signal
client/server release drift. Sources are the service surface modules and the discovery
schema document as they stood at the survey date.

## Summary

### The package version reached no wire surface

`vaultspec_rag.__version__` was referenced nowhere outside its own resolving
`__getattr__` in `src/vaultspec_rag/__init__.py`.

- The health payload in `src/vaultspec_rag/server/_lifespan.py` carried `executable`,
  `prefix`, `base_prefix`, `virtual_env`, `service_token`, and a bare `schema_version` -
  the latter being the storage-schema version, not the package release.
- `ReadinessReport.to_dict` in `src/vaultspec_rag/_readiness.py` carried the storage
  schema descriptor and the support profile, and no package version. A test in
  `src/vaultspec_rag/tests/test_readiness.py` asserts that key set exactly, on the stated
  ground that readiness must stay a bounded snapshot.
- The discovery snapshot in `src/vaultspec_rag/server/_lifecycle.py` published
  `python_version` - the interpreter, not the package. That snapshot is the single source
  for both published views: it is written to the status sidecar and to the machine
  pointer in the same locked publication, so one field added there reaches both.
- The spawning parent's own initial sidecar write in
  `src/vaultspec_rag/cli/_service_status.py` published the schema pair, pid, port, and
  start timestamp only.

### The version field that existed was written by both writers and compared by none

`SERVICE_DISCOVERY_SCHEMA` and `SERVICE_DISCOVERY_VERSION` in
`src/vaultspec_rag/serviceclient/_discovery.py` are stamped by both writers named above.
Neither `_discovery.py` nor `_machine_lock.py` - the two modules that read those files -
compared the read value against the constant. The only comparisons in the tree were in
`src/vaultspec_rag/tests/test_service_discovery_schema.py`.

`docs/service-discovery.md` documents the pair and instructs consumers to pin on it and
refuse a file they do not understand - an obligation no client code implemented.

### The identifying fields that were published were read for display only

The health route published exactly the fields that would identify a foreign build.
`src/vaultspec_rag/cli/_status_render.py` printed `executable` as a "Service env" line and
did nothing else with it.

The start verb's attach path (`_existing_service_running` in
`src/vaultspec_rag/cli/_service_start.py`) confirmed an existing daemon through
`_is_our_service` in `src/vaultspec_rag/cli/_process.py`, which checks pid liveness, a
token round-trip, and the executable *name*. No release comparison existed on that path,
so a daemon from another install satisfied it and the verb reported the idempotent
already-running success for it.

### Route payloads are read untyped, so an unknown field is dropped rather than refused

The search handlers in `src/vaultspec_rag/server/_routes.py` pull each known key off a raw
dict with repeated `payload.get(...)` calls rather than validating against a request model.
An unrecognised field is therefore silently discarded. Concretely, a newer client sending
the search domain filters - carried as inline query tokens - to an older daemon receives a
normal 200 computed over the unfiltered candidate set.

This is the mechanism that makes release drift *silent* rather than merely present, and it
is the reason a detection signal was judged necessary before the route-typing work.

### The project already has a fail-closed precedent for this class of check

The daemon's own attach path to Qdrant in `src/vaultspec_rag/qdrant_runtime/_resolve.py`
refuses on a version mismatch, and refuses as well when the Qdrant version cannot be read
at all. The code comment there records the reason: attaching to a server whose version
cannot be confirmed defeats the purpose of the check.

The same codebase had no equivalent gate for its own clients attaching to its own daemon.
This asymmetry is the strongest single argument found for the policy eventually chosen -
exact equality, with an unreadable version failing closed rather than passing.

### Constraints the surrounding code imposes on any fix

- The MCP server, the service client, and the CLI service-control commands must stay
  torch-free, so any shared comparison module has to be import-light.
- The MCP's `_require_port` in `src/vaultspec_rag/mcp/_tools.py` is the single
  precondition helper every tool passes through, and it already resolves the discovery
  pointer. A version carried on that pointer is therefore comparable with no additional
  round trip.
- Lifecycle verbs converge on shared success and failure helpers in
  `src/vaultspec_rag/cli/_service_lifecycle.py`, which own the one-envelope-per-exit-path
  and non-zero-on-unachieved-state contracts; a new refusal must route through them
  rather than emit its own output.
- `MachineResolution` in `src/vaultspec_rag/serviceclient/_discovery.py` already
  distinguishes `ready`, `absent`, and `degraded`, with `degraded` carrying a reason and
  documented as deliberately distinct from `absent` so a live-but-unpublished daemon is
  never rendered as stopped. A refusal to read an unrecognised document belongs in that
  vocabulary rather than collapsing to absence.

---
tags:
  - '#reference'
  - '#service-release-compat'
date: '2026-07-25'
modified: '2026-07-25'
related: []
---

# `service-release-compat` reference: `Compatibility surface audit`

A source audit of every place a client and the daemon exchange identity, taken before any
code was written, to establish what already exists and what is genuinely absent. Sources
were the service routes, the discovery contract and its two writers and two readers, every
client that reads a health payload, and the existing version-comparison idioms in the tree.

## Summary

### The package release reaches no wire surface

`vaultspec_rag.__version__` is defined in `src/vaultspec_rag/__init__.py` (resolved lazily
through the package `__getattr__`, because reading installed metadata is the dominant cost
of importing the package). Outside that module and the `--version` flag in
`src/vaultspec_rag/cli/_app.py`, nothing in `src/` reads it.

It is absent from all three identity surfaces:

- The health handler in `src/vaultspec_rag/server/_lifespan.py` returns `executable`,
  `prefix`, `base_prefix`, `virtual_env`, and a bare `schema_version` - the *storage*
  schema, not the package version.
- `ReadinessReport.to_dict` in `src/vaultspec_rag/_readiness.py` returns six keys, none of
  them a package version. A test asserts that key set exactly.
- The daemon's discovery snapshot in `src/vaultspec_rag/server/_lifecycle.py` publishes
  `python_version` - the *interpreter* version - and nothing reads it anywhere in `src/`.

### The discriminator that does travel is written by two, read by none

`SERVICE_DISCOVERY_SCHEMA` and `SERVICE_DISCOVERY_VERSION` are defined in
`src/vaultspec_rag/serviceclient/_discovery.py` and stamped by both writers: the daemon
snapshot in `src/vaultspec_rag/server/_lifecycle.py` and the CLI launcher's
`_write_service_status` in `src/vaultspec_rag/cli/_service_status.py`.

Neither reader compares them. `_read_service_status` requires only `pid` and `port`;
`resolve_machine_service` validates port coercibility, pointer-pid-equals-holder, and
heartbeat staleness, and never touches the declared schema or version. The machine-pointer
reader in `src/vaultspec_rag/_machine_lock.py` is deliberately tolerant and validates
nothing but JSON-object-ness; its publisher validates only that the payload pid matches the
lease. Every comparison of the pair anywhere in the tree is in a test fixture.

Meanwhile `docs/service-discovery.md` documents the pair and instructs consumers to pin on
it and refuse a file they do not understand.

### Identity checks confirm ownership, not build

`_is_our_service` in `src/vaultspec_rag/cli/_process.py` compares the per-process identity
token when both sides have one, and falls back to an executable-name and cmdline check
otherwise. `_health_matches_pointer` in `src/vaultspec_rag/serviceclient/_status.py`
requires the token and pid to match the machine pointer. Both are satisfied by a foreign
build of the same tool, so the attach path in `src/vaultspec_rag/cli/_service_start.py`
reports `already_running` for a daemon from a different install.

The identifying fields that *are* published are read for display only - for example the
"Service env" line in `src/vaultspec_rag/cli/_status_render.py` prints the daemon's
executable and does nothing else with it.

### Route asymmetry constrains where a handshake can live

The health route is registered outside the token gate in `src/vaultspec_rag/server/_main.py`
and is ungated; the readiness route in `src/vaultspec_rag/server/_routes.py` calls
`require_token` first. A signal that must be readable before a client holds credentials can
therefore only ride the health route.

### Existing version-comparison idioms available to reuse

- **Strict schema rejection.** `src/vaultspec_rag/watcher_retry.py` refuses a state or
  marker payload whose `schema_version` is not exactly the expected integer, using an exact
  type test rather than an instance check so a boolean cannot satisfy an integer pin. This
  was the only strict "refuse a schema I do not understand" reader in the tree.
- **Pinned-binary version equality.** The Qdrant runtime compares a live and on-disk server
  version against a committed constant and refuses when the version merely cannot be read.
  This is the project's precedent for failing closed on a version mismatch - and the
  contrast that makes its absence on the client/daemon boundary notable.
- **Storage schema integers.** Compared for data-shape compatibility in the store and
  indexer modules; same-process or on-disk, never process-to-process.

No code anywhere in `src/` compares a package version between two processes. `packaging.version`
appears only in the repo-root install smoke check, against a different package.

### Assertions that will move when a field is added

- `test_readiness.py` asserts the readiness key set exactly.
- `test_cli_service_status.py` asserts the launcher's status-write key set exactly.
- `test_cli_server_start.py` asserts the attach-detection return value by full equality.
- `test_serving_verdict_parity.py` binds the CLI's serving verdict to the service's own
  health status from one shared table, so a new server-side degradation reason the CLI does
  not know about fails there.

The health payload has no exact-key-set assertion; its tests check named keys individually.

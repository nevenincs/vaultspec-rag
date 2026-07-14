---
tags:
  - "#audit"
  - "#control-plane-affordances"
date: '2026-07-13'
related:
  - "[[2026-07-13-control-plane-affordances-adr]]"
  - "[[2026-07-13-control-plane-affordances-plan]]"
promoted_to:
  - 'rule:broker-facing-cli-outcomes-are-structured-and-idempotent'
modified: '2026-07-14'
---

# `control-plane-affordances` audit: `execution review of the survey root lookup and stop --json`

## Scope

Post-execution review of the six-step control-plane-affordances plan: the
root-scoped survey lookup (route, transport, MCP client, CLI) and the
`server stop --json` envelope parity, commits `031b900` through `43ec308`.
Reviewed for envelope-contract safety (one envelope per exit path), the
ADR's exit-code decisions, single-authority prefix derivation, signature-
change regressions, rule conformance (`service-domain-owns-operability`,
`operator-views-are-bounded`, test integrity), and idiom quality.

## Findings

### envelope-contract | pass | one envelope per stop exit path, no stdout leakage

Every terminal branch of `service_stop` / `_stop_service_on_port` routes
through exactly one `_stop_success` or `_fail_stop`; the terminate helpers
write only to the rotating log, and `_reclaim_machine_singleton` prints
nothing. Exit codes match the ADR: `identity_unconfirmed` exits 1 in both
modes, all satisfied outcomes exit 0. Both prefix computations (route and
CLI-direct fallback) resolve through `root_collection_prefix()` - no hash
reimplementation. Signature changes are regression-clean: the single
`_survey_from_service` caller was updated and `_stop_service_on_port`'s new
parameter defaults preserve the pre-existing test call site.

### relative-root-divergence | medium | relative --root resolves against the daemon cwd on the service-first path

The CLI forwards `--root` verbatim; the daemon resolves it against its own
cwd (inherited from whatever shell ran `server start`), while the CLI-direct
fallback resolves against the operator's cwd - the same command silently
yields different prefixes depending on whether a daemon is up. Absolute
paths (the dashboard's usage) are unaffected. Fix: resolve `--root` to an
absolute path in the CLI before dispatch.

### cli-direct-envelope-drift | medium | CLI-direct --json survey omits returned, route includes it

The route emits `{namespaces, returned, total, limit, queried_root?}`; the
CLI-direct `_emit_survey_json` emits `{namespaces, total, queried_root?}`,
so the shape a broker parses depends on whether a daemon answered. The
drift predates this feature but the root work widens the parsed surface.
Fix: add `returned` to the CLI-direct envelope for parity.

### survey-help-omits-root | low | command one-line help does not mention the root lookup

The `survey` command's `help=` string omits the new `--root` capability;
only the option help and docstring carry it. Fix: extend the help line.

### total-postfilter-doc | low | total reflects the post-root-filter count without a docstring note

With `root`, `total` counts the namespaces after prefix narrowing -
correct and consistent with the status filter, but worth one docstring
line so consumers do not read it as the server-wide count.

### preexisting-daemon-reindex | noted | indexed-root integration test blocked by a regression outside this feature

The daemon-driven vault reindex errors inside the spawned qdrant ("failed
to open mutable map index on gridstore: os error 3") on this machine, also
failing main's untouched `test_multi_project_search_isolation`. Out of this
feature's scope; needs its own investigation.

### daemon-reindex-root-cause | resolved | qdrant gridstore breaks on Windows storage paths over ~105 characters

Root-caused by an A/B repro against the same pinned qdrant 1.18.2 binary
and identical collection schema: `create_collection` succeeds with a
storage dir of 100 characters and fails with the gridstore "os error 3" at
110 - the internal `collections/<name>/segments/<uuid>/...` layout crosses
the classic MAX_PATH boundary, and `LongPathsEnabled=1` does not help (the
engine's file handling ignores it). Deep pytest tmp paths (~95-115 chars)
cross the cliff; the real machine dir (~48 chars) does not, which is why
the resident service has 256 finished jobs and zero failures. Fix: the
integration `_service_env` helper now places the isolated qdrant storage
under a short unique temp dir (~56 chars) with teardown cleanup, and the
supervisor logs a legible warning on Windows when the storage dir exceeds
90 characters so a real operator with a deep
`VAULTSPEC_RAG_QDRANT_STORAGE_DIR` sees the cause at spawn instead of
opaque 500s on first index. Follow-up candidate: test whether a newer
qdrant pin fixes the engine-side limit (RocksDB is removed upstream from
1.17, so gridstore is unavoidable).

### qdrant-pin-followup | resolved | no newer qdrant exists; the pin stays at 1.18.2

Investigated 2026-07-14: 1.18.2 is the latest stable upstream release
(releases page, the releases API, and the tag list all agree; nothing
newer including prereleases), so no pin bump is available. Gridstore is
the 1.18-era storage engine (RocksDB removal completed in that line) and
its deep on-disk layout is what crosses MAX_PATH; no upstream issue
matches this exact long-path signature (the nearest Windows
collection-create issues are unrelated). The >90-character supervisor
warning remains the durable mitigation. Optional next steps surfaced to
the operator: file a minimal upstream repro issue, or harden the warning
into enforcing a short managed storage root on Windows.

### daemon-reindex-disk-full | resolved | a second cause was stacked under the path cliff: the dev box disk was full

After the path fix the failure changed shape ("Failed to create storage
for mmap sparse vectors: failed to set length of file") - `C:` was down to
677MB free out of 1TB, and each qdrant collection create preallocates
roughly half a GB of mmaps. The diagnostic repro runs themselves had eaten
about 4.4GB of temp storage; deleting that debris plus stale pytest tmp
recovered to ~5.3GB free and both tests pass. Because a test that holds
its daemon open past `_service_env`'s exit leaves its storage locked at
teardown (rmtree silently leaves ~0.5-1GB behind), the helper now sweeps
stale leftovers under the short storage base on entry, so leaks self-heal
on the next run instead of accumulating on an already-tight disk. The
operator should still free space on `C:` - ~5GB headroom is one integration
run away from failing again.

## Recommendations

- Apply the two medium and two low fixes in a follow-up commit (all
  one-to-three-line changes); done as part of this execution cycle.
- Open a separate investigation for the pre-existing daemon-reindex /
  qdrant gridstore failure, which currently blocks every
  reindex-through-daemon integration test on this box.
- The `broker-facing-cli-outcomes-are-structured-and-idempotent`
  codification candidate has now held through its second execution cycle
  (start, then stop); consider promotion via
  `vaultspec-core vault rule promote`.

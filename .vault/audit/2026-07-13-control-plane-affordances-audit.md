---
tags:
  - '#audit'
  - '#control-plane-affordances'
date: '2026-07-13'
modified: '2026-07-13'
related:
  - '[[2026-07-13-control-plane-affordances-adr]]'
  - '[[2026-07-13-control-plane-affordances-plan]]'
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

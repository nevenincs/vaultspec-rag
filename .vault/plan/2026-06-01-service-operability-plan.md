---
tags:
  - '#plan'
  - '#service-operability'
date: '2026-06-01'
tier: L2
related:
  - '[[2026-06-01-service-operability-adr]]'
  - '[[2026-06-01-service-operability-research]]'
---

# `service-operability` `auto-reindex + watcher control (CLI/MCP parity) implementation` plan

## Description

This plan implements the auto-reindex and watcher control contract decided in
the service-operability ADR, grounded by the service-operability research. It
folds GitHub issues #143 (watcher configurability) and #144 (auto-reindex as a
first-class, opt-out-able feature) under one governing decision: full
bidirectional CLI and MCP parity over the watcher and auto-reindex surface, with
CLI control riding the existing MCP-client seam rather than a new transport.

The work proceeds backend-first: config keys and their env coercion (P01),
wiring those values into the running watcher behind a `watch_enabled` guard
(P02), startup CLI flags translated to environment before the daemon spawns
(P03), runtime control parity via MCP tools and matching CLI subcommands (P04),
and documentation across the required surfaces (P05).

P05 also delivers this cluster's slice of #145 (harden the shipped builtin rule
as an imperative DO/DO NOT mandate): the obsolete "manually reindex" directive
is inverted to "DO NOT manually reindex; DO use `--no-watch` for pull-only", the
new watcher knobs are stated as directives, and a maintenance check guards the
rule against drifting behind shipped behaviour. The full imperative restructure
of the rule (the resident-service single-writer mandate, RAG-vs-grep selection)
stays with #145 as a consolidated documentation-workflow pass after #142, so the
rule is not rewritten twice.

Out of scope by ADR decision: the service-managed periodic full rebuild
(deferred, default-off, its own decision), watch include and exclude globs
(deferred), per-project persisted config (global-only; runtime reconfigure is
per-root and non-persistent), the HTTP observability surface for #142 (ADR-B),
and the full #145 rule restructure (consolidated pass after #142).

## Steps

The implementation is organised into the five Phases below (P01 through P05).
Each Step row names exactly one file or cohesive area; every Step inherits its
authorising ADR and research through the `related` frontmatter.

### Phase `P01` - backend config keys

Add watcher config keys to the config layer with env coercion and explicit-over-env-over-default precedence.

- [x] `P01.S01` - Add watch_enabled, watch_debounce_ms, and watch_cooldown_s to the RAG defaults; `src/vaultspec_rag/config.py`.
- [x] `P01.S02` - Add the three VAULTSPEC_RAG_WATCH env members and override-map entries; `src/vaultspec_rag/config.py`.
- [x] `P01.S03` - Add unit tests for watcher-config precedence and bool, int, and float coercion including WATCH_ENABLED false parsing; `src/vaultspec_rag/tests/test_config.py`.

### Phase `P02` - wire config into the watcher and add the enable guard

Thread config-derived debounce and cooldown into the running watcher and gate auto-start on watch_enabled.

- [x] `P02.S04` - Guard \_ensure_watcher on watch_enabled and pass config debounce and cooldown into watch_and_reindex; `src/vaultspec_rag/mcp_server.py`.
- [x] `P02.S05` - Add an integration test that watch_enabled false yields a pull-only service and that custom debounce and cooldown propagate; `src/vaultspec_rag/tests/integration/test_watcher_config.py`.

### Phase `P03` - startup CLI flags and env translation

Add watcher flags to service start and translate operator-set flags into VAULTSPEC_RAG_WATCH env before the daemon is spawned.

- [x] `P03.S06` - Add the watch, no-watch, watch-debounce-ms, and watch-cooldown-s options to service start; `src/vaultspec_rag/cli.py`.
- [x] `P03.S07` - Translate non-default watcher flags into VAULTSPEC_RAG_WATCH env on the child env in \_spawn_service; `src/vaultspec_rag/cli.py`.
- [x] `P03.S08` - Add tests for flag-to-env translation via parameter source and preserved JSON envelope and exit codes; `src/vaultspec_rag/tests/test_cli_service_watch.py`.

### Phase `P04` - runtime control parity (MCP tools and CLI subcommands)

Expose watcher start, stop, reconfigure, and state via MCP tools and matching CLI subcommands over the existing MCP-client seam.

- [x] `P04.S09` - Add start_watcher, stop_watcher, reconfigure_watcher, and get_watcher_state MCP tools reusing the watcher internals; `src/vaultspec_rag/mcp_server.py`.
- [x] `P04.S10` - Add the server watcher subcommand group driving the daemon over the \_try_mcp_admin seam; `src/vaultspec_rag/cli.py`.
- [x] `P04.S11` - Add integration tests for the four watcher MCP tools including reconfigure restart semantics; `src/vaultspec_rag/tests/integration/test_watcher_control.py`.
- [x] `P04.S12` - Add CLI parity tests for the server watcher subcommands including disabled pull-only state reporting; `src/vaultspec_rag/tests/test_cli_watcher.py`.

### Phase `P05` - docs parity

Update the builtin rule directives (per #145) and the two readmes for the new watcher config and control surface, and add a maintenance check that guards the rule against drifting behind shipped behaviour.

- [ ] `P05.S13` - Rewrite the watcher and auto-reindex directives in the builtin rule as imperative DO and DO NOT, inverting the obsolete manual-reindex instruction, then sync; `.vaultspec/rules/rules/vaultspec-rag.builtin.md`.
- [ ] `P05.S14` - Document watcher config keys, env vars, flags, and subcommands in the top-level readme; `README.md`.
- [ ] `P05.S15` - Document the same watcher config and control surface in the package readme; `src/vaultspec_rag/README.md`.
- [ ] `P05.S16` - Add a maintenance check asserting the builtin rule carries the required auto-reindex and opt-out directive tokens; `src/vaultspec_rag/tests/test_builtin_rule_directives.py`.

## Parallelization

Phases are sequenced by dependency. P01 (config keys) is the foundation and has
no dependencies. P02 depends on P01 (it reads the new keys). P03 depends on P01
(the flags set the new env vars) and is independent of P02, so P02 and P03 may
proceed in parallel once P01 lands. P04 depends on P02 (it reuses the guarded
watcher internals) and on P01. P05 depends on every surface being final (P01
through P04). Within a phase, the implementation Step precedes its test Step;
the two `config.py` Steps in P01 (S01, S02) are one cohesive edit and land
together.

## Verification

The plan is complete when every Step is closed. Concretely: the three watcher
config keys resolve correctly across explicit, env, and default precedence with
bool, int, and float coercion (unit tests pass); `watch_enabled` false yields a
pull-only service with no watcher started, and custom debounce and cooldown
reach the running watcher (integration tests pass); service start flags
translate to `VAULTSPEC_RAG_WATCH` env only when set, preserving the JSON
envelope and exit-code contract (tests pass); the four watcher MCP tools and the
matching `server watcher` CLI subcommands behave identically over the MCP-client
seam, including reconfigure restart semantics and disabled-state reporting
(integration and CLI tests pass); ruff and ty are clean with no skips; the
watcher config and control surface is documented in the rule source (synced),
the top-level readme, and the package readme; the builtin rule's reindex
directive is inverted to the auto-reindex/opt-out form and the maintenance check
asserting the required directive tokens passes (per #145). Final sign-off is a
vaultspec-code-review pass.

---
tags:
  - '#audit'
  - '#provider-mcp-enrollment'
date: '2026-07-15'
modified: '2026-07-15'
related:
  - "[[2026-07-15-provider-mcp-enrollment-adr]]"
  - "[[2026-07-15-provider-mcp-enrollment-research]]"
  - "[[2026-07-15-provider-mcp-enrollment-plan]]"
---

# `provider-mcp-enrollment` audit: `native MCP release readiness`

## Scope

The complete `origin/main...HEAD` feature diff was audited against the accepted
research, ADR, and execution plan. The review covered RAG/Core responsibility
boundaries, provider-native install and uninstall behavior, ownership preservation,
dependency-extra provenance, dry-run and idempotency semantics, report and CLI failure
contracts, real-host acceptance, package metadata, locked dependencies, wheel smoke
coverage, and the quality of the added tests.

## Findings

### provider-error-exit-contract | high | MCP reconciliation failures still return successful CLI exits

Core communicates ordinary provider failures through `SyncResult.errored` and
`SyncResult.errors`; it does not raise them. `_run_core_sync` and `_run_mcp_cleanup`
append those results, but the install and uninstall CLI handlers only fail on raised
exceptions (plus the separate consumer-TOML inspection error). A real install against
a malformed Codex target therefore exited zero while reporting one provider error. A
second real install with a corrupt MCP ownership sidecar also exited zero, and the
failure disappeared entirely because `_provider_sync_outcomes` serializes only
`per_tool` children while the ownership error exists only on the top-level result. The
same unchecked result contract is used by selective uninstall. These paths can report
successful installation or removal even though the requested provider entry was not
changed, and the top-level ownership failure is invisible in both JSON and human output.

### dry-run-source-overlay | high | Install previews do not model MCP source addition or removal

`_seed_builtins` correctly avoids writes during a preview, but `_run_core_sync` then
calls Core against the unchanged on-disk source tree. On a fresh dual-provider workspace,
a real dry-run reported zero additions for both providers because the canonical RAG
source had not been materialized. On an enrolled workspace, `--no-mcp --dry-run`
reported both provider entries as unchanged even while the seed report said the source
would be removed. The preview is byte-inert, but its provider plan is not the plan the
corresponding real operation will execute, contrary to the feature's dry-run acceptance
contract.

### published-core-smoke-pin | low | The wheel smoke check rejects later compatible Core releases

`check_published_core_floor` first verifies the intended metadata floor
`vaultspec-core>=0.1.44`, then separately requires the installed Core version to equal
`0.1.44`. The documented isolated smoke command resolves dependencies from the public
index, so once a compatible `0.1.45` or later release exists, a newly built RAG artifact
can satisfy its declared dependency correctly and still fail this smoke check. The
assertion tests a transient resolver outcome rather than the published minimum-version
contract.

### dormant-uv-add-path | low | The superseded uv-add implementation and tests remain live in the source tree

The feature removes the only production call to `_run_uv_add_mcp_extra` and replaces it
with placement-aware TOML reconciliation, but `_uv_sync` still exports the unused
subprocess helper and its classifier, and `test_install_mcp_extra` continues testing that
dormant classifier. The test module narrative and install option help also still describe
the implementation as `uv add vaultspec-rag[mcp]`. This leaves executable dead code and
tests that can stay green while the real placement engine regresses, and gives operators
an inaccurate account of whether installation performs dependency resolution.

### dry-run-mode-overlay | high | The preview projection omits the requested package mode and can report unchanged for a real update

The source overlay added after the first audit copies the committed `.vaultspec` tree
and provider files, but dry-run still skips `persist_rag_mode`, so the projection never
receives the package declaration that the corresponding real install writes before Core
renders companion definitions. Core therefore resolves a missing RAG declaration through
its legacy dependency-mode bridge even when the requested install mode is `tool`. In a
real legacy dependency-shaped workspace with the declaration removed, an explicit
tool-mode upgrade preview reported both Claude and Codex as `[UNCHANGED]`; the
corresponding real upgrade reported a skip followed by `[UPDATE]` for both providers and
changed each launch from `uv run` to the canonical `uvx --from vaultspec-rag[mcp]`
shape. Fresh additions and unenrollment prunes are now counted correctly and the preview
is byte- and lock-inert, but it still does not model the same desired state as the real
operation for mode establishment or migration. This remains release-blocking under the
accepted exact-preview contract.

### runtime-uv-add-guidance | low | Missing-extra recovery still directs tool-mode projects to mutate dependencies

The dormant `_run_uv_add_mcp_extra` helper, exports, classifier tests, install help, and
test narrative were removed. One operator-facing runtime error still says to run
`uv add vaultspec-rag[mcp]` or re-run install "which adds it by default." That advice is
not mode-aware: the accepted tool-mode contract deliberately performs no project
dependency mutation and launches through `uvx --from vaultspec-rag[mcp]`. The remaining
message can therefore reintroduce the dependency placement that the feature removed.

## Recommendations

- Treat any MCP result with `errored` or `errors` as an unsuccessful requested
  operation, preserve both top-level and per-provider errors in structured reports, and
  make install and uninstall return a non-zero CLI status. Add real malformed-target and
  corrupt-ownership acceptance for both commands.
- Give install dry-run a source overlay (or a Core planning input) representing the
  would-be seeded or removed canonical definition, then assert fresh additions and
  `--no-mcp` prunes for Claude and Codex without byte changes.
- Keep the exact `>=0.1.44` metadata-floor assertion, but validate the resolved Core with
  specifier membership and required API behavior instead of equality to one installed
  version.
- Remove the orphaned MCP `uv add` helper, classifier tests, and stale prose, or reconnect
  an explicit package-resolution step if that remains part of the intended contract.
- Persist the requested RAG package declaration inside the temporary preview projection
  before invoking Core, without touching the real workspace. Add a legacy dependency to
  tool-mode upgrade regression that requires preview and real provider actions to agree
  for both Claude and Codex while retaining the existing whole-workspace byte and lock
  assertions.
- Replace the remaining runtime `uv add` recovery sentence with mode-neutral guidance
  that points operators to the enrolled canonical launch or the placement-aware install
  command without prescribing a project dependency mutation.

## Remediation verification

- `provider-error-exit-contract`: verified remediated. Direct lifecycle exceptions,
  unattributed top-level Core errors, and per-provider errors are retained in report JSON
  and human rendering; both install and uninstall raise exit code 2 when
  `mcp_sync_failed` is true. Real malformed-Codex and corrupt-ownership tests pass.
- `dry-run-source-overlay`: partially remediated. Fresh enrollment now reports one
  Claude and one Codex addition, `--no-mcp` reports one prune for each, and whole-workspace
  bytes and lock paths remain stable. The new `dry-run-mode-overlay` finding prevents
  closure because the projected render mode can differ from the real operation.
- `published-core-smoke-pin`: verified remediated. The smoke keeps the exact
  `vaultspec-core>=0.1.44` metadata-floor assertion, accepts any installed version in the
  specifier, imports all three required lifecycle APIs, and exercises native-provider
  status plus selective uninstall behavior.
- `dormant-uv-add-path`: implementation and test-code portions verified remediated. No
  production or test reference to the deleted helper or classifier remains, and the
  focused placement tests pass. The new `runtime-uv-add-guidance` finding leaves the
  stale operator guidance portion open.

Verdict: **not release-ready**. The provider error contract and Core-floor smoke are
closed, while the dry-run remediation remains behaviorally incomplete and the final
mode-inaccurate recovery message remains. The high-severity preview divergence must be
fixed and re-audited before merge or publication.

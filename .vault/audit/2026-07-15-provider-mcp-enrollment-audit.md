---
tags:
  - '#audit'
  - '#provider-mcp-enrollment'
date: '2026-07-15'
modified: '2026-07-16'
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

### partial-provider-mode-transition | high | A missing sibling suppresses mode migration and leaves split launches

The final mode-overlay remediation detects a flip only when `mode_is_deployed`
returns true, but that predicate requires every selected provider to report a healthy,
managed RAG entry. In a dual-provider dependency-mode workspace with the persisted
declaration removed and the Codex target missing, an explicit tool-mode upgrade
therefore classified the workspace as not deployed and skipped the narrow
force-managed migration. Both preview and real execution reported Claude as one
`[SKIP]` and Codex as one `[ADD]`, and the real report set `mcp_failed` false. The
resulting Claude entry still launched through `uv run` while the newly added Codex
entry launched through `uvx --from vaultspec-rag[mcp]`. This is a false-success
non-convergence: a provider-local missing state prevents repair of the still-managed
sibling and leaves the two native hosts on different requested modes.

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
- Detect a mode transition when any selected provider has a managed RAG deployment,
  rather than requiring every provider to be healthy. Add a dual-provider regression
  with one missing target that requires preview and real execution to update the
  existing managed sibling, add the missing sibling, converge both launch shapes, and
  return success only after convergence.

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

## Final remediation verification

- `provider-error-exit-contract`: verified closed. Top-level corrupt-ownership errors
  remain present in structured reports, malformed Codex configuration is attributed to
  the provider, and both install and uninstall exit 2 rather than reporting success.
- `dry-run-source-overlay`: verified closed for fresh enrollment and `--no-mcp`.
  Claude and Codex each report one native addition or prune, respectively, while all
  workspace bytes and lock paths remain unchanged.
- `dry-run-mode-overlay`: verified closed for healthy dual-provider transitions.
  Dependency-to-tool, dev-to-tool, and tool-to-dependency previews match the real
  per-provider skip/update outcomes, preserve preview bytes and locks, and converge to
  the requested `uvx` or `uv run` launch.
- `published-core-smoke-pin`: verified closed. The live smoke accepts the installed
  public Core through `>=0.1.44`, imports the required status/sync/uninstall APIs, and
  exercises dual-provider installed enrollment plus selective uninstall preview.
- `dormant-uv-add-path`: verified closed. Repository search found no production helper,
  classifier, or stale `uv add vaultspec-rag[mcp]` guidance; the only match is the
  negative guidance assertion.
- `runtime-uv-add-guidance`: verified closed. The runtime message distinguishes tool,
  dependency, and dev recovery surfaces and explicitly keeps tool mode project-inert.
- `partial-provider-mode-transition`: open release blocker. An independent real
  workspace probe removed only the Codex target before a dependency-to-tool upgrade.
  Preview was byte-inert and matched real counters, but both reported Claude skipped
  and Codex added, `mcp_failed` remained false, and the resulting launches split between
  Claude `uv run` and Codex `uvx --from vaultspec-rag[mcp]`.

Evidence: the focused high-risk integration selection passed 8 tests; ownership,
real-host, placement, and guidance selection passed 11 tests; both installed Claude and
Codex CLIs recognized the project entry; the public-Core smoke passed every check with
Core 0.1.44 satisfying `>=0.1.44`; and `git diff --check` passed. Selective uninstall
preserved Core/user entries and ownership fingerprints. No ownership mutation or
preview-byte divergence was observed outside the open partial-provider transition.

Final verdict: **FAIL — not release-ready**. Commit `48b6127` fixes the original
healthy-provider mode-overlay divergence and the recovery guidance, but a provider-local
missing state still converts a requested mode migration into a successful split-mode
deployment. This false-success path must be remediated and independently re-audited
before merge or publication.

## S21 independent verification

### fresh-source-only-transition | high | Source-only missing status creates false mode flips and preview-real counter drift

The partial-provider remediation closes the split-launch failure when either Claude or
Codex still carries a managed RAG entry. Both missing-provider inverses now converge for
dependency-to-tool and tool-to-dependency transitions: the existing provider reports one
skip followed by one update, the missing sibling reports one add followed by one
unchanged result, preview and real counters are equal, both final launches match, and the
preview leaves every real byte and lock path unchanged.

However, `mode_is_deployed(require_all=False)` now treats `missing` as affirmative
deployment evidence. Core's status contract populates `missing` from canonical source
definitions even when no provider entry or ownership has ever existed. On a real fresh
explicit tool install, `_seed_builtins` materializes the source before
`_persist_mode_and_detect_flip` runs, so both absent targets appear `missing` and the real
operation is misclassified as a mode transition. The corresponding dry-run detects the
flip against the unmodified source tree before its temporary projection exists and does
not make the same classification. An independent real-workspace probe therefore produced
one `[ADD]` per provider in preview, but `[ADD]` plus a synthetic second-pass
`[UNCHANGED]` per provider in the matching real operation. Both operations converged and
returned success, but their exact provider plans differ, violating the accepted preview
contract.

The same defect is visible with an unowned Claude same-name collision and absent Codex
target: preview reports one Claude skip and one Codex add, while real execution reports
two duplicate Claude skips and Codex add plus unchanged. The user-owned Claude entry
remains byte-identical, so no adoption or ownership regression was observed; the blocker
is false transition detection, duplicate diagnostics, and preview-real report divergence.
The causal path is `src/vaultspec_rag/commands/_mode.py` in the non-conjunctive
`managed | missing | drifted` predicate and `src/vaultspec_rag/commands/_install.py` in
the resulting mutable two-pass projection/real migration path.

All prior HIGH findings remain closed apart from this new exact-preview regression.
Provider lifecycle errors remain visible and fail closed; fresh source addition and
unenrollment removal previews remain byte-inert and accurate without an explicit fresh
mode; healthy and partial-provider legacy mode transitions converge; and the adversarial
collision probe confirmed ownership preservation. The full real integration suite passed
50 tests, the focused mode/placement/CLI/packaging/server suite passed 449 tests, the
high-risk transition and failure selection passed 11 tests, and focused Ruff passed.

Recommendation: trigger force-managed mode migration only from affirmative deployed
ownership evidence, not an uncorroborated source-derived `missing` name. Add a fresh
explicit-mode preview-versus-real regression, plus the external-collision/absent-sibling
variant, requiring exact per-provider counters and diagnostics as well as byte and lock
inertness.

S21 verdict: **FAIL — not release-ready**. The requested partial-provider transition is
fixed, but commit `e838148` regresses exact dry-run fidelity for fresh explicit enrollment
and source-only/collision states. Release must remain held until that HIGH finding is
remediated and independently re-audited.

## S23 final verification (P03.S24)

### mcp-skip-mode-migration | high | An explicit MCP skip still mutates both provider targets during a mode transition

Commit `7f6d4f0` closes the source-only deployment-evidence defect. The
non-conjunctive predicate in `src/vaultspec_rag/commands/_mode.py:185` now recognizes
only `managed` or `drifted` native entries, both of which are grounded in Core's
ownership state; source-derived `missing`, target absence, and unowned same-name
entries no longer count as deployment evidence. Fresh explicit tool enrollment reports
exactly one addition per provider in preview and real execution. The inverse unowned
Codex collision with an absent Claude sibling likewise reports one Claude addition and
one Codex skip in both operations, leaves the Codex file byte-identical, and creates the
canonical Claude `uvx` launch. A managed drifted Claude entry with a missing Codex
sibling remains affirmative evidence: preview and real both report Claude skip/update
and Codex add/unchanged, remain byte- and lock-inert during preview, and converge both
launches to `uvx`. All four missing-provider inverses across dependency-to-tool and
tool-to-dependency retain exact preview-real counters and converge.

The full-diff audit found a separate release blocker in the same migration control
flow. `_run_core_sync` returns immediately when `"mcp"` is present in `skip` at
`src/vaultspec_rag/commands/_install.py:191`, but the real post-sync migration guard at
`src/vaultspec_rag/commands/_install.py:468` excludes only a `"core"` skip. On a real
managed dependency-to-tool transition with the legacy declaration removed,
`install_run(..., upgrade=True, mode=tool, skip={"mcp"})` therefore changed both
`.mcp.json` and `.codex/config.toml` from `uv` to `uvx` and reported one provider update
for each host. The matching dry-run reported no provider work. This violates the
operator's explicit component skip, mutates precisely the provider surfaces the earlier
branch promised to omit, and reintroduces preview-real divergence on an exposed command
path.

Recommendation: include `"mcp" not in skip` in the post-sync migration guard (or
centralize the migration under the already skip-aware MCP lifecycle branch), and add a
real dependency-to-tool regression requiring both preview and execution to report no
MCP provider work and preserve both native target files byte-for-byte when MCP is
skipped.

Verification evidence: the complete real install integration module passed 52 tests;
the focused high-risk selection passed 13 tests; mode, placement, public Core floor,
packaging, and recovery-guidance coverage passed 57 tests; focused Ruff and
`git diff --check` passed. Independent real-workspace probes covered the inverse Codex
collision, drifted-owned evidence with a missing sibling, and the failing MCP-skip
transition without mocks, fakes, patches, skips, or xfails. The earlier provider-error
exit, source add/prune preview, ownership-safe uninstall, Core `>=0.1.44` floor, and
mode-aware guidance findings remain closed.

S23/S24 verdict: **FAIL — not release-ready; one unresolved HIGH finding**. The
affirmative deployment-evidence remediation is correct, but `--skip mcp` is not honored
by the real mode-migration seam. Merge and publication must remain held until that path
is fixed and independently re-audited.

## S25/S26 final verification

### implicit-upgrade-mcp-skip | high | Legacy mode inference crosses the MCP skip boundary and rewrites dependency placement

Commit `92ba087` correctly closes the explicit-mode seam identified in S24. For both
dependency-to-tool and tool-to-dependency transitions, `skip={"mcp"}` and the combined
`skip={"core", "mcp"}` now produce no preview projection, native sync, force-managed
migration, provider counters, items, or results. Claude JSON, Codex TOML, the canonical
MCP source, Core ownership, and lock bytes remain unchanged. A separate real-workspace
probe removed the generated non-MCP `CLAUDE.md` and `AGENTS.md` files before an MCP-only
skip; ordinary Core reconciliation restored both while leaving every protected MCP
surface unchanged, so the intended non-MCP work remains active.

The guard is nevertheless too late for an implicit legacy upgrade. `install_run`
resolves an upgrade mode before it reaches `_persist_mode_and_detect_flip`; when no RAG
package declaration or explicit mode exists, `infer_rag_upgrade_mode` calls
`mode_is_deployed`, which calls Core `mcp_status` even when `"mcp"` is in the skip set.
That provider-derived result then controls `_reconcile_mcp_extra`, which also runs before
the S25 guard. In an independently created dependency-mode workspace with the legacy
declaration removed, malformed Codex TOML or malformed MCP ownership made status cease
to provide affirmative deployment evidence. Both `skip={"mcp"}` and
`skip={"core", "mcp"}` consequently resolved tool mode and removed the owned `[mcp]`
runtime extra from `pyproject.toml`; the MCP-only case also persisted a tool declaration.
Provider bytes and reports remained inert, but MCP state still determined and mutated
package placement despite the explicit skip. The supplied S25 matrix always passes an
explicit mode and therefore cannot exercise this call path.

Recommendation: make MCP skip part of upgrade-mode resolution itself. An implicit
MCP-skipped upgrade must not call provider status or derive package placement from native
deployment health; use the non-MCP declaration/project precedence instead, and cover
missing declarations with valid, malformed, drifted, and partial provider state for both
MCP-only and combined Core/MCP skips. Require provider, source, ownership, lock, and
owned-extra bytes to remain unchanged while non-MCP reconciliation continues.

### managed-dependency-dev-transition | high | The persisted mode changes while the owned MCP extra stays on the old project surface

The complete feature diff also leaves a placement transition uncovered by the accepted
three-mode contract. `_enable_mcp_extra` returns `already` whenever its recorded managed
requirement still exists, without checking whether the ownership location belongs to the
newly requested mode. Real dependency-to-dev and dev-to-dependency upgrade probes both
returned success and persisted the new mode while leaving `pyproject.toml` byte-identical.
Dependency-to-dev retained `vaultspec-rag[mcp]` in `[project].dependencies`, leaking the
optional surface into published runtime dependencies. Dev-to-dependency retained it only
in `[dependency-groups].dev`, so a built runtime consumer does not carry the dependency
that the persisted dependency mode claims. Both native launches remain `uv run`, which
hides the placement mismatch from provider convergence tests.

Recommendation: when owned placement and requested project mode differ, restore the
recorded original at the old surface and reconcile only an unambiguous declaration at the
new surface, or fail closed with a structured conflict without persisting a contradictory
mode. Add real preview/apply/reversal cases for both dependency-to-dev and
dev-to-dependency, including exact ownership and byte assertions.

Verification evidence: the complete real install integration module passed 56 tests,
including both real host CLIs, provider-error exits, source add/prune previews, all four
partial-provider inverses, source-only and collision cases, selective ownership-safe
uninstall, and the four explicit S25 skip combinations. The focused placement, mode,
packaging, server, and guidance slice passed 184 tests. Ruff, Ty, BasedPyright, all
complexity gates, the lock check, changed-file formatting, Vaultspec validation, and
`git diff --check` passed. The Vaultspec run retained only known corpus warnings plus the
newly scaffolded S26 exec annotations and stale feature index; no structural error was
reported.

All earlier HIGH findings remain closed on their covered paths: provider errors fail
closed with complete attribution; source addition and pruning previews are exact and
byte-inert; requested-mode projections and partial-provider migrations agree with real
execution; source-only, collision, and drifted ownership evidence behave correctly;
selective uninstall preserves sibling and user ownership; Core `>=0.1.44` and the
canonical tool launch remain enforced; and recovery guidance is mode-aware.

S25/S26 verdict: **FAIL — not release-ready; two unresolved HIGH findings and no
CRITICAL findings**. The explicit-mode native skip leak is fixed, but implicit upgrade
inference still crosses the same boundary and can rewrite owned dependency placement.
The full feature also permits dependency/dev declaration-placement contradictions.
Merge and publication must remain held until both are remediated and independently
re-audited.

## S27/S28 final verification

### mcp-skip-source-and-extra-boundary | high | MCP skip still permits source and owned-extra mutations

Commit `c1f81b8` closes the provider-derived implicit-mode path identified in S26.
With no explicit mode or RAG declaration, both `skip={"mcp"}` and
`skip={"core", "mcp"}` now resolve from durable `pyproject.toml` placement without
calling MCP status. The supplied malformed-Codex and malformed-ownership cases retain
dependency mode, the provider targets and Core ownership sidecar remain byte-identical,
no MCP lifecycle result or provider report is emitted, and an MCP-only skip still runs
ordinary non-MCP Core reconciliation.

The skip boundary remains incomplete because `_reconcile_mcp_extra` and
`_seed_builtins` execute before the skip-aware persistence and provider lifecycle
guards. In independent real workspaces, an implicit upgrade combining either skip set
with disabled MCP intent removed the canonical RAG MCP source and reversed the owned
runtime extra in `pyproject.toml`; `mcp_extra_action` reported `removed` while
`sync_providers` remained empty. With MCP intent enabled, changing the canonical source
to operator bytes before the same skipped upgrade caused the upgrade seed to overwrite
those bytes under both skip sets, again with no MCP report. Provider configuration and
the provider ownership sidecar stayed unchanged, but the source and dependency/provenance
surfaces explicitly named by the component skip did not.

Recommendation: apply the MCP skip before source-intent seeding and optional-extra
reconciliation as well as before status, projection, native sync, and migration. A
skipped run must preserve source bytes and owned-extra state regardless of simultaneous
`--mcp`/`--no-mcp` intent or upgrade reseeding, emit no MCP report, and continue only
the intended non-MCP work.

### placement-conflict-mode-commit | high | A placement conflict still commits a contradictory package mode

The happy owned dependency-to-dev and dev-to-dependency paths are symmetric: preview is
byte-inert, apply moves the exact owned edit to the requested surface, reverse restores
the prior managed bytes, uninstall restores the original declaration, and ownership
tracks the active edit. The unowned-target-extra case also restores the old owned edit,
preserves the target extra, and clears provenance instead of adopting it.

Conflict handling is only local to the TOML reconciler, however. An independent real
dependency-mode workspace had only the owned runtime requirement externally drifted,
leaving its recorded ownership unchanged, and then requested a dev-mode upgrade.
Preview and apply both returned `mcp_extra_action="conflict"` and correctly left
`pyproject.toml` byte-identical, but install continued through
`_persist_mode_and_detect_flip`: the real run persisted `dev`, retained the drifted
runtime `[mcp]` requirement with no dev declaration, reported two unchanged MCP passes
per provider, left `mcp_sync_failed` false, and returned success. The local refusal is
therefore non-destructive but the overall operation is not atomic, and persisted mode
no longer agrees with dependency placement.

Recommendation: make an MCP-extra conflict a fail-closed transition boundary. Do not
persist the requested package mode or reconcile native launch state unless placement
can commit, or atomically roll back every earlier placement edit if a later step fails.
Add real drift and ambiguous-target cases requiring preview/apply parity, unchanged
mode/provider/source/ownership/dependency/lock bytes, an explicit failed result, and a
non-zero CLI exit.

Verification evidence: the complete real install integration module passed 62 tests,
including both host CLIs, provider failures, source add/prune previews, fresh/collision
parity, four partial-provider inverses, explicit skip boundaries, implicit skipped
corruption cases, selective uninstall, and the two happy placement directions. The
focused implicit-skip and placement selection passed 6 tests, the complete placement
module passed 18 tests, focused Ruff passed, and `git diff --check` passed. A broader
unit run was stopped at the release owner's request after both adversarial blockers were
accepted; the owner separately reported the 1,416-test unit, full static, and wheel
smoke gates green. No mock, fake, patch, monkeypatch, skip, or xfail was used in the
independent probes.

All earlier HIGH findings remain closed on their covered paths: provider errors retain
attribution and fail closed; source add/prune and requested-mode previews are exact and
byte-inert; healthy, partial, source-only, collision, and drifted-ownership provider
transitions converge; selective uninstall preserves sibling and user ownership; the
public Core `>=0.1.44` floor and canonical launch remain enforced; and recovery guidance
is mode-aware. The two findings above are new uncovered boundaries rather than
regressions in those verified paths.

S27/S28 verdict: **FAIL — not release-ready; two unresolved HIGH findings and no
CRITICAL findings**. Status-free implicit mode inference and happy dependency/dev moves
are correct, but MCP skip does not protect all MCP-owned surfaces and placement conflicts
can still commit a contradictory mode. Merge and publication must remain held pending
remediation and another independent audit.

## S30 final verification

### malformed-pyproject-report-boundary | high | MCP preflight suppresses the established torch-config failure contract

Commit `0e405ee` closes both S28 transaction findings on the adversarial paths. An MCP
skip now filters the MCP builtin before classification and preserves the canonical or
operator-drifted source, dependency-extra edit and provenance, both provider files, Core
ownership, provider reports, MCP errors, and lock bytes for enabled and disabled intent
under both the MCP-only and combined Core/MCP skip sets. Ordinary non-MCP Core
reconciliation continues for the MCP-only skip. Owned-drift and ambiguous-target
placement conflicts are preview/apply byte-inert, retain the previous dependency mode,
produce structured MCP failure, and make the CLI exit 2. A genuine atomic-write blocker
after the dependency placement edit restores the exact prior pyproject, placement
provenance, workspace declaration, and dependency mode before returning failure.

The new placement preflight nevertheless introduces a separate release-blocking report
regression. With malformed `pyproject.toml`, `_prepare_mcp_transition` catches the parse
failure and `install_run` immediately returns the MCP-failed report. The established
torch-config inspection path is never reached, so `torch_config_action` remains
`skipped` rather than `error` and the required `torch-config inspect failed` diagnostic
is absent. The existing real test
`TestErrorBranches.test_install_corrupt_pyproject_records_error` fails on this exact
contract. The command still fails closed through its MCP error, but it no longer reports
all requested component failures through the long-standing structured surface.

The other reproducible unit failure is not a production finding: the old dev-mode case
in `test_explicit_mode_persists_and_renders_rag_entry` supplies only a runtime project
declaration. The new placement preflight correctly refuses to persist a contradictory
dev mode, so that fixture must use a dev-surface declaration or explicitly assert the
conflict; weakening the transaction boundary would be incorrect.

Verification evidence: the focused S29 transaction matrix passed 11 tests, the complete
real install integration module passed 73 tests, and the complete placement module
passed 18 tests. The mode module passed 35 tests with the single stale-fixture failure
above. The first over-broad non-integration invocation selected 1,815 of 2,148 tests and
timed out after 904 seconds without a summary while still executing real Qdrant service
tests; deterministic segmentation then reported 803 passes and three failures: the
confirmed report regression, the stale dev fixture, and external machine-service
contamination. Ruff and Ty passed, BasedPyright reported zero errors, warnings, and
notes, and the cognitive, cyclomatic, and nesting-depth gates passed. The lock check
resolved 141 packages, Vaultspec structural checks were clean with 24 pre-existing
corpus warnings, and `git diff --check` passed.

An isolated `vaultspec-rag 0.3.0` wheel also passed every smoke assertion: both console
entry points and the canonical builtin were present, public `vaultspec-core 0.1.44`
satisfied the declared `>=0.1.44` floor, both entry points started, and the installed CLI
enrolled identical native Claude and Codex project targets. Earlier healthy
dependency-to-dev and dev-to-dependency moves, ownership-safe uninstall, provider-error
attribution, preview fidelity, source collision handling, selective removal, host
acceptance, and public-Core packaging findings remain closed.

S30 verdict: **FAIL — not release-ready; one unresolved HIGH finding and no CRITICAL
findings**. The complete MCP skip and placement/mode transaction remediations are correct,
but malformed consumer metadata now truncates the structured install report before the
established torch-config failure is recorded. Merge and publication must remain held
until that contract is restored and a new independent audit passes the complete suite.

## S32 final verification

### transaction-lock-rollback | high | A fresh mode-write failure leaves newly created lock state

Commit `861f6b2` retains the placement-and-mode rollback added in S29, but the
transaction snapshots only `pyproject.toml` and `.vaultspec/workspace.json`.
Vaultspec Core's mode persistence also creates `.vaultspec/workspace.json.lock`. A real fresh
dependency workspace with a directory blocking Core's atomic mode write returned
structured MCP failure and restored the exact project bytes. It removed the absent-before
workspace declaration, but left the newly created lock file behind.

The current integration regression starts from an already installed workspace, so its
before-state already includes the lock and cannot detect this first-install residue.
Recommendation: include lock existence and bytes in the transaction boundary. Rollback
must remove a lock created by the failed operation while preserving any exact pre-existing
lock state.

### unreadable-project-report-boundary | high | Non-ParseError inspection failures still suppress torch-config reporting

The S31 change restores the dual MCP and torch-config error contract only for
`tomlkit.exceptions.ParseError`. The generic exception branch in
`_reconcile_mcp_extra` still returns before the torch flow and does not set
`TorchConfigAction.ERROR`. A real invalid-UTF-8 `pyproject.toml` reproduced this path.
The command preserved the project bytes, created no lock, and reported MCP failure.
It left `torch_config_action` as `skipped` and omitted the established
`torch-config inspect failed` diagnostic.

Recommendation: classify every project-inspection failure through the same requested
component reporting contract, not only TOML syntax failures. Retain the current early
mutation boundary, MCP failure, CLI exit 2, exact project bytes, and absent lock state.

### seed-failure-transaction-order | high | Builtin failure commits placement and mode before enrollment exists

The MCP placement and workspace mode commit now precedes `_seed_builtins`. The seeder's
rollback owns only files written during its own call. A real dependency workspace with a
non-empty directory blocking the rule destination raised `PermissionError` after the MCP
source was written. The local seed rollback removed that source, but install retained the
`vaultspec-rag[mcp]` dependency edit, its placement provenance, the new dependency-mode
declaration, and the workspace lock. Provider configuration remained absent, leaving a
half-installed state.

This contradicts the existing seed-failure contract, whose test currently checks only
the partially written MCP source. Recommendation: extend the install transaction across
placement, mode persistence, and builtin seeding. Any seed failure must restore exact
dependency, provenance, declaration, source, and lock state before propagating or
reporting the failure.

Verification evidence: the complete install, mode, torch-config, placement, Qdrant CLI,
and install-integration selection passed 194 tests against the production-equivalent
S31 code. After the Qdrant isolation commit, the complete Qdrant runtime and CLI selection
passed 44 tests. The Qdrant delta correctly isolates status, storage, lock identity, and
port state and produced no review finding. Ruff, Ty, BasedPyright, all complexity gates,
the lock check, changed-file formatting, Vaultspec validation, and `git diff --check`
passed before the test-only Qdrant delta. The owner also reported that delta's hooks and
static checks green. These three blockers were reproduced independently with real
temporary files and genuine filesystem failures, without mocks, patches, skips, or
xfails. The deterministic 1,815-test aggregate and wheel smoke were not awaited because
genuine release-blocking defects already satisfied the audit's stop condition.

S32 verdict: **FAIL — not release-ready; three unresolved HIGH findings and no CRITICAL
findings**. The malformed-TOML and Qdrant cases covered by S31 are fixed. Transaction
rollback omits fresh lock state. Unreadable project metadata still loses requested
torch-config failure attribution. A later builtin write failure leaves placement and
mode committed. Hold merge and publication until remediation and another independent
audit are complete.

## S34 final verification

### forced-builtin-rollback-data-loss | high | A later seed failure deletes a pre-existing repaired rule

Commit `93341ab` closes all three S32 findings on their targeted paths. Fresh and
pre-existing project and workspace locks participate in the intent snapshot; source
addition and repair failures restore the exact prior MCP source, placement provenance,
package declaration, project bytes, and locks; invalid UTF-8 and a genuine filesystem
read blocker produce both MCP and torch-config errors; and the CLI fails with exit 2.
The complete high-risk install, placement, mode, torch-config, Qdrant, and native-host
selection passed 235 tests.

The broadened transaction still exposes a separate data-loss path during forced builtin
repair. `_mcp_intent_paths` snapshots only project metadata, persistent locks, and MCP
source destinations. `seed_builtins` records every file it writes, including an existing
rule overwritten under `force` or `upgrade`. If a later skill destination presents a
genuine filesystem blocker, `_rollback_seeded` unlinks the repaired rule, and the outer
transaction cannot restore it because the rule was never snapshotted.

An independent real temporary-workspace probe wrote distinct pre-existing bytes to the
RAG rule, placed a non-empty directory at the later skill destination, and invoked a
forced MCP install. The operation correctly returned structured MCP failure and restored
the MCP intent surfaces, but the pre-existing rule no longer existed. This is
release-blocking user-data loss. The transaction must snapshot every builtin destination
that forced seeding may overwrite, restore exact bytes for pre-existing files, remove
only transaction-created files, and prove both rule and skill failure orderings with
real filesystem blockers.

Verification evidence: the complete high-risk selection passed 235 tests, including
both installed host CLIs and isolated Qdrant runtime and CLI behavior. The first exact
non-integration segment passed 811 tests with 4 deselected and no failures. Ruff lint
passed. The remaining segmented aggregate, static, Vaultspec, diff, and wheel gates were
stopped when the release owner accepted the genuine HIGH finding and invalidated the
target; their absence is not waived and a fresh audit must rerun them after remediation.
No mock, fake, stub, patch, monkeypatch, skip, or xfail was used in the independent
reproduction.

S34 verdict: **FAIL — not release-ready; one unresolved HIGH finding and no CRITICAL
findings**. S33 restores the previously missing intent and lock rollback boundaries, but
a forced repair followed by a later builtin write failure deletes exact pre-existing
rule bytes. Merge and publication remain held pending remediation and a new independent
review with the complete release gates.

## S36 final verification

### symlink-rollback-topology-loss | high | Failed forced seeding does not restore operator-owned builtin symlinks

Commit `92ce320` closes the S34 data-loss path for ordinary files. Every bundled MCP,
rule, and skill destination now participates in the transaction snapshot, and the real
ordered force and upgrade regressions restore exact pre-existing bytes, remove only
newly created files, and preserve blocker directories and unrelated files.

The snapshot model still records each destination only as file bytes or absence. It
does not record filesystem object type or symlink target. An independent real-workspace
probe placed a pre-existing RAG rule symlink to an operator-owned file inside the
workspace, then used a genuine atomic-temp directory blocker at the later skill
destination during a forced MCP install. The install failed closed with structured MCP
failure and no provider sync. Rollback preserved the rule content bytes and the link
target, but replaced the rule symlink itself with a regular file. A failed transaction
therefore still destroys operator-owned filesystem topology at a builtin destination.

Recommendation: snapshot builtin destinations with `lstat`-level object identity and
the exact symlink target, not only dereferenced bytes. Rollback must recreate a
pre-existing symlink exactly, remove only transaction-created objects, and retain the
existing exact-byte behavior for regular files and locks. Add real forced-install and
upgrade regressions for valid and broken symlinks followed by a later ordered write
failure.

Verification evidence: the complete high-risk install integration, MCP placement,
mode, torch-config, Qdrant runtime and CLI, and packaging selection passed 244 tests,
including both real host CLIs and all previous malformed-input, placement, lock, and
regular-file rollback cases. Deterministic segmentation of the exact
`pytest -m "not integration"` inventory passed 1,632 of 1,820 selected tests before the
target was invalidated and the service batch was terminated. The remaining 188 tests,
static, Vaultspec, diff, build, and wheel gates were stopped after the genuine HIGH was
accepted; none is waived.

S36 verdict: **FAIL — not release-ready; one unresolved HIGH finding and no CRITICAL
findings**. Regular builtin files now roll back correctly, but a failed forced seed can
replace an operator-owned symlink with a regular file. Merge and publication remain
held pending topology-aware remediation, a fresh independent audit, and completion of
every unwaived release gate.

## S38 final verification

### rollback-scratch-symlink-data-loss | high | Predictable rollback scratch path follows and removes an operator symlink

Commit `d8de256` closes the S36 finding at the primary builtin destination. Node
snapshots now distinguish absent paths, regular files, directories, symlinks, and
Windows junctions; valid and broken relative symlinks recover their exact link text,
and direct real junction restoration preserves the referenced target contents.

Regular-file restoration introduces a separate data-loss path. `_restore_regular_file`
constructs the deterministic sibling pathname
`<destination>.<pid>.rollback.tmp`, writes the saved payload through it, replaces the
destination, and unconditionally unlinks the scratch path. That scratch node is neither
captured by the transaction snapshot nor created with an exclusive no-follow boundary.
If it already exists as an operator-owned symlink, `write_bytes` follows the link and
overwrites the referenced file before cleanup removes the link itself.

An independent real temporary-workspace reproduction saved a regular builtin snapshot,
changed the builtin, placed a relative symlink at the exact rollback scratch pathname,
and pointed that link at an unrelated operator file containing distinct bytes.
`_restore_file_snapshot` restored the builtin, but also replaced the operator file's
bytes with the builtin snapshot and deleted the operator's symlink. No mock, fake,
patch, monkeypatch, skip, or xfail was used. This is release-blocking user-data loss and
violates the rollback contract that link targets and unrelated nodes are never followed,
modified, or removed.

Recommendation: create rollback scratch files atomically and exclusively with a
non-following primitive in the destination directory, use an unpredictable name, and
remove only a scratch node whose creation and identity belong to the active
transaction. Add a real forced-install and upgrade regression with a pre-existing
symlink collision that requires both the link and its referenced bytes to remain exact.

The first exact `pytest -m "not integration"` aggregate batch was terminated before it
produced a summary, so no test count is credited to S38. All remaining high-risk,
static, Vaultspec, diff, build, wheel, and real-host gates were stopped after the target
was invalidated; none is waived.

S38 verdict: **FAIL — not release-ready; one unresolved HIGH finding and no CRITICAL
findings**. Primary builtin topology restoration is correct on the covered paths, but
its predictable scratch file can corrupt an unrelated symlink target and delete the
operator's link. Merge and publication remain held pending scratch-node-safe
remediation, a fresh independent audit, and completion of every release gate.

## S40 final verification

### mcp-reindex-initiator-attribution | high | Real MCP reindex requests are recorded as CLI work

Commit `07e4084` closes the S38 rollback-scratch data-loss path on its focused
surface. Rollback now creates a random same-directory file exclusively with
`mkstemp`, writes only through the returned descriptor, flushes and fsyncs the
payload, restores the captured mode, publishes with `os.replace`, and cleans up
only the exact node created by the active restore. The high-risk install surface
passed 208 tests before this independent review, including regular, live-symlink,
and broken-symlink collisions for regular-file and symlink snapshot restoration.

The fresh exact release inventory exposed a separate production attribution defect.
The real MCP `reindex_vault` tool delegates through `_try_http_reindex`, but that
shared transport unconditionally sends `initiator_kind="cli"`. A real isolated
service test invokes the MCP tool, waits for the resulting job, and observes
`initiator.kind == "cli"` instead of `"mcp"`. The selector fails identically when
run alone, so this is not order leakage. It makes operator job history and service
diagnostics misidentify MCP-originated work and is release-blocking.

Recommendation: carry initiator identity at the actual caller boundary. MCP tools
must submit `mcp`, CLI callers must submit `cli`, and the service route must retain
that value. Prove the distinction through the real transport and service API without
mocks, patches, or global service state.

### service-release-gate-drift | medium | The exact service inventory is red and its daemon baseline is not deterministic

The same clean `test_service_jobs.py` run completed with 56 passes and five failures.
Four rendering assertions expect text or line placement that no longer matches the
current CLI behavior: `No matching jobs.` versus `No jobs matched these filters.`,
the filter line versus the scripting advisory at header position eight, and
`There are no active or waiting jobs.` versus `There are no active jobs.`. Each
selector fails identically in isolation.

A detached disposable `origin/main` worktree at `874f0fe` reproduced all four
rendering mismatches with the same actual output. The feature branch does not modify
the service-jobs tests, the service-jobs renderer, the MCP tool, the service transport,
or the integration fixture/helper. The base daemon selector did not produce a terminal
result within 300 seconds, while the feature target terminated and exposed the
attribution mismatch. This proves the rendering drift is pre-existing and also shows
that the real-service test boundary is not yet deterministic enough for an exact
release gate. Being pre-existing does not waive a red release inventory.

Recommendation: establish the authoritative current rendering contract from code,
help, user documentation, and history. Change production only where that contract is
wrong; otherwise update the stale behavior assertions. Isolate and clean up every
daemon-owned status, storage, port, lock, and child process so the real MCP selector
terminates deterministically on both the feature target and the baseline.

Fresh verification evidence: collection reported exactly 1,820 selected tests out of
2,174, with 354 deselected rather than the historical 337 because 17 additional
integration-marked cases are present. The three sorted top-level batches passed
811, 309, and 490 tests. The isolated Qdrant/singleton group passed 22 tests. The first
deterministic service batch passed one test, yielding 1,633 credited passes. The
61-test service-jobs file then reported 56 passes and the five failures above; because
the file is red, none of its tests is credited to the exact aggregate. The remaining
service files, the 54-test remainder, static checks, Vaultspec checks, build, wheel,
and real-host acceptance were stopped after the release target was invalidated; none
is waived.

S40 verdict: **FAIL — not release-ready; one unresolved HIGH and one unresolved
MEDIUM finding, with no CRITICAL findings**. Rollback scratch restoration is corrected,
but MCP work is misattributed, the service release inventory is deterministically red,
and baseline daemon execution is not deterministic. Merge and publication remain held
pending S41 remediation and a fresh S42 review that restarts all 1,820 selected tests
from zero and completes every unwaived gate.

## S42 final verification

### fresh-install-provider-selection | high | A self-sufficient MCP install silently enrolls no provider

The S42 review restarted from commit `1fe7b99` and collected the current exact
non-integration inventory before relying on any earlier gate. A real CLI install into a
truly fresh temporary workspace, with MCP intent enabled and provisioning and torch
configuration disabled, exited zero with `mcp_failed=false` and an empty
`sync_providers` map. It created an empty Core provider manifest but neither
`.mcp.json` nor `.codex/config.toml`.

The production installer describes RAG enrollment as self-sufficient, but
`_run_core_sync` asks Core to reconcile `provider="all"` without supplying the
fresh-install `enrolled` selection. Core therefore resolves the just-created empty
manifest to zero targets. The feature's install helper, native-host acceptance, and
installed-wheel smoke all pre-seed `{"claude", "codex"}` with `write_manifest`, so
they cannot detect the public CLI's empty-workspace behavior. A default install can
claim success while exposing the MCP to neither host, which directly violates the
release requirement that installation establish project-scoped Claude and Codex
enrollment.

Recommendation: make provider selection an explicit install input or a documented,
fail-closed prerequisite, and pass Core's typed fresh-enrollment selection to every
real and preview MCP lifecycle call. Add a real installed-CLI case with no prewritten
manifest that either enrolls the requested hosts or exits non-zero with actionable
provider-selection guidance; do not manufacture the condition under test in the smoke
fixture.

### uninstall-mcp-skip-boundary | high | MCP skip removes local intent while leaving both host entries active

`uninstall_run` reverses the owned optional dependency and removes every bundled source
before `_run_core_cleanup` checks the MCP skip. A real dual-provider dependency-mode
workspace followed by `uninstall --force --skip mcp --json` exited zero with
`mcp_failed=false` and no provider outcomes. Exact hashes proved that Claude JSON and
Codex TOML remained byte-identical, while the canonical MCP source disappeared and
`pyproject.toml` changed from the managed `[mcp]` requirement back to the base
requirement, also removing placement provenance.

The result is a configured server whose canonical source and required optional runtime
surface were dismantled despite the explicit component skip. This contradicts the
already accepted complete-intent skip boundary on install and the plan's symmetric
uninstall contract.

Recommendation: apply the MCP skip before dependency reversal and MCP source removal.
Preserve source, dependency and provenance, provider targets, ownership, and locks
byte-for-byte while allowing only non-MCP uninstall work to continue.

### dry-run-context-leak | high | Preview leaves Core bound to a deleted temporary workspace

`_mcp_preview_projection` creates a temporary workspace and `_run_core_sync` calls
Core's `mcp_sync` with that projection as `target_dir`. Core initializes its workspace
ContextVar to the supplied target, but RAG never restores the prior context when the
projection closes. A real probe first initialized Core against a durable temporary
workspace, then ran RAG's dual-provider install preview. After return,
`get_context().target_dir` pointed at the deleted
`vaultspec-rag-mcp-preview-*` directory rather than the original workspace.

This is observable state mutation from a command promised to be non-mutating, and it
can make a subsequent implicit Core status or sync silently inspect a nonexistent
workspace. The provider counters for the preview itself can be accurate while the
calling process is left corrupted.

Recommendation: execute projection-bound Core calls inside a context boundary that
restores the exact previous context, including the no-prior-context case. Add real
sequential preview-then-status and preview-then-sync acceptance proving that the caller's
workspace binding survives success and failure.

### preview-symlink-topology | high | Dry-run follows workspace links and can fail where apply succeeds

The preview copies the complete `.vaultspec` tree with default `shutil.copytree`
semantics. Those semantics dereference links instead of preserving node topology. In a
real enrolled workspace, an unrelated broken symlink under `.vaultspec` made the
matching `install --upgrade --dry-run` exit one with a `shutil.Error`. The corresponding
real upgrade exited zero, reported no MCP failure, and preserved the broken symlink and
its exact link text.

Preview and apply therefore disagree solely because the planner traverses unrelated
filesystem topology that the actual install does not need to mutate. Live directory
links and Windows junctions can likewise cause an unrelated target tree to be read into
the projection, which is inconsistent with the transaction's established no-follow
boundary.

Recommendation: build a minimal MCP projection from the required source, declaration,
ownership, and native target nodes using lstat-aware copy semantics. Cover unrelated
live and broken symlinks plus Windows junctions with exact preview/apply parity and
no-follow assertions.

### uninstall-extra-failure-contract | high | Failed dependency reversal is reported as a successful uninstall

The uninstall path converts exceptions and conflicts from `reconcile_mcp_extra` into
warnings only. It does not populate `mcp_errors`, and it continues through source and
provider removal. A real owned runtime requirement was externally drifted from the
recorded managed value before `uninstall --force --json`. The CLI exited zero with
`mcp_failed=false` and no MCP errors, removed both native provider entries and the
canonical source, but left the drifted `[mcp]` requirement and its
`tool.vaultspec-rag.mcp-extra` ownership table in `pyproject.toml`.

The lifecycle therefore reports success while durable RAG-owned state remains and the
workspace has been split across opposite sides of the uninstall boundary. A warning is
not sufficient for a requested reversal that did not complete.

Recommendation: make optional-dependency reversal a fail-closed MCP transaction. Record
inspection exceptions and ownership conflicts as MCP failures, exit non-zero, and do
not remove canonical source or provider enrollment unless the owned dependency
transition can commit atomically.

### S41 remediation review and release-gate ledger

The S41 attribution change carries explicit `cli` and `mcp` literals at their real
caller boundaries, the route retains the value, and the isolated fixture relocates the
status directory, storage root, Qdrant port, service port, and machine lock while
verifying service and recorded Qdrant process exit. The thirty-second client and Qdrant
deadlines introduce no retry or local-fallback path. The current rendering assertions
test semantic content and relative order rather than the stale fixed positions. No new
S41-specific production or test-shortcut finding was identified by source review.

Collection reported exactly 1,823 selected tests out of 2,177, with 354 deselected;
S41 added three selected tests relative to S40's 1,820. The first deterministic
top-level segment passed all 553 selected tests with four deselected in 152.12 seconds.
Once the five independent HIGH findings were reproduced, the remaining 1,270 selected
tests, complete install integration, service repetitions, real-host acceptance, Ruff,
changed-path format, Ty, BasedPyright, complexity, lock, Vaultspec, provider-artifact,
diff, build, wheel, and public-Core smoke gates were stopped. None receives credit or a
waiver; a remediation audit must restart the complete current inventory and every
release gate from zero.

S42 verdict: **FAIL — not release-ready; five unresolved HIGH findings and no CRITICAL
findings**. S41 corrects caller attribution and substantially hardens the service gate,
and the prior rollback-scratch fix remains sound on the reviewed paths. The fresh
provider-selection false success, two uninstall boundary failures, dry-run ContextVar
mutation, and topology-divergent preview each independently block merge and publication.

## S44 final verification

### foreign-lock-holder-lifecycle | medium | The exact singleton gate races a surviving interpreter lock holder

The S44 review started from clean commit `98a5727` and re-read the accepted research,
ADR, plan, complete audit history, S42 and S43 records, and canonical audit and execution
templates before inspecting the complete feature surface. Collection reported 1,824
selected tests out of 2,191, with 367 deselected. This is one selected test and fourteen
total tests above the historical S42 inventory.

The fifteen focused S43 lifecycle regressions passed against real temporary workspaces.
They independently reproduced closure of the five S42 HIGH findings: a fresh install
selected Claude and Codex without a preseeded manifest; corrupt provider intent failed
before workspace mutation; uninstall with MCP skipped preserved the complete MCP domain;
preview restored both prior and unset Core contexts and did not follow unrelated live,
broken, or junction topology; and optional-dependency reversal failures stopped teardown
with structured non-zero outcomes. The three disjoint top-level inventory segments then
passed 545, 546, and 523 tests, crediting all 1,614 top-level selections.

The next exact 22-test singleton and Qdrant segment was red twice, each time after all
22 test calls passed. The first run failed teardown in
`test_live_foreign_machine_lock_holder_fast_fails`; the second failed teardown in
`test_second_acquire_refused_while_foreign_holder_alive`. Both fixtures raised Windows
`PermissionError` while unlinking their isolated `service.lock`, which remained held by
the real subprocess. The complete `test_adversarial_singleton.py` file reproduced the
same teardown error independently, while the single selector happened to pass once.

The causal diagnostic used the real `_spawn_lock_holder` helper with no fake, mock,
patch, monkeypatch, skip, or xfail. It reported launcher PID 84200 and holder PID 22904,
then proved the lock became unlinkable only 0.05 seconds after the launcher was killed
and awaited. The helper's own contract acknowledges that the launcher may spawn the
interpreter as a grandchild, but cleanup terminates only the launcher PID and fixture
teardown immediately unlinks the lock. The exact release gate is therefore nondeterministic
on the supported Windows/uv process topology and currently cannot produce a terminal
green inventory.

Recommendation: terminate and await the actual reported holder PID, or supervise the
complete spawned process tree, then verify the OS lock is released within a bounded
deadline before fixture teardown removes the file. Apply the same real holder lifecycle
helper to both singleton modules and require repeated clean file and combined-group runs.

The red singleton segment receives no inventory credit. The remaining 210 selected
integration tests, the complete 107-test install lifecycle module, service repetitions,
real Claude and Codex acceptance, Ruff, changed-path format, Ty, BasedPyright,
complexity, lock, Vaultspec, provider-artifact, diff, build, wheel, public-Core smoke,
and fresh installed-package gates were stopped after the blocker and receive neither
credit nor waiver. No production or test file was modified during S44.

S44 verdict: **FAIL — not release-ready; one unresolved MEDIUM release-gate finding and
no newly identified HIGH or CRITICAL finding**. S43's five targeted lifecycle repairs
are green on their focused real-workspace surface, but every required gate must terminate
green. Merge and publication remain blocked until the real holder lifecycle is repaired
and a fresh independent review restarts all 1,824 selected tests and every uncredited
release gate from zero.

## S46 final verification

### required-node-relative-symlink-preview | high | The isolated preview breaks relative links and reports a different native lifecycle

The S46 review started from clean holder-safe commit `59e08842` and re-read the accepted
research, ADR, plan, complete audit history through S44, S42 through S45 execution
records, and canonical audit and execution templates. Source review then classified the
previously unresolved required-node relative-symlink candidate before beginning the
expensive release campaign.

`_mcp_preview_projection` copies required provider intent, package declaration,
ownership, and native target nodes through `_copy_preview_node`. That helper captures a
symlink's exact link text and recreates it unchanged under the temporary projection.
For a relative link, the same text is resolved from the projection directory rather
than the real workspace directory, while the sibling target file is not projected. The
preview therefore sees a broken or semantically different required node even though the
matching apply reads the live target correctly.

An independent real temporary-workspace matrix first completed a fresh dual-provider
dependency-mode install, then replaced each required file with a relative symlink to a
distinct sibling carrying its exact bytes. No mock, fake, stub, patch, monkeypatch,
skip, or xfail was used. With linked `.mcp.json`, preview reported Claude `[ADD]` while
apply reported `[UNCHANGED]`. With linked `.codex/config.toml`, preview reported Codex
`[ADD]` while apply reported `[UNCHANGED]`. With linked
`.vaultspec/mcp-ownership.json`, preview classified Claude as externally managed and
`[SKIP]`, while apply retained managed ownership and reported `[UNCHANGED]`. With linked
`.vaultspec/providers.json`, preview returned an empty provider map and
`mcp_failed=false`, while apply reconciled both Claude and Codex as `[UNCHANGED]`.
Every preview left the real symlink and target bytes exact, so the defect is the plan it
reports rather than preview mutation.

The same matrix also showed that a no-delta real upgrade replaced relative-symlink
`.vaultspec/providers.json` and `.vaultspec/workspace.json` nodes with regular files
while leaving their sibling targets intact. That topology mutation is not represented
by the preview report and contradicts the feature's byte-stable, idempotent reinstall
intent. Required-node topology therefore needs an explicit lifecycle contract rather
than inheriting the unrelated-node no-follow implementation.

Recommendation: project the effective contents of each exact required node into an
isolated projection-local regular node, or use a Core planning input that does not
relocate filesystem links. Do not re-create raw relative link text under a different
root and do not point a projected mutating pass back at the real link target. Add real
preview/apply/idempotency regressions for relative links at provider intent, workspace
mode, ownership, Claude JSON, and Codex TOML, requiring exact provider outcomes and
unchanged operator topology where no logical update is needed.

The exact 1,824-test inventory, complete 107-plus native lifecycle acceptance, service
repetitions, real-host recognition, static checks, Vaultspec checks, build, wheel,
public-Core smoke, and truly fresh installed-package gates were not started after this
HIGH invalidated the release target. They receive no credit and no waiver. S45's
focused holder evidence remains useful but cannot establish release readiness for the
broken preview contract.

S46 verdict: **FAIL — not release-ready; one unresolved HIGH finding and no CRITICAL
findings**. Merge, PR approval, and publication remain blocked pending required-node
projection remediation and a new independent audit that restarts every required gate
from zero.

## S48 final verification

### core-atomic-writer-node-integrity | critical | Core can consume a pre-existing sibling node as its scratch file

The S48 review started from clean topology-remediation commit `5a96aad` and rebuilt the
exact release inventory: 2,261 collected tests, 437 excluded integration cases, and
1,824 selected cases. The selected ledger remained non-overlapping: 1,614 top-level
cases in 545, 546, and 523-test segments; 22 singleton and Qdrant cases; 54 remaining
non-service integration cases; 134 selected service-ledger cases; and 177 native
install cases.

Before the first segment produced a terminal result, source review found that the
published Core `atomic_write` constructs a sibling path from the destination suffix,
the current process identifier, and `.tmp`, then writes that path before replacement.
That name is knowable before the call and is not created exclusively. A pre-existing
regular file, link, or other filesystem node at the same sibling path is therefore
treated as Core's private scratch node. For a link, the byte write follows the link;
the subsequent replacement can also install the link itself at the destination. The
same helper is used by MCP JSON and ownership writes, and parallel PID-derived writers
exist for generated ignore and attributes files.

Recommendation: create an unpredictable same-directory temporary regular file
exclusively, write through the returned descriptor, flush and close it, atomically
replace the destination, and clean up only the node created by that invocation. Audit
the parallel generated-file writers and add real regressions proving that pre-existing
sibling regular files, links, broken links, and directories retain exact bytes and
topology.

### required-target-lifecycle-output-overlap | high | RAG validates linked targets against only a subset of lifecycle writes

`inspect_required_mcp_topology` rejects a required link target when it overlaps another
required MCP node or another captured required target. It does not compare that target
with the full install and uninstall write inventory. The install path separately
enumerates every bundled output through `list_builtins`, then seeds and synchronizes
those files while the required-node topology transaction is materialized. A required
link can consequently target a non-required bundled or provider output: both lifecycle
subsystems then claim the same effective file, and the topology finish phase can
replace the bytes written by the other subsystem.

Recommendation: derive one authoritative lifecycle transaction-path inventory before
mutation and reject any required link target that aliases any content node, lock node,
or managed container in that inventory. Use the same inventory for install preview,
install apply, and uninstall, with real overlap regressions requiring a fail-closed
report and exact preservation of every operator-owned node.

The initial 545-test process was interrupted before a terminal pytest summary and
therefore receives zero credit. No later inventory segment, host acceptance, static
check, Vaultspec check, build, wheel, public-Core smoke, or fresh installed-package gate
was started. None is waived. Earlier focused evidence remains useful but cannot
establish release readiness for this revision.

S48 verdict: **FAIL — not release-ready; one unresolved CRITICAL finding and one
unresolved HIGH finding**. Merge and publication remain blocked until Core publishes a
corrective release, RAG rejects full-lifecycle target overlap and adopts that Core
floor, and a fresh independent audit restarts all 1,824 selected tests and every other
release gate from zero.

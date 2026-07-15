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

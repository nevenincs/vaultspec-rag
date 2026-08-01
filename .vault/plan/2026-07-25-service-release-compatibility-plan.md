---
tags:
  - '#plan'
  - '#service-release-compatibility'
date: '2026-07-25'
modified: '2026-07-27'
body_hash: 'sha256:5ecd31149186107b9f3b798abd0d485b0e4af350ebe79423e0b8fd312db09a3e'
tier: L2
related:
  - '[[2026-07-25-service-release-compatibility-adr]]'
  - '[[2026-07-25-service-release-compatibility-reference]]'
  - '[[2026-07-27-service-release-compatibility-research]]'
---

# `service-release-compatibility` plan

### Phase `P01` - publication and classification

Stamp this install's release onto every payload the daemon already publishes, and declare the one field name and the one classifier that turn any of those payloads into a compatibility verdict.

- [x] `P01.S01` - Declare the wire field name, the three verdict states, the two structured error codes, the single restart remediation, and the verdict type in one import-light client module; `src/vaultspec_rag/serviceclient/_compat.py`.
- [x] `P01.S02` - Classify any published payload into the three-state verdict, treating an absent, blank, or non-string version as unreported rather than a silent pass, and resolve this install's release through the already-cached package attribute rather than a second metadata read; `src/vaultspec_rag/serviceclient/_compat.py`.
- [x] `P01.S03` - Stamp the release onto the health payload the daemon publishes; `src/vaultspec_rag/server/_lifespan.py`.
- [x] `P01.S04` - Stamp the release onto the readiness report; `src/vaultspec_rag/_readiness.py`.
- [x] `P01.S05` - Stamp the release onto the daemon-owned discovery snapshot, which is the single source for both the status sidecar and the machine pointer; `src/vaultspec_rag/server/_lifecycle.py`.
- [x] `P01.S06` - Stamp the release onto the spawning parent's own initial sidecar write; `src/vaultspec_rag/cli/_service_status.py`.
- [x] `P01.S07` - Enforce the discovery schema discriminator at the reader, resolving a live holder's unrecognised pointer as degraded rather than absent while still accepting a payload that carries neither field; `src/vaultspec_rag/serviceclient/_discovery.py`.

### Phase `P02` - client surfaces adapt to the verdict

Route every surface through the shared verdict: the data-plane seam refuses a foreign release, the lifecycle and observability verbs render it and keep working against any release, and no adapter re-derives the comparison.

- [x] `P02.S08` - Resolve the daemon address and its release verdict together at one data-plane seam, deliberately excluding the stop, status, doctor, logs, and jobs verbs so the verdict stays actionable; `src/vaultspec_rag/serviceclient/_compat.py`.
- [x] `P02.S09` - Gate the start verb's attach path on the health response it already fetches, converging on the shared lifecycle failure helper with both versions in its data and a non-zero exit in human and JSON modes alike; `src/vaultspec_rag/cli/_service_start.py`.
- [x] `P02.S10` - Refuse every MCP tool call at the single port-precondition helper using the verdict already carried on the discovery pointer, costing no extra round trip; `src/vaultspec_rag/mcp/_tools.py`.
- [x] `P02.S11` - Refuse a reachable-but-incompatible service on the search data-plane path; `src/vaultspec_rag/cli/_search.py`.
- [x] `P02.S12` - Refuse a reachable-but-incompatible service on the index refresh and clean data-plane path; `src/vaultspec_rag/cli/_index.py`.
- [x] `P02.S13` - Render one refusal for both incompatible states from the shared verdict, so no surface invents its own code, reason, or remediation wording; `src/vaultspec_rag/cli/_render.py`.
- [x] `P02.S14` - Print the running release unconditionally in status and add the reason and remediation when it is incompatible; `src/vaultspec_rag/cli/_status_render.py`.
- [x] `P02.S15` - Fold an incompatible release into the doctor's exit code at the same tier as a daemon that is expected but not live; `src/vaultspec_rag/cli/_service_doctor.py`.

### Phase `P03` - coverage and boundary reconciliation

Prove the three verdict states and the refusal sites can fail, reconcile the fixtures the new field and the new gate invalidate, and document the enforced pin on the discovery surface.

- [x] `P03.S16` - Cover the three verdict states, the four publication sites, the enforced discriminator, and every refusal site, mutation-proving each guard fails on the assertion it names; `src/vaultspec_rag/tests/test_service_version_compatibility.py`.
- [x] `P03.S17` - Reconcile the exact-key-set assertion the new readiness field grows, keeping readiness a bounded snapshot; `src/vaultspec_rag/tests/test_readiness.py`.
- [x] `P03.S18` - Stamp this install's release into the discovered-but-dead-service fixture so that case reaches the unreachability assertion it names instead of being refused earlier by the release gate; `src/vaultspec_rag/tests/test_search_service_first.py`.
- [x] `P03.S19` - Document the published release field, its distinction from the schema pair, and the enforced pin on the discovery surface; `docs/service-discovery.md`.

## Description

This plan executes the accepted decision to publish the daemon's own package release on
every payload it already emits and to compare it client-side, exactly once, in a shared
import-light module. The authorizing ADR and the compatibility-chain reference are named
in `related:`.

The implementation landed ahead of this document, so the plan is a retroactive tracking
record: a closed Step here asserts behaviour verified present at the cited path, not work
performed under this plan, and no Execution Record backs the closed rows. The one open
Step is genuinely open.

The classifier lives at `src/vaultspec_rag/serviceclient/_compat.py:1-232`. It owns the
wire field name (`_compat.py:35`), the three verdict states (`_compat.py:39-41`), the two
structured error codes (`_compat.py:45-46`), the single restart remediation
(`_compat.py:50-53`), the verdict type and its renderers (`_compat.py:86-137`), the
classifier itself (`_compat.py:150-183`), and the one data-plane seam that pairs an
address with a verdict (`_compat.py:186-232`). Cite that module, not an earlier home: the
survey behind the ADR was taken against modules that have since moved.

P01 covers the four publication sites and the classifier. The daemon stamps health at
`src/vaultspec_rag/server/_lifespan.py:1161`, readiness at
`src/vaultspec_rag/_readiness.py:173`, and the discovery snapshot at
`src/vaultspec_rag/server/_lifecycle.py:205` - the last being the single source for both
the status sidecar and the machine pointer, so one insertion reaches both views. The
spawning parent stamps its own initial sidecar write at
`src/vaultspec_rag/cli/_service_status.py:135`. The separate and narrower obligation, the
schema discriminator becoming enforced rather than merely written, is
`_discovery_pair_understood` at `src/vaultspec_rag/serviceclient/_discovery.py:463-476`.

P02 covers the surfaces. Data-plane callers refuse a foreign release: the MCP at its
single port precondition (`src/vaultspec_rag/mcp/_tools.py:170-194`), search at
`src/vaultspec_rag/cli/_search.py:1156-1157`, and index refresh and clean at
`src/vaultspec_rag/cli/_index.py:646-647`. The start verb gates its attach path at
`src/vaultspec_rag/cli/_service_start.py:235` and `:460`. The refusal is rendered from one
place, `_display_service_version_error` at `src/vaultspec_rag/cli/_render.py:468-498`.
Status renders the verdict at `src/vaultspec_rag/cli/_status_render.py:479-483` and doctor
folds it into its exit tier at `src/vaultspec_rag/cli/_service_doctor.py:127-200`. The
lifecycle and observability verbs - stop, status, doctor, logs, jobs - are deliberately
not gated, because they are how an operator sees the mismatch and how they resolve it.

P03 covers coverage and the fixtures the change invalidates. The compatibility suite is
`src/vaultspec_rag/tests/test_service_version_compatibility.py`; the readiness key-set
assertion already admits the new field at
`src/vaultspec_rag/tests/test_readiness.py:132-143`.

A forked version of this same decision exists on an unmerged rescue branch, carrying its
own decision record, plan, reference, execution records, and an alternative module. That
fork was reviewed and resolved against the implementation this plan tracks, which is a
functional superset of it: both name the wire field identically, and the fork's cached
version lookup is not an advantage over reading the already-resolved package attribute,
which costs nothing on the second call. The fork's only unique surface, a summary
renderer, is already produced here on the envelope path. That branch stays unmerged and
is a source for this plan's Step structure only; no Step here describes the dropped
module.

### Boundary against the concurrent session

Two tests currently fail on the error code `service_version_unreported`, and they do not
belong to the same owner. The distinguishing fact is fixture isolation, and it is
verifiable by reading the fixtures rather than by re-running them.

`test_discovered_dead_service_errors_without_fallback` in
`src/vaultspec_rag/tests/test_search_service_first.py:207-226` is **this plan's work**,
tracked as `P03.S18`. It runs under `isolated_status_dir`
(`test_search_service_first.py:58-69`), which relocates both managed directories, so no
service on the host can reach it and the outcome is deterministic. It writes a discovery
document carrying pid, port, and token and no release field, which predates the stamp
this feature added. The data-plane guard at `src/vaultspec_rag/cli/_search.py:1157`
therefore refuses on the release gate before the test can reach the `port_unreachable`
assertion it actually names. That is this feature's gate landing on a stale fixture, and
nothing outside this feature would touch it.

`test_reindex_compatibility_keeps_mcp_refresh_distinct_from_clean` in
`src/vaultspec_rag/tests/integration/test_service_job_control.py:371` is **not this
plan's work**. Its harness, `_real_job_control_server`
(`test_service_job_control.py:44-105`), relocates the status directory only and leaves the
machine-global pointer to the host. Discovery resolves that pointer ahead of the
status-dir hint, so the verdict this test gets is whatever daemon happens to be live on
the machine: a matching one passes, an absent or older one reports unreported. The defect
is missing singleton isolation in a harness every test in that module shares, not
release-compatibility behaviour, and this feature must not unilaterally rewrite it. It is
left to the session already diagnosing the environment-dependence.

Neither side is assumed to cover the other. If that session concludes the second failure
is release-compatibility work after all, `P03` is where the Step lands, added through the
plan verbs; until then this plan claims only the first.

## Steps

Evidence gap: the retained document body has no authored Steps content beyond scaffold comments or placeholders.

## Parallelization

`P01.S01` and `P01.S02` are the hard prerequisite for everything else: the field name and
the verdict type must exist before any publisher can stamp or any surface can classify.

The four publication Steps (`P01.S03` through `P01.S06`) touch four separate modules and
carry no interdependency, so they parallelize freely once the field name exists.
`P01.S07` is independent of all of them - the discriminator is a different field with a
different obligation - and can run at any point.

Within `P02`, `P02.S08` precedes the three data-plane refusals (`P02.S11`, `P02.S12`, and
the MCP at `P02.S10`) because all three consume the seam it defines, and `P02.S13`
precedes `P02.S09` because the start verb renders through it. `P02.S14` and `P02.S15` are
read-only renderings of the verdict and depend on nothing but `P01.S02`.

`P03` follows the surfaces it covers. `P03.S18`, the only open Step, has no dependency on
any other open work and can be taken alone.

## Verification

- The comparison exists in exactly one place. A search for the wire field constant and
  the classifier finds one definition under `src/vaultspec_rag/serviceclient/`, and no
  surface re-derives the verdict from two version strings of its own.
- All three verdict states are covered and each guard is mutation-proven: breaking the
  guard makes the test fail on the assertion it names, not on an import or a collection
  error, and both directions are recorded where the test's next reader will find them.
- An unreported version is refused, never passed. A payload with the field absent, blank,
  whitespace, or non-string classifies as unreported and carries its own error code,
  distinct from a mismatch.
- Every data-plane caller refuses a reachable-but-foreign daemon, and no lifecycle or
  observability verb does. `stop`, `status`, `doctor`, `logs`, and `jobs` still complete
  against a daemon of any release.
- Each refusal emits exactly one structured envelope and exits non-zero in both human and
  JSON modes, with both versions in its data and the single restart remediation as its
  next action.
- The comparing module stays torch-free and import-light: importing it in a fresh
  interpreter leaves `torch` out of `sys.modules`.
- `P03.S18` is verified by running
  `src/vaultspec_rag/tests/test_search_service_first.py::TestServiceFirstRouting::test_discovered_dead_service_errors_without_fallback`
  alone and seeing it fail on `port_unreachable` rather than on the release gate, with the
  full module green afterwards.
- Lint, format, type-check, and the tests covering the touched branches are run
  explicitly before the commit that closes the last Step.
- The plan is complete when every Step is closed.

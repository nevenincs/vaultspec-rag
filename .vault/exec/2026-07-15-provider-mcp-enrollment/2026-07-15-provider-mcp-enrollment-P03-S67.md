---
tags:
  - '#exec'
  - '#provider-mcp-enrollment'
date: '2026-07-16'
modified: '2026-07-22'
step_id: 'S67'
related:
  - "[[2026-07-15-provider-mcp-enrollment-plan]]"
---

# Repeat every platform-aware release gate after the model-aware service-startup correction

## Scope

- One clean commit containing the complete S66 correction.
- Fresh Windows and exact-archive POSIX collection ledgers.
- Complete S54, S56, and S66 bounded-runtime contracts.
- All runtime, static, package, public-dependency, provider, idempotence,
  unenrollment, and uninstall gates.
- Stop on the first failed or non-terminal gate.

## Description

- Recount the clean candidate's complete real `.vault` Markdown corpus and
  recollect both platform inventories from zero.
- Reconcile the unique `M`, `P`, `J`, and `F` sets without carrying S65 or S66
  counts, runtime results, or waivers.
- Audit the S66 diff independently. Require all eager service models to pass the
  S56 completeness test before spawn, cold or interrupted caches to use bounded
  online repair, and the daemon to enter supported offline/cache-only mode
  before readiness polling.
- Prove inherited offline switches are removed during repair and restored
  afterward, and require cache-only markers from the same effective model
  configuration, including a disabled-reranker path.
- Require one explicit whole-startup deadline, retained model-worker and service
  output, completed-stage timings, endpoint exclusion, and forced cleanup of
  every test-owned service or Qdrant survivor.
- Require Qdrant identity publication before model warming and prove
  pre-readiness failure or cancellation leaves no owned process or listener on
  Windows and the POSIX detached-session path.
- Audit forced POSIX stop independently: require exact service-incarnation,
  managed-storage, ready-port, pinned-version, and Qdrant-image validation
  before any detached child is signalled, and fail closed for unrelated or
  unverifiable identities.
- Repeat the exact formerly failed jobs selector, the full jobs and
  service-startup groups, and the complete S56 full-corpus ranking worker before
  crediting the broader runtime campaign.
- Run every remaining release gate in the preserved S65 order from the same
  clean commit.

## Outcome

Failed at the independent code-review gate before the selected runtime campaign.

The audit inspected exact clean commit
`83ecbadf2fc735170af892bb4d8c1a191338068a`, independently recounted 1,122
unique `.vault` Markdown documents, and rebuilt both collection ledgers from
zero. Windows collected 2,283 unique items: 1,840 in `M`, six disjoint promoted
items in `P`, 13 Windows-only junction items in `J`, no `F`, 1,846 campaign
items, and 437 exclusions. The fresh exact-archive POSIX environment collected
2,273 unique items: 1,843 in `M`, the same six disjoint `P` items, no `J`, one
real-FIFO `F` item inside `M`, two additional S66 POSIX-only forced-stop items,
1,849 campaign items, and 424 exclusions.

The frozen Windows and POSIX environments resolved successfully, direct
scikit-learn 1.9.0 imports passed, and published `vaultspec-core==0.1.45` was
present. The independent review then found five actionable MEDIUM defects:

- auth-token recovery can spend the remaining job timeout independently on
  three sequential requests;
- pre-warming Qdrant status publication can be skipped if the child starts
  before the parent writes `service.json`;
- forced POSIX cleanup witnesses the service incarnation but not the Qdrant
  child incarnation;
- a repeated status-directory override can overwrite the saved ambient value
  and leak the isolated directory after context-entry failure; and
- model repair, spawn, and status-write failures do not receive the promised
  whole-startup diagnostics, while repair termination can exceed the remaining
  budget by its fixed grace period.

The environment leak and multiplied admin deadline were reproduced
independently with real child-process and loopback HTTP probes. The first red
review gate stopped the campaign. No FIFO runtime selector, focused S54/S56/S64/
S66 selector, full Windows or POSIX runtime campaign, static gate, package gate,
provider gate, host-recognition gate, idempotence gate, unenrollment gate,
uninstall gate, pull request, approval, merge, tag, publication, or release
received S67 credit.

## Notes

S67 began with zero carried credit. Because formal review failed first, every
runtime and later gate remains uncredited. S66 focused, repeated, adjacent, S56,
and static results are remediation evidence only. A green S67 verdict requires
every mandated gate to terminate successfully at one clean commit. This mandate
does not authorize a pull request, approval, merge, tag, publication, or
release.

The unrelated installed service observed at PID 88968 on port 8766 and its
Qdrant PID 65108 on port 8765 remained outside the isolated audit and was not
signalled or stopped.

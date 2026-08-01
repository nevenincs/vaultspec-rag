---
tags:
  - '#plan'
  - '#service-health-client-hardening'
date: '2026-07-22'
modified: '2026-07-27'
body_hash: 'sha256:93761765bb58275f24002c6bdfb574ff3a628beef3a75a5f5d7b939ef2acc10b'
tier: L2
related:
  - '[[2026-07-22-service-health-client-hardening-adr]]'
  - '[[2026-07-22-service-health-client-hardening-research]]'
---

# `service-health-client-hardening` plan

## Description

Executes `2026-07-22-service-health-client-hardening-adr`, grounded in
`2026-07-22-service-health-client-hardening-research`. One ADR governs all three
Phases: `P01` delivers D1, `P02` delivers D3, and `P03` delivers D2 together
with D5.

The Phase order is not a convenience. D1's sequencing constraint is binding: the
redirect correction must land and be verified before any consolidation begins,
because the refusing opener is presently the only thing confining a consistent
responder to the local port. Running `P03` first would move the health call onto
a redirect-following client and hold that window open for the duration of the
migration. `P02` sits between them because the bounded default it establishes is
the default the new health owner inherits.

Scope boundary, stated because the adjacent defect is easy to conflate with this
work: the self-referential identity check in the service stop path is NOT
addressed here. D4 defers it to its own record. No Step in this plan repairs it,
and no Step, record, or commit arising from this plan may be described as
repairing it. The redirect correction narrows the conditions under which that
weakness can be reached; it does not make the check sound.

## Steps

### Phase `P01` - correct the redirect defect on the shared transport

Stop the transport following redirects on every request path, and prove refusal on both the health path and a credential-bearing path.

- [x] `P01.S01` - Build the transport's requests through a redirect-refusing opener so no request path follows a 3xx; `src/vaultspec_rag/serviceclient/_transport.py`.
- [x] `P01.S02` - Assert a redirect answered on the health path is refused rather than followed; `src/vaultspec_rag/tests/test_http_admin_errors.py`.
- [x] `P01.S03` - Assert a redirect answered on a token-carrying request path is refused and the bearer credential never reaches the redirect target; `src/vaultspec_rag/tests/test_http_admin_errors.py`.

### Phase `P02` - enumerate transport callers and bound the default timeout

Establish which callers rely on the absent default timeout, then replace that default with a bounded one.

- [x] `P02.S04` - Enumerate every caller of the general transport entry point and record which rely on the absent default timeout, treating each as an unbounded credential-exposure window rather than a bookkeeping entry; `src/vaultspec_rag/serviceclient/_transport.py`.
- [x] `P02.S05` - Replace the general entry point's absent default timeout with a bounded default, leaving callers that need a different bound to pass one explicitly; `src/vaultspec_rag/serviceclient/_transport.py`.
- [x] `P02.S06` - Assert a call that omits the timeout argument is bounded rather than able to wait indefinitely; `src/vaultspec_rag/tests/test_http_admin_errors.py`.

### Phase `P03` - move health-call ownership to the transport

Give the health call one owner that keeps the probe's non-raising contract, repoint every call site to it, and correct the module docstring.

- [x] `P03.S07` - Add a dedicated health function to the transport that returns the parsed body, returns a structured error carrying the HTTP code when the service answers unhealthily, returns a sentinel when unreachable, never raises, and defaults to a bounded timeout matching the command-line probe; `src/vaultspec_rag/serviceclient/_transport.py`.
- [x] `P03.S08` - Assert the health function returns a sentinel on unreachability, a structured error on an unhealthy answer, and the parsed body on success, and that it raises in none of those cases; `src/vaultspec_rag/tests/test_http_admin_errors.py`.
- [x] `P03.S09` - Repoint the already-running status read in service start to the transport's health function; `src/vaultspec_rag/cli/_service_start.py`.
- [x] `P03.S10` - Repoint the readiness-and-token read in service start, which persists the token into the status file, to the transport's health function; `src/vaultspec_rag/cli/_service_start.py`.
- [x] `P03.S11` - Repoint the serving-pid and token resolution in service stop to the transport's health function; `src/vaultspec_rag/cli/_service_stop.py`.
- [x] `P03.S12` - Repoint the identity token comparison in the process helper to the transport's health function; `src/vaultspec_rag/cli/_process.py`.
- [x] `P03.S13` - Repoint the token-confirmation read in status rendering to the transport's health function; `src/vaultspec_rag/cli/_status_render.py`.
- [x] `P03.S14` - Repoint the status-file-absent JSON payload read in status rendering to the transport's health function; `src/vaultspec_rag/cli/_status_render.py`.
- [x] `P03.S15` - Repoint the running-state summary read in status rendering to the transport's health function; `src/vaultspec_rag/cli/_status_render.py`.
- [x] `P03.S16` - Repoint the explicit-port state read in status rendering to the transport's health function; `src/vaultspec_rag/cli/_status_render.py`.
- [x] `P03.S17` - Repoint the operational-summary read in status rendering to the transport's health function; `src/vaultspec_rag/cli/_status_render.py`.
- [x] `P03.S18` - Repoint the integration readiness-wait helper to the transport's health function; `src/vaultspec_rag/tests/integration/_helpers.py`.
- [x] `P03.S19` - Remove the command-line probe's separate implementation once no call site depends on it, leaving at most a thin delegation to the single owner; `src/vaultspec_rag/cli/_process.py`.
- [x] `P03.S20` - Assert every repointed call site preserves its sentinel semantics, so unreachability stays an ordinary branch and no exception escapes the service start or service stop verbs; `src/vaultspec_rag/tests/test_cli_service_status.py`.
- [x] `P03.S21` - Correct the module docstring's false claim that every call funnels through the general entry point, and document the two failure idioms the module now exposes; `src/vaultspec_rag/serviceclient/_transport.py`.
- [x] `P03.S23` - Repoint the discovery-reconciliation probe injection to the transport's health function, a consumer the plan's call-site enumeration missed because the probe is passed as a value rather than invoked; `src/vaultspec_rag/cli/_service_reconcile.py`.
- [x] `P03.S24` - Repoint the five interception points that patch the command-line probe symbol to the new target, and prove at least one still catches its intended failure by mutating the token comparison to confirm it goes red and restoring it; `src/vaultspec_rag/tests/test_cli_status.py`.

### Phase `P04` - independent closing review

Judge the whole plan against the authorizing decision, by a reviewer with no authorship in it, and record the verdict as an audit document.

- [x] `P04.S22` - Review the delivered plan against its authorizing decision and record the verdict, confirming that redirect refusal is transport-wide rather than health-only, that the credential-bearing request path is asserted and not only the health path, that every repointed call site preserves its sentinel semantics with no exception escaping the two envelope-bound verbs, that the caller enumeration behind the bounded default was performed rather than assumed, and that no delivered code, test, record, or commit message describes the deferred stop-path identity check as fixed; `the reviewer must have no authorship in this plan, and the author of all twenty-one preceding Steps is ineligible;`.vault/audit/2026-07-22-service-health-client-hardening-audit.md\`.

## Parallelization

No separate parallelization is recorded in the retained prior plan body. Source: retained prior plan body.

## Verification

No separate verification is recorded in the retained prior plan body. Source: retained prior plan body.

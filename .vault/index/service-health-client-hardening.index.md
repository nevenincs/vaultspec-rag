---
generated: true
tags:
  - '#index'
  - '#service-health-client-hardening'
date: '2026-08-14'
modified: '2026-08-14'
body_schema: 'body-v1'
body_hash: 'sha256:0ef79ff4cdbe0cc2467ed5a9cf69220b8c14769de7173514eb1b2d383c7892bb'
related:
  - '[[2026-07-22-service-health-client-hardening-P01-S01]]'
  - '[[2026-07-22-service-health-client-hardening-P01-S02]]'
  - '[[2026-07-22-service-health-client-hardening-P01-S03]]'
  - '[[2026-07-22-service-health-client-hardening-P02-S04]]'
  - '[[2026-07-22-service-health-client-hardening-P02-S05]]'
  - '[[2026-07-22-service-health-client-hardening-P02-S06]]'
  - '[[2026-07-22-service-health-client-hardening-P03-S07]]'
  - '[[2026-07-22-service-health-client-hardening-P03-S08]]'
  - '[[2026-07-22-service-health-client-hardening-P03-S09]]'
  - '[[2026-07-22-service-health-client-hardening-P03-S10]]'
  - '[[2026-07-22-service-health-client-hardening-P03-S11]]'
  - '[[2026-07-22-service-health-client-hardening-P03-S12]]'
  - '[[2026-07-22-service-health-client-hardening-P03-S13]]'
  - '[[2026-07-22-service-health-client-hardening-P03-S14]]'
  - '[[2026-07-22-service-health-client-hardening-P03-S15]]'
  - '[[2026-07-22-service-health-client-hardening-P03-S16]]'
  - '[[2026-07-22-service-health-client-hardening-P03-S17]]'
  - '[[2026-07-22-service-health-client-hardening-P03-S18]]'
  - '[[2026-07-22-service-health-client-hardening-P03-S19]]'
  - '[[2026-07-22-service-health-client-hardening-P03-S20]]'
  - '[[2026-07-22-service-health-client-hardening-P03-S21]]'
  - '[[2026-07-22-service-health-client-hardening-P03-S23]]'
  - '[[2026-07-22-service-health-client-hardening-P03-S24]]'
  - '[[2026-07-22-service-health-client-hardening-adr]]'
  - '[[2026-07-22-service-health-client-hardening-plan]]'
  - '[[2026-07-22-service-health-client-hardening-research]]'
  - '[[2026-07-23-service-health-client-hardening-audit]]'
---

# `service-health-client-hardening` feature index

Auto-generated index of all documents tagged with `#service-health-client-hardening`.

## Documents

### adr

- `2026-07-22-service-health-client-hardening-adr` - `service-health-client-hardening` adr: `health call ownership, redirect policy, and error contract` | (**status:** `accepted`)

### audit

- `2026-07-23-service-health-client-hardening-audit` - `service-health-client-hardening` audit: `independent closing review — passed on revision`

### exec

- `2026-07-22-service-health-client-hardening-P01-S01` - Build the transport's requests through a redirect-refusing opener so no request path follows a 3xx
- `2026-07-22-service-health-client-hardening-P01-S02` - Assert a redirect answered on the health path is refused rather than followed
- `2026-07-22-service-health-client-hardening-P01-S03` - Assert a redirect answered on a token-carrying request path is refused and the bearer credential never reaches the redirect target
- `2026-07-22-service-health-client-hardening-P02-S04` - Enumerate every caller of the general transport entry point and record which rely on the absent default timeout, treating each as an unbounded credential-exposure window rather than a bookkeeping entry
- `2026-07-22-service-health-client-hardening-P02-S05` - Replace the general entry point's absent default timeout with a bounded default, leaving callers that need a different bound to pass one explicitly
- `2026-07-22-service-health-client-hardening-P02-S06` - Assert a call that omits the timeout argument is bounded rather than able to wait indefinitely
- `2026-07-22-service-health-client-hardening-P03-S07` - Add a dedicated health function to the transport that returns the parsed body, returns a structured error carrying the HTTP code when the service answers unhealthily, returns a sentinel when unreachable, never raises, and defaults to a bounded timeout matching the command-line probe
- `2026-07-22-service-health-client-hardening-P03-S08` - Assert the health function returns a sentinel on unreachability, a structured error on an unhealthy answer, and the parsed body on success, and that it raises in none of those cases
- `2026-07-22-service-health-client-hardening-P03-S09` - Repoint the already-running status read in service start to the transport's health function
- `2026-07-22-service-health-client-hardening-P03-S10` - Repoint the readiness-and-token read in service start, which persists the token into the status file, to the transport's health function
- `2026-07-22-service-health-client-hardening-P03-S11` - Repoint the serving-pid and token resolution in service stop to the transport's health function
- `2026-07-22-service-health-client-hardening-P03-S12` - Repoint the identity token comparison in the process helper to the transport's health function
- `2026-07-22-service-health-client-hardening-P03-S13` - Repoint the token-confirmation read in status rendering to the transport's health function
- `2026-07-22-service-health-client-hardening-P03-S14` - Repoint the status-file-absent JSON payload read in status rendering to the transport's health function
- `2026-07-22-service-health-client-hardening-P03-S15` - Repoint the running-state summary read in status rendering to the transport's health function
- `2026-07-22-service-health-client-hardening-P03-S16` - Repoint the explicit-port state read in status rendering to the transport's health function
- `2026-07-22-service-health-client-hardening-P03-S17` - Repoint the operational-summary read in status rendering to the transport's health function
- `2026-07-22-service-health-client-hardening-P03-S18` - Repoint the integration readiness-wait helper to the transport's health function
- `2026-07-22-service-health-client-hardening-P03-S19` - Remove the command-line probe's separate implementation once no call site depends on it, leaving at most a thin delegation to the single owner
- `2026-07-22-service-health-client-hardening-P03-S20` - Assert every repointed call site preserves its sentinel semantics, so unreachability stays an ordinary branch and no exception escapes the service start or service stop verbs
- `2026-07-22-service-health-client-hardening-P03-S21` - Correct the module docstring's false claim that every call funnels through the general entry point, and document the two failure idioms the module now exposes
- `2026-07-22-service-health-client-hardening-P03-S23` - Repoint the discovery-reconciliation probe injection to the transport's health function, a consumer the plan's call-site enumeration missed because the probe is passed as a value rather than invoked
- `2026-07-22-service-health-client-hardening-P03-S24` - Repoint the five interception points that patch the command-line probe symbol to the new target, and prove at least one still catches its intended failure by mutating the token comparison to confirm it goes red and restoring it

### plan

- `2026-07-22-service-health-client-hardening-plan` - `service-health-client-hardening` plan

### research

- `2026-07-22-service-health-client-hardening-research` - `service-health-client-hardening` research: `health probe duplication, redirect policy, and stop-path identity`

---
generated: true
tags:
  - '#index'
  - '#serviceclient-admin-errors'
date: '2026-06-24'
modified: '2026-06-24'
related:
  - '[[2026-06-24-serviceclient-admin-errors-S01]]'
  - '[[2026-06-24-serviceclient-admin-errors-S02]]'
  - '[[2026-06-24-serviceclient-admin-errors-adr]]'
  - '[[2026-06-24-serviceclient-admin-errors-audit]]'
  - '[[2026-06-24-serviceclient-admin-errors-plan]]'
  - '[[2026-06-24-serviceclient-admin-errors-research]]'
---

# `serviceclient-admin-errors` feature index

Auto-generated index of all documents tagged with `#serviceclient-admin-errors`.

## Documents

### adr

- `2026-06-24-serviceclient-admin-errors-adr` - `serviceclient-admin-errors` adr: `surface admin failures through the transport's structured error envelope` | (**status:** `accepted`)

### audit

- `2026-06-24-serviceclient-admin-errors-audit` - `serviceclient-admin-errors` audit: `admin-error envelope contract review (PASS)`

### exec

- `2026-06-24-serviceclient-admin-errors-S01` - Replace the catch-all empty-dict swallow in the admin helper with the structured http_call_failed ok=False envelope (mirroring the search and reindex helpers), leaving the connection-refused→None and timeout→admin_timeout branches unchanged
- `2026-06-24-serviceclient-admin-errors-S02` - Add a no-mock regression test: drive an admin call against a real in-process route that raises a non-refused, non-timeout error (e.g. a malformed non-JSON response) and assert it returns the http_call_failed envelope, distinguishable from a real empty result and from the unreachable None sentinel

### plan

- `2026-06-24-serviceclient-admin-errors-plan` - `serviceclient-admin-errors` plan

### research

- `2026-06-24-serviceclient-admin-errors-research` - `serviceclient-admin-errors` research: `swallowed admin errors in the shared service client`

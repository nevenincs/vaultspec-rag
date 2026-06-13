---
tags:
  - '#exec'
  - '#operability-hardening'
date: '2026-06-09'
modified: '2026-06-09'
step_id: 'S06'
related:
  - "[[2026-06-09-operability-hardening-plan]]"
---

# Route get_logs admin tool to /logs/json endpoint

## Scope

- `src/vaultspec_rag/cli/_http_search.py`
- `src/vaultspec_rag/tests/test_http_search_routing.py` (new)

## Description

`_route_admin_tool` in `_http_search.py` was routing the `get_logs` admin tool to `/logs`,
which returns plaintext. `_do_http_call` unconditionally calls `json.loads` on every
response, so the plaintext body raised `json.JSONDecodeError`, was swallowed, and produced
an empty `{}` — causing `server service logs` to always print "No log lines available."

The daemon already exposes `/logs/json` returning `{"lines": [...]}`. Changed the single
`url_path = "/logs"` assignment to `url_path = "/logs/json"` (line 106). The
`?lines=N` query-string appending is unchanged.

Added `src/vaultspec_rag/tests/test_http_search_routing.py` with two `unit`-marked tests
in `TestRouteAdminToolGetLogs`:

- `test_get_logs_routes_to_json_endpoint` — asserts bare call produces path `"/logs/json"`.
- `test_get_logs_with_lines_param_routes_to_json_endpoint` — asserts `lines=50` arg
  produces path starting with `"/logs/json"` containing `lines=50` and not the old bare
  `/logs` form.

Both tests use `monkeypatch` to intercept `_do_http_call` and capture the constructed
path without any network I/O.

## Outcome

- `ruff check` and `ty check` both clean on both files.
- 2/2 new unit tests pass.
- `server service logs` delegation now sends a JSON-capable route to the daemon.

## Notes

None.

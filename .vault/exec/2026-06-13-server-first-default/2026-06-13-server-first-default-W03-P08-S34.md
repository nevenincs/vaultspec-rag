---
tags:
  - '#exec'
  - '#server-first-default'
date: '2026-06-13'
modified: '2026-06-13'
step_id: 'S34'
related:
  - "[[2026-06-13-server-first-default-plan]]"
---

# add tests asserting the CLI readiness verb and MCP readiness tool return the same bounded snapshot in both modes

## Scope

- `src/vaultspec_rag/tests/test_server_doctor.py`

## Description

- Add unit tests (`tests/test_server_doctor.py`) for the `server doctor` verb: the `--json` envelope's `data` equals `api.get_readiness()`, the snapshot is the bounded three-dimension (torch/models/qdrant) shape, and the human render lists each dependency. No mocks/skips.
- Add a Starlette integration test (`tests/integration/test_server_doctor_route.py`) exercising the real `GET /readiness` route through `TestClient` built from `ROUTES` with a known `_SERVICE_TOKEN`: 401 without the token, 200 with it, and a body equal to `api.get_readiness()` — establishing CLI/route parity by construction (both read the same reporter).

## Outcome

- 5 tests pass (3 CLI unit + 2 route integration). The CLI JSON data and the route body are asserted equal to the same `get_readiness()` snapshot, proving both adapters return the identical bounded snapshot. `ruff`/`ty`/complexity clean.

## Notes

- Deviation from the plan's named scope `tests/test_cli.py`: the CLI tests live in a dedicated new file `test_server_doctor.py` (and the route test in `integration/test_server_doctor_route.py`) to avoid the concurrently-edited `test_cli.py`. The token-set-with-restore fixture mirrors the existing metrics route test (real ASGI client, no mocks/monkeypatch).

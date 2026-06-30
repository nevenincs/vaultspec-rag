---
tags:
  - '#exec'
  - '#sparse-search-latency'
date: '2026-06-09'
modified: '2026-06-30'
step_id: 'P05.S16'
related:
  - '[[2026-06-08-sparse-search-latency-plan]]'
---

# `sparse-search-latency` P05.S16 - remove `_resources.py` server internal imports

scope: `src/vaultspec_rag/mcp/_resources.py`

## Description

Verified that the `mcp/` package no longer imports any server internals. `_resources.py`
imports only `from ._mcp import mcp` and `from ._tools import _call_daemon`; the previous
`import vaultspec_rag.server as _m`, `from ..server._utils import _default_root`, and
`_m._http_mode` reads were already eliminated when `P05.S15` rewired the `vault://` resource
to the `/vault-document` REST endpoint (commit `5b38c13`).

A package-wide grep confirmed no `mcp/*.py` file imports `server`, `store`, `service`, or
`registry`. The only remaining cross-package import is `_tools.py` → `cli._service_status`
(a peer consumer-client helper that reads `service.json`), which is permitted by the
invariant.

## Outcome

Step satisfied with no further code change required. The import-isolation invariant is now
enforced by the `P05.S18` guard test.

## Notes

`_tools.py` carries a comment referencing a `_registry` test-rebind alias; that is
descriptive prose, not a server import.

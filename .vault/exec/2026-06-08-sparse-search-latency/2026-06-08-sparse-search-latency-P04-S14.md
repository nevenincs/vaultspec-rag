---
tags:
  - '#exec'
  - '#sparse-search-latency'
date: '2026-06-08'
related:
  - '[[2026-06-08-sparse-search-latency-plan]]'
---

# `sparse-search-latency` `P04.S14` execution

Fixed `mcp.get_starlette_app()` missing method crash in `_main.py` which was causing the daemon process to exit immediately with code 1. Replaced it with `mcp.streamable_http_app()` as specified in the service-observability ADR. Also fixed an assertion bug in `test_adr_regression.py` that expected `urllib.request` in `_try_http_search` but was missed after `_do_http_call` extraction.

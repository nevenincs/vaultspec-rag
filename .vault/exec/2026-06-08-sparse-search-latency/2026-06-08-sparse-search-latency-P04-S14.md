---
tags:
  - '#exec'
  - '#sparse-search-latency'
date: '2026-06-08'
modified: '2026-07-27'
related:
  - '[[2026-06-08-sparse-search-latency-plan]]'
---
# `sparse-search-latency` `P04.S14` execution

## Description

Fixed `mcp.get_starlette_app()` missing method crash in `_main.py` which was causing the daemon process to exit immediately with code 1. Replaced it with `mcp.streamable_http_app()` as specified in the service-observability ADR. Also fixed an assertion bug in `test_adr_regression.py` that expected `urllib.request` in `_try_http_search` but was missed after `_do_http_call` extraction.

## Outcome

Evidence gap: the original record contains no outcome or result section; a result is not established here.

## Notes

Evidence gap: the original record contains no Notes section with authored incident, deferred-work, or follow-up evidence.

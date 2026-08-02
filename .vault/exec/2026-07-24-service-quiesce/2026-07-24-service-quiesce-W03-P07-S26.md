---
tags:
  - '#exec'
  - '#service-quiesce'
date: '2026-07-30'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:cddb3ecdb3b4a4cc44f490b91f061ed8dee978ae6493dee8f527c91380be582f'
step_id: 'S26'
related:
  - "[[2026-07-24-service-quiesce-plan]]"
---

# Expose the service-owned quiesce block through existing MCP service-state delegation without adding public lifecycle mutation tools

## Scope

- `src/vaultspec_rag/mcp/_tools.py`

## Description

Return the existing service-state response directly through MCP so the
controller-owned quiesce block is observed without adapter reconstruction or
lifecycle interpretation.

## Outcome

Accepted for S26 from `866f399c`. The MCP status tool returns the same mapping
as the authenticated production service-state route. Its checked-in
fresh-interpreter probe compares the direct and MCP documents exactly and
confirms that neither path imports a model, Torch, or Qdrant dependency.

## Notes

No lifecycle mutation tool was added. This reconciliation inspected the
checked-in CPU-only probe but did not execute it or start a service.

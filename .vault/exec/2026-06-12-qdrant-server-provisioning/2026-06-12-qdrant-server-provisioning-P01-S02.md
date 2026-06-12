---
tags:
  - '#exec'
  - '#qdrant-server-provisioning'
date: '2026-06-12'
step_id: 'S02'
related:
  - "[[2026-06-12-qdrant-server-provisioning-plan]]"
---

# Implement platform-to-asset mapping and active-binary resolution ordered env var, provisioned dir, PATH

## Scope

- `src/vaultspec_rag/qdrant_runtime/_resolve.py`

## Description

- Add `qdrant_runtime/_resolve.py`: platform/arch to release-asset mapping for the six
  pinned assets (unsupported pairs raise with the env-var escape hatch named), the managed
  bin dir layout (`{status_dir}/bin/qdrant/{version}/`), manifest reading, and
  `resolve_binary()` ordered operator env var > provisioned dir > PATH.

## Outcome

`TestAssetResolution` and `TestResolution` unit tests green: seven platform pairs map
correctly, unsupported pairs raise, env binary wins over a provisioned install, a binary
without a manifest is not treated as provisioned.

## Notes

None.

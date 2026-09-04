---
tags:
  - '#plan'
  - '#tool-mode-cuda'
date: '2026-09-01'
tier: L2
related:
  - '[[2026-07-14-tool-env-gpu-continuity-adr]]'
  - '[[2026-09-01-tool-mode-cuda-research]]'
  - '[[2026-09-01-tool-mode-cuda-reference]]'
modified: '2026-09-04'
body_hash: 'sha256:257d4226cb2b978063fffc70ddeca7c393c25cc8ddec83eff35c4c162a0795d2'
---

<!-- RETIRED: S03, S04 -->

# `tool-mode-cuda` plan

## Steps

### Phase `P01` - repair transaction

Create the single tool-mode CUDA repair backend and place it safely in installation orchestration.

- [x] `P01.S01` - Create the receipt-verified tool CUDA repair backend; `src/vaultspec_rag/commands/_tool_torch.py`.
- [x] `P01.S02` - Integrate the repair transaction and structured outcome; `src/vaultspec_rag/commands/_install.py and src/vaultspec_rag/commands/_models.py`.

### Phase `P02` - operator contract and proof

Expose consent and truthful outcomes, then prove each refusal and durable-success branch.

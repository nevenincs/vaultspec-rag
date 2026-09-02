---
tags:
  - '#plan'
  - '#tool-mode-cuda'
date: '2026-09-01'
modified: '2026-09-01'
body_hash: 'sha256:faf224c54b9ff21f47f42668589c9a9be81a2523e74867fe2cadca1f3647cc6b'
tier: L2
related:
  - '[[2026-07-14-tool-env-gpu-continuity-adr]]'
  - '[[2026-09-01-tool-mode-cuda-research]]'
  - '[[2026-09-01-tool-mode-cuda-reference]]'
---

# `tool-mode-cuda` plan

## Steps

### Phase `P01` - repair transaction

Create the single tool-mode CUDA repair backend and place it safely in installation orchestration.

- [ ] `P01.S01` - Create the receipt-verified tool CUDA repair backend; `src/vaultspec_rag/commands/_tool_torch.py`.
- [ ] `P01.S02` - Integrate the repair transaction and structured outcome; `src/vaultspec_rag/commands/_install.py and src/vaultspec_rag/commands/_models.py`.

### Phase `P02` - operator contract and proof

Expose consent and truthful outcomes, then prove each refusal and durable-success branch.

- [ ] `P02.S03` - Expose tool repair consent and report rendering; `src/vaultspec_rag/cli/_install.py`.
- [ ] `P02.S04` - Prove repair safety and receipt postconditions; `src/vaultspec_rag/tests/test_tool_torch_repair.py`.

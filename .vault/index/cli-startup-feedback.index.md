---
generated: true
tags:
  - '#index'
  - '#cli-startup-feedback'
date: '2026-08-14'
modified: '2026-08-14'
body_schema: 'body-v1'
body_hash: 'sha256:8ab579bd6dc4e91c1dac7ecfa67159ad9c6b8900edf1c998cacf0ee31837a18b'
related:
  - '[[2026-07-23-cli-startup-feedback-S01]]'
  - '[[2026-07-23-cli-startup-feedback-S02]]'
  - '[[2026-07-23-cli-startup-feedback-S03]]'
  - '[[2026-07-23-cli-startup-feedback-S04]]'
  - '[[2026-07-23-cli-startup-feedback-S05]]'
  - '[[2026-07-23-cli-startup-feedback-S06]]'
  - '[[2026-07-23-cli-startup-feedback-adr]]'
  - '[[2026-07-23-cli-startup-feedback-plan]]'
  - '[[2026-07-23-cli-startup-feedback-research]]'
---

# `cli-startup-feedback` feature index

Auto-generated index of all documents tagged with `#cli-startup-feedback`.

## Documents

### adr

- `2026-07-23-cli-startup-feedback-adr` - `cli-startup-feedback` adr: `publish structured startup progress; the CLI polls and renders it` | (**status:** `accepted`)

### exec

- `2026-07-23-cli-startup-feedback-S01` - Carry a structured startup-progress descriptor (stage id, label, optional done/total) on the discovery snapshot and \_DiscoveryPublisher, additive and best-effort
- `2026-07-23-cli-startup-feedback-S02` - Publish the structured descriptor at each cold-start stage boundary, filling done/total for the model-load count
- `2026-07-23-cli-startup-feedback-S03` - Render a determinate Rich bar in the start wait when total is present, falling back to the named spinner for a descriptor-less daemon
- `2026-07-23-cli-startup-feedback-S04` - Investigate whether the Hugging Face and pinned-binary downloaders expose incremental byte callbacks, and record whether download-percentage bars are feasible
- `2026-07-23-cli-startup-feedback-S05` - Add unit tests for the descriptor round-trip and the CLI bar/spinner rendering, including the older-daemon fallback guard
- `2026-07-23-cli-startup-feedback-S06` - Verify on a real GPU cold start that provisioning, per-model load count, and reranker stages render live, and record the execution

### plan

- `2026-07-23-cli-startup-feedback-plan` - `cli-startup-feedback` plan

### research

- `2026-07-23-cli-startup-feedback-research` - `cli-startup-feedback` research: `async live progress during service and index startup`

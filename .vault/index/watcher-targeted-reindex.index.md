---
generated: true
tags:
  - '#index'
  - '#watcher-targeted-reindex'
date: '2026-06-18'
related:
  - '[[2026-06-02-watcher-targeted-reindex-P03-S06]]'
  - '[[2026-06-02-watcher-targeted-reindex-P03-S07]]'
  - '[[2026-06-02-watcher-targeted-reindex-P03-S08]]'
  - '[[2026-06-02-watcher-targeted-reindex-adr]]'
  - '[[2026-06-02-watcher-targeted-reindex-plan]]'
  - '[[2026-06-02-watcher-targeted-reindex-research]]'
  - '[[2026-06-18-watcher-targeted-reindex-adr]]'
  - '[[2026-06-18-watcher-targeted-reindex-research]]'
---

# `watcher-targeted-reindex` feature index

Auto-generated index of all documents tagged with `#watcher-targeted-reindex`.

## Documents

### adr

- `2026-06-02-watcher-targeted-reindex-adr` - `watcher-targeted-reindex` adr: `watcher targeted reindex contract` | (**status:** `accepted`)
- `2026-06-18-watcher-targeted-reindex-adr` - `watcher-targeted-reindex` adr: `idle-tick flush for cooldown-suppressed reindex` | (**status:** `accepted`)

### exec

- `2026-06-02-watcher-targeted-reindex-P03-S06` - Construct the watcher's awatch with yield_on_timeout=True and an explicit one-second rust_timeout, and re-drain the pending vault and code sets on every loop iteration so an empty idle-tick batch reconciles cooldown-suppressed changes while the unchanged per-source cooldown guard still gates the actual reindex
- `2026-06-02-watcher-targeted-reindex-P03-S07` - Add a real-backend watcher regression test that deletes a tracked file during the cooldown window then leaves the tree quiet and asserts the chunks are evicted, plus a guard that an idle tick during an open cooldown does not trigger a premature reindex, folding in the reproduction scenarios and exercising the real backend with no mocks or skips
- `2026-06-02-watcher-targeted-reindex-P03-S08` - Run ruff and the full pytest suite and confirm zero violations and green before PR

### plan

- `2026-06-02-watcher-targeted-reindex-plan` - `watcher-targeted-reindex` `watcher targeted reindex` plan

### research

- `2026-06-02-watcher-targeted-reindex-research` - `watcher-targeted-reindex` research: `watcher targeted reindex: per-change cost`
- `2026-06-18-watcher-targeted-reindex-research` - `watcher-targeted-reindex` research: `stranded pending changes on quiet trees`

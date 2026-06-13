# vaultspec-rag docs corpus — target information architecture

Campaign: rewrite the git-visible user-facing markdown corpus to the **server-first-default**
branch reality. Every doc runs the full vaultspec-documentation wireframe pipeline.

## Diataxis map (target)

| File | Type | Role |
| --- | --- | --- |
| `docs/getting-started.md` | Tutorial | First run end to end: install → setup → index → first search (server-first). |
| `docs/installation.md` | How-to | Package install + `install` provisioning (torch/models/qdrant binary), `--local-only`, per-dependency skips, verify (`server doctor`/`status`), recovery, uninstall. |
| `docs/search-and-index.md` | How-to | Run + refine searches (current flags, readable-records output); build/refresh the index day to day. |
| `docs/service-mode.md` | How-to | Run/observe/stop the background service (server-first); `server doctor`, `projects`, `updates`, `logs`/`jobs`, HTTP monitoring. Flat `server` CLI. |
| `docs/backends.md` | Explanation + How-to | **NEW.** Supervised managed Qdrant server (default) vs `--local-only`; provisioning + `server qdrant install\|status\|clean`; per-root namespacing; air-gapped/CI. |
| `docs/mcp.md` | How-to | Wire into Claude Desktop (stdio) + Claude Code (HTTP); current tool list. |
| `docs/automation.md` | How-to | `--json` envelope, error/exit codes, jq recipes, CI gating. |
| `docs/preprocessing-hooks.md` | How-to + Reference | Custom extractors (`.vaultragpreprocess.toml`, schema, caching, security). |
| `docs/cli.md` | Reference | Every command/flag for the flat `server` tree + `qdrant`/`updates`/`doctor` + install opt-outs + exit codes. |
| `docs/configuration.md` | Reference | Env vars + flags + defaults (incl. LOCAL_ONLY, qdrant_server, sparse_enabled, dense_backend, …). |
| `docs/glossary.md` | Reference | Terms (fix locale entry; add backend/server/local, supervised server, readiness, provisioning, slot). |
| `docs/architecture.md` | Explanation | Concepts: RAG, how it works, semantic vs grep, why GPU, **why server-first**. |
| `docs/indexing.md` | Explanation/Reference | Deep indexing & retrieval internals + tuning; fix stale server-mode section. |
| `README.md` | How-to + Reference (landing) | Quickstart (server-first) + documentation map. |
| `src/vaultspec_rag/README.md` | Landing (PyPI) | Short quickstart + docs pointer. |

## Key restructure decisions
- Add `backends.md` — the server-first/local-only backend model is the headline change and needs its own home; `architecture.md` carries only the *why*, `service-mode.md`/`installation.md` carry operation, `backends.md` is the dedicated concept+how-to.
- Keep `architecture.md` (gentle concepts) and `indexing.md` (deep internals) distinct but cleanly cross-linked; no merge.
- Keep `search-and-index.md` combined (search + index how-to).

## Processing order (dependency-aware)
architecture → backends → installation → getting-started → search-and-index → service-mode →
mcp → automation → preprocessing-hooks → indexing → configuration → cli → glossary →
README → src README → finalize (cross-link + commit).

## Ground truth
Authoritative current-state facts: `.docs-campaign/ground-truth.md` (code-verified).

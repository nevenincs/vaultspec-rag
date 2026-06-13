---
tags:
  - '#research'
  - '#project-hardening'
date: 2026-05-03
modified: '2026-05-03'
related: []
---

# `project-hardening` research: `vaultspec-rag discoverability`

This note captures the practical listing and announcement targets for
`vaultspec-rag` after the 0.2.6 PyPI release and repository metadata pass.

## Current state

- Public PyPI install works: `uv run --isolated --no-project --with vaultspec-rag==0.2.6 python -c "import vaultspec_rag; print(vaultspec_rag.__version__)"` returned `0.2.6`.
- GitHub topics are set to: `cuda`, `embeddings`, `gpu`, `mcp`, `qdrant`, `rag`, `semantic-search`, `sentence-transformers`, `vector-search`, `vaultspec`.
- GitHub repository description is set to: `GPU-accelerated RAG search for vaultspec vaults and project codebases`.
- README badges now cover Python, PyPI, alpha status, CI, MCP, uv, and MIT license.

## Candidate listings

### MCP directories

Primary target: `appcypher/awesome-mcp-servers`.

Evidence: The repository describes itself as a curated list of MCP servers and
explicitly includes production-ready and experimental servers. It has a
Development Tools section, which is the best fit for a vault/code search MCP
server.

Reference: https://github.com/appcypher/awesome-mcp-servers

Secondary target: `MCP.Directory`.

Evidence: The directory has a visible `Submit Server` path and positions itself
as a browsable directory for MCP servers across Cursor, Claude Desktop, VS Code,
Claude Code, and other MCP-compatible clients.

Reference: https://mcp.directory/servers

### RAG and AI lists

Primary target: Awesome Lists / Awesome RAG style repositories.

Evidence: Awesome Lists are maintained as open contribution projects and accept
resources through GitHub. The RAG-specific surface is relevant, but submission
quality should wait until the repository is public and the README installation
path is stable.

Reference: https://www.awesomelists.io/lists/awesome-rag/

### Qdrant community

Primary target: Qdrant community channels, not a direct listing PR.

Evidence: Qdrant's community page points developers to Discord, events,
articles, demos, partners, and contributor programs. The project uses Qdrant
local mode as a core storage component, so a short demo or article is a better
fit than a bare repository link.

Reference: https://qdrant.tech/community/

## Recommended sequence

1. Make the repository public when the owner is ready. Most external directories
   require public source URLs.
1. Set GitHub social preview to `assets/logo.png` from issue #40.
1. Submit to `appcypher/awesome-mcp-servers` under Development Tools.
1. Submit to `MCP.Directory` using its `Submit Server` path.
1. Prepare a short Qdrant-oriented demo note showing local hybrid search over
   vault docs and source code.
1. Only after public visibility and stable docs, submit to RAG/AI awesome lists.

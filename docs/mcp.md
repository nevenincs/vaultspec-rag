# Use vaultspec-rag with MCP clients

An assistant like Claude Desktop or Claude Code can search your vault and source code directly. The Model Context Protocol (MCP) is a JSON-RPC interface assistants use to call external tools, and vaultspec-rag ships an MCP server that exposes its search and indexing operations as MCP tools. Any client that speaks stdio MCP or streamable HTTP MCP can connect.

Before you start, this page assumes you've installed vaultspec-rag and run at least one search. See the [installation guide](installation.md) for setup and the [getting-started tutorial](getting-started.md) for the first-search path. The MCP server binary `vaultspec-search-mcp` lands on `PATH` when you install the package.

## Choose a transport

vaultspec-rag offers two transports. The right pick depends on how you work.

- **stdio**: the client launches `vaultspec-search-mcp` as a child process, one per project. The server reads the project from `VAULTSPEC_RAG_ROOT`.
- **HTTP**: the client connects to one long-running service that serves many projects. Start the service first, then point the client at its MCP endpoint.

Pick stdio when you work in one project at a time. Pick HTTP when several projects share one service. The next two sections are common examples - either transport works with any compatible client.

## Configure a stdio client (Claude Desktop)

Claude Desktop reads its MCP config from `claude_desktop_config.json`. The location varies by operating system; open Claude Desktop's settings dialog to find the path on your machine.

Add a `vaultspec-rag` entry under `mcpServers`, point it at `vaultspec-search-mcp`, and set `VAULTSPEC_RAG_ROOT` to the absolute path of the project you want the assistant to search.

```json
{
  "mcpServers": {
    "vaultspec-rag": {
      "command": "vaultspec-search-mcp",
      "env": {
        "VAULTSPEC_RAG_ROOT": "/absolute/path/to/your/project"
      }
    }
  }
}
```

Restart Claude Desktop after editing the file so it picks up the new server.

## Configure an HTTP client (Claude Code)

The HTTP transport connects to the running service, so start the service first.

```bash
uv run vaultspec-rag server start
```

Create or edit `.mcp.json` at the project root and add the entry. Note the trailing slash on the endpoint:

```json
{
  "mcpServers": {
    "vaultspec-rag": {
      "type": "http",
      "url": "http://127.0.0.1:8766/mcp/"
    }
  }
}
```

The HTTP service is multi-tenant, so it needs the project path on every tool call. An editor like Claude Code sends its workspace path automatically once the server is registered. See how to [run and supervise the service](service-mode.md).

## Confirm the assistant sees the tools

In Claude Desktop, open the MCP debug panel and look for the `vaultspec-rag` server. In Claude Code, run `/mcp` and check that `vaultspec-rag` appears in the connected-servers list.

A connected server publishes the search and indexing tools, including `search_vault` and `search_codebase`. For the full tool list and parameters, see the [search and index guide](search-and-index.md) and the [CLI reference](cli.md).

For a smoke test, ask the assistant a retrieval question about your project, such as "find the ADR about caching" or "where is authentication handled?". A successful answer cites file locations from your project - a document path or a source file and line - rather than answering from general knowledge.

## Troubleshooting

### Assistant doesn't see the tools

In stdio mode, confirm `vaultspec-search-mcp` is on `PATH`:

```bash
which vaultspec-search-mcp
```

In HTTP mode, confirm the service is running:

```bash
uv run vaultspec-rag server status
```

If the service is down, start it with `uv run vaultspec-rag server start` and reconnect from the client.

### Results come from the wrong project

In HTTP mode, the client must send the right project path on every call. Check the client's MCP-call logs and confirm the path matches the workspace you expect. If your client doesn't auto-resolve the workspace path, set it explicitly in the client config.

In stdio mode, set `VAULTSPEC_RAG_ROOT` to the absolute project path in the `env` block and restart the client. Without that variable, the server falls back to its working directory, which rarely matches the project you want.

### First call is slow

Embedding and reranker models load on first use, which can take several seconds. Pre-warm them before launching the assistant:

```bash
uv run vaultspec-rag server warmup
```

Otherwise, accept the one-time delay on the first search of the session.

## Where to go next

- [Run and supervise the HTTP service](service-mode.md).
- [Browse the full tool list and search filters](search-and-index.md).
- [Look up commands and parameters in the CLI reference](cli.md).

If something still doesn't work, check the [Support](../README.md#support-and-help) section of the repo README.

# Using vaultspec-rag with MCP clients

The Model Context Protocol (MCP) is a JSON-RPC interface AI clients use to call external tools. vaultspec-rag ships an MCP server that exposes its search and indexing operations as MCP tools, so an assistant like Claude Desktop or Claude Code can query your vault and source code directly. Any client that speaks stdio MCP or streamable HTTP MCP can connect, including Claude Desktop, Claude Code, and similar tools.

Before you start, this page assumes you have vaultspec-rag installed and have run at least one search successfully. See [installation.md](installation.md) for setup and [getting-started.md](getting-started.md) for the smoke-test path. The MCP server binary `vaultspec-search-mcp` lands on `PATH` automatically when the package is installed.

## Choose a transport

vaultspec-rag offers two transports, and the right pick depends on how you work.

- **stdio**: the client launches `vaultspec-search-mcp` as a child process, one process per project. Suitable for Claude Desktop and any client where each workspace gets its own MCP server.
- **HTTP**: the client connects to a long-running HTTP service on `127.0.0.1:8766`. One daemon serves any number of projects. Suitable for Claude Code or any setup where several projects share one daemon.

Pick stdio if you work in one project at a time, HTTP if you switch between projects or already run the service.

## Configure Claude Desktop (stdio)

Claude Desktop reads its MCP config from `claude_desktop_config.json`. The exact location varies by operating system; open Claude Desktop's settings dialog to see the path on your machine.

Add a `vaultspec-rag` entry under `mcpServers`, pointing at the stdio binary and setting `VAULTSPEC_RAG_ROOT` to the absolute path of the project you want the assistant to search.

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

## Configure Claude Code (HTTP)

Claude Code talks to vaultspec-rag over HTTP. Start the service first, then register it in your project's `.mcp.json`.

```bash
uv run vaultspec-rag server service start
```

Create or edit `.mcp.json` at the project root and add the entry:

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

The HTTP service is multi-tenant and refuses tool calls that do not include a `project_root`. The client must send an absolute project path on every call. Claude Code resolves `${workspaceFolder}` from the editor's project root, so the path travels automatically once the server is registered.

## Confirm the assistant sees the tools

In Claude Desktop, open the MCP debug panel and look for the `vaultspec-rag` server. In Claude Code, run `/mcp` and check that `vaultspec-rag` appears in the connected-servers list. A connected server publishes fifteen tools covering search, indexing, status, project management, watcher control, and service observability. Beyond the search and indexing tools, this includes filesystem-watcher control (`get_watcher_state`, `start_watcher`, `stop_watcher`, `reconfigure_watcher`) and service observability (`get_service_state`, `get_logs`, `get_jobs`). For the full parameter list, see [cli.md](cli.md); the same tools surface there.

For a smoke test, ask the assistant a question that requires retrieval, for example "find the ADR about caching", and confirm it cites vault hits in the response.

## Troubleshooting

### Assistant does not see the tools

In stdio mode, verify `vaultspec-search-mcp` is on `PATH`:

```bash
which vaultspec-search-mcp
```

In HTTP mode, verify the service is running:

```bash
uv run vaultspec-rag server service status
```

If the service is down, start it with `uv run vaultspec-rag server service start` and reconnect from the client.

### Results come from the wrong project

In HTTP mode, the client must send the correct `project_root` on every call. Check the client's MCP-call logs and confirm the path matches the workspace you expect. If your client does not auto-resolve the workspace path, set it explicitly in the client config.

In stdio mode, set `VAULTSPEC_RAG_ROOT` in the `env` block of `claude_desktop_config.json` and restart the client. Without that variable, the server falls back to its current working directory, which rarely matches the project you want.

### First call is slow

Embedding and reranker models load on first use, which can take several seconds. Pre-warm them before launching the assistant:

```bash
uv run vaultspec-rag server service warmup
```

Otherwise, accept the one-time delay on the first search of the session.

## Need help?

If something still does not work, check the [Support](../README.md#support-and-help) section of the repo README.

# How to use vaultspec-rag with MCP clients

This guide shows you how to expose vaultspec-rag to an AI assistant so the assistant can search your vault and codebase on your behalf.

The Model Context Protocol (MCP) is a JSON-RPC interface that AI clients use to call external tools, and vaultspec-rag ships an MCP server that publishes its search and indexing operations as MCP tools. Any client that speaks MCP can use them. Confirmed clients include Claude Desktop, Claude Code, and any other client that supports either the stdio or streamable HTTP transport.

## Choose a transport

vaultspec-rag offers two transports. Pick one before you edit any config.

- **stdio**: the client launches `vaultspec-search-mcp` as a child process. One process serves one project. The project root comes from the `VAULTSPEC_RAG_ROOT` environment variable, falling back to the working directory. Best for desktop clients that handle a single project at a time.
- **HTTP**: the client connects to a long-running HTTP service on `127.0.0.1:8766`. One daemon serves every project on your machine, and the client passes a `project_root` argument on each tool call. Best when several projects share one daemon, or when you already run the service for other reasons.

If you only ever work on one project from one client, use stdio. If you switch between projects, or you want the embedding models to stay warm across sessions, use HTTP.

## Configure Claude Desktop with stdio

Open `claude_desktop_config.json` (the path varies by operating system; Claude Desktop's settings dialog reveals it) and add a server entry:

```json
{
  "mcpServers": {
    "vaultspec-rag": {
      "command": "vaultspec-search-mcp",
      "env": { "VAULTSPEC_RAG_ROOT": "/absolute/path/to/your/project" }
    }
  }
}
```

Use an absolute path for `VAULTSPEC_RAG_ROOT`. Restart Claude Desktop so it picks up the new server. The `vaultspec-search-mcp` binary must be on the `PATH` that Claude Desktop inherits; if it isn't, replace `"command"` with the absolute path to the binary.

## Configure Claude Code with HTTP

First, start the HTTP service from a terminal in any directory:

```bash
uv run vaultspec-rag server service start
```

The service binds to `http://127.0.0.1:8766` and exposes the MCP endpoint at `http://127.0.0.1:8766/mcp/`. Leave it running.

Next, add `.mcp.json` at the root of the project you want Claude Code to search:

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

The HTTP service is multi-tenant and refuses tool calls without a `project_root` argument. The MCP client must pass an absolute path on every call. Claude Code resolves `${workspaceFolder}` from the project root where you ran the editor. If results come from the wrong project, the client is sending the wrong path; check the client's MCP-call logs.

## Confirm the assistant sees the tools

In Claude Desktop, open the MCP debug panel and look for `vaultspec-rag` in the list of connected servers. In Claude Code, run `/mcp` and check that `vaultspec-rag` reports as connected. A connected server publishes eight tools covering search, indexing, status, and project management. For the full parameter list, see [the MCP tools reference](../reference/mcp-tools.md).

Ask the assistant a question that requires search ("find the ADR about caching") to verify the tools are wired up end to end.

## Troubleshooting

**The assistant doesn't see the tools.** For stdio, confirm `vaultspec-search-mcp` is on `PATH` by running `which vaultspec-search-mcp` (Unix) or `where vaultspec-search-mcp` (Windows). For HTTP, run `vaultspec-rag server service status` and start the service if it isn't running.

**Results come from the wrong project.** In HTTP mode, the client must pass the correct `project_root` on each call; if your client doesn't set it automatically, ask the assistant to pass the absolute path. In stdio mode, set `VAULTSPEC_RAG_ROOT` in the `env` block and restart the client.

**The first call takes a long time.** vaultspec-rag loads its embedding models on first use. To avoid the delay during a session, run `vaultspec-rag server service warmup` before you launch the assistant. The warmup loads models into GPU memory without serving requests.

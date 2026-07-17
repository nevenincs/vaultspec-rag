# Use vaultspec-rag with MCP clients

An assistant like Claude Desktop or Claude Code can search your vault and source code without leaving the editor. The Model Context Protocol (MCP) is a JSON-RPC interface assistants use to call external tools. vaultspec-rag ships an MCP server that exposes its search and indexing operations as MCP tools. Any client that speaks stdio MCP can connect.

Before you start, this page assumes you've installed vaultspec-rag and run at least one search. See the [installation guide](installation.md) for setup and the [getting-started tutorial](getting-started.md) for the first-search path. The MCP server binary `vaultspec-search-mcp` lands on `PATH` when you install the package.

## How the MCP server connects

MCP has one transport here: **stdio**. The client launches `vaultspec-search-mcp` as a child process, and the server reads the project from `VAULTSPEC_RAG_ROOT`. That stdio process loads no models; every tool call delegates to the running HTTP service daemon over its native REST API. So the daemon does the compute and serves many projects at once, while each client gets a thin, fast stdio shim.

The HTTP service daemon does **not** speak MCP. It serves only vaultspec-rag's native REST routes - health, jobs, logs, projects, and the search and index endpoints the stdio shim calls. Those REST routes are the operator and monitoring surface, covered in the [service-mode guide](service-mode.md); they are not an MCP endpoint, and no MCP client connects to them directly. Start the daemon before using the MCP server so the stdio shim has a backend to delegate to.

### Stdio server lifetime

A stdio server lives exactly as long as its client connection. The normal shutdown is stdin closing (EOF), but some clients abandon or kill the launcher chain without ever closing the pipe - on Windows that used to leave orphaned `uv -> launcher -> python` chains running forever. The shim therefore anchors its lifetime to the client and exits on its own (one JSON line on stderr, exit code 0) when the client dies. The primary anchor identifies the exact process that created the shim's stdin pipe - the MCP client itself, however many `uv` or launcher wrappers sit in between - and reaps immediately, even if the client was already gone at startup. When stdin is not a client-created pipe (console runs, unusual spawners), the shim falls back to watching the process chain that spawned it, with a short startup grace so transient spawn helpers do not count. The same layered design runs in the vaultspec-core MCP server, with the identical stderr event shape, so host tooling can treat both alike. Nothing to configure, and none of it affects the HTTP service daemon, which is designed to outlive its spawner.

Two knobs exist for unusual setups: `--parent-pid <pid>` adds an explicit process to watch (for spawners that know their own PID), and `VAULTSPEC_RAG_STDIO_WATCHDOG=0` disables the self-reap entirely.

## Configure a stdio client (Claude Desktop)

Claude Desktop reads its MCP config from `claude_desktop_config.json`. The location varies by operating system; open Claude Desktop's settings dialog to find the path on your machine.

Add a `vaultspec-rag` entry under `mcpServers` and point it at `vaultspec-search-mcp`. Set `VAULTSPEC_RAG_ROOT` to the absolute path of the project you want the assistant to search.

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

## Configure a stdio client (Claude Code)

Claude Code launches the same stdio server. Because every tool call delegates to the HTTP daemon, start the service first so the shim has a backend.

```bash
uv run vaultspec-rag server start
```

Create or edit `.mcp.json` at the project root and add the entry. Point it at `vaultspec-search-mcp` and set `VAULTSPEC_RAG_ROOT` to the project path:

```json
{
  "mcpServers": {
    "vaultspec-rag": {
      "command": "vaultspec-search-mcp",
      "env": {
        "VAULTSPEC_RAG_ROOT": "${workspaceFolder}"
      }
    }
  }
}
```

The daemon is multi-tenant, so the shim tags each delegated call with the project root it resolved from `VAULTSPEC_RAG_ROOT`. See how to [run and supervise the service](service-mode.md).

## Confirm the assistant sees the tools

In Claude Desktop, open the MCP debug panel and look for the `vaultspec-rag` server. In Claude Code, run `/mcp` and check that `vaultspec-rag` appears in the connected-servers list.

A connected server publishes exactly these five tools:

- `search_vault` - search the documentation vault for relevant ADRs, plans, and research, with the same filters as the `search` command (doc type, feature, date, tag) plus an `intent` ranking profile.
- `search_codebase` - search the source codebase for relevant functions, classes, or logic, with the code filters (language, path, symbol, include and exclude globs) plus noise-domain control via the typed `exclude_domains` / `only_domains` / `include_domains` arguments (see [Filter noise by domain](search-and-index.md#filter-noise-by-domain)).
- `get_code_file` - return the full content of a source file by path.
- `reindex_vault` - re-index the vault documentation incrementally.
- `reindex_codebase` - re-index the source codebase incrementally.

The search filters mirror the CLI, so the [CLI reference](cli.md) documents the filter values in full. Service operations - jobs, logs, project slots, the file watcher, and service state - are not MCP tools; they are HTTP REST routes on the daemon and are driven through the `vaultspec-rag server` CLI or queried directly. See the [service-mode guide](service-mode.md) for that surface.

For a smoke test, ask the assistant a retrieval question about your project, such as "find the ADR about caching" or "where is authentication handled?". A successful answer cites file locations from your project, a document path or a source file and line, rather than answering from general knowledge.

## Troubleshooting

### Assistant doesn't see the tools

First confirm `vaultspec-search-mcp` is on `PATH`:

```bash
which vaultspec-search-mcp
```

Then confirm the service daemon is running, since every tool call delegates to it:

```bash
uv run vaultspec-rag server status
```

If the service is down the tools connect but every call reports "service is not running". Start it with `uv run vaultspec-rag server start` and reconnect from the client.

### Results come from the wrong project

Set `VAULTSPEC_RAG_ROOT` to the absolute project path in the `env` block and restart the client. Without that variable, the server falls back to its working directory, which rarely matches the project you want.

### First call is slow

The first search of a session loads the models and can take several seconds. Pre-warm them before launching the assistant with `uv run vaultspec-rag server warmup`. See [run and supervise the service](service-mode.md) for how warmup works.

## Where to go next

- [Run and supervise the HTTP service](service-mode.md).
- [Search filters and result formats](search-and-index.md).
- [Commands, flags, and filter values in the CLI reference](cli.md).

If something still doesn't work, check the [Support](../README.md#support-and-help) section of the repo README.

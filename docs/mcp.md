# Use vaultspec-rag with MCP clients

An assistant like Claude Desktop or Claude Code can search your source code, and
the decision records in your `.vault/` directory, without you switching tools.
The Model Context Protocol (MCP) is a JSON-RPC interface assistants use to call
external tools, and vaultspec-rag ships an MCP server that exposes its search
and indexing operations as MCP tools. Any client that speaks stdio MCP can
connect.

This page assumes you have installed vaultspec-rag and run at least one search.
See the [installation guide](installation.md) for setup and the
[getting-started tutorial](getting-started.md) for the first-search path.

## Install the MCP server

`vaultspec-rag install` enrolls the MCP server by default. It installs the
optional `mcp` dependency and writes the client configuration for you:

```bash
vaultspec-rag install
```

The server publishes six index-mutating tools, one of which deletes every index
for the project. If you want the assistant to search and nothing else, see
[Withholding the mutating tools](#withholding-the-mutating-tools) before you
connect a client.

Use `--no-mcp` for a CLI-only workspace, which also skips the `mcp` dependency
and, on Windows, `pywin32`.

Prefer `vaultspec-rag install` over hand-writing the config. `--mode` selects
the launch shape: `tool` (the default, launched via uvx), `dependency` (resolved
through the project's own virtual environment and shipped in built
distributions), or `dev` (like `dependency`, but confined to the dev dependency
group). `server doctor` compares the shape in your config against the declared
mode, so a hand-written entry that disagrees with the mode shows up as a failing
check.

The `vaultspec-search-mcp` console script is registered by the base install, but
it needs the `mcp` extra to run. Without it the server exits at launch with a
message naming the fix. `vaultspec-rag[gpu,mcp]` installs the MCP protocol and
the local inference stack together.

### Start the service

Start the HTTP service before connecting a client:

```bash
vaultspec-rag server start
```

### Check the client sees it

In Claude Desktop, open the MCP debug panel and look for the `vaultspec-rag`
server. In Claude Code, run `/mcp` and check that `vaultspec-rag` appears in the
connected-servers list.

Then ask the assistant a retrieval question about your project, such as "find
the decision record about caching" or "where is authentication handled?". A
successful answer cites locations from your project, a document path or a source
file and line, rather than answering from general knowledge.

## How the connection works

MCP reaches vaultspec-rag over stdio only. The client launches
`vaultspec-search-mcp` as a child process, and that stdio server reads the
project from `VAULTSPEC_RAG_ROOT`. It loads no models: it forwards every call to
the HTTP service, which does the compute and serves several projects at once.
Because the service is multi-tenant, the stdio server tags each forwarded call
with the project root it resolved.

The HTTP service does not speak MCP. It serves only vaultspec-rag's own REST
routes, which are the operator and monitoring surface covered in the
[service-mode guide](service-mode.md). No MCP client connects to them directly.

Passing `--port` does not serve MCP over HTTP. It starts the REST service daemon
instead, which is what `server start` launches. Leave `--port` off for MCP.

## The tools

A connected server publishes twelve tools. Six read:

- `search_vault` searches the documentation vault, with the same filters as the
  `search` command (doc type, feature, date, tag) plus an `intent` ranking
  profile.
- `search_codebase` searches source code, with the code filters (language, path,
  symbol, include and exclude globs) plus controls to include or exclude whole
  classes of files such as tests, generated code, and vendored trees, through
  the `exclude_domains`, `only_domains`, and `include_domains` arguments. See
  [Filter noise by domain](search-and-index.md#filter-noise-by-domain).
- `search_documents` searches extracted documents, meaning preprocessed
  non-source content, as an independent domain.
- `search_combined` searches all three domains together, allocating candidates
  across them.
- `get_code_file` returns the full content of a source file by path.
- `get_index_status` reports whether a content kind is indexed, so an assistant
  can skip one that has no index.

Six mutate:

- `reindex_vault`, `reindex_codebase`, and `reindex_documents` re-index one
  domain incrementally, and `reindex_all` does all three.
- `clean_documents` deletes the extracted-document index for a project, and
  `clean_all` deletes the vault, code, and document indexes.

Search filters mirror the CLI, so the [CLI reference](cli.md) documents the
filter values in full.

Service administration is not exposed over MCP: jobs, logs, project slots, the
file watcher, service state, and starting or stopping the service all go through
the `vaultspec-rag server` CLI.

## Withholding the mutating tools

`clean_all` deletes every index for the project, and an assistant that can see a
tool will eventually call it. Launch with `--read-only` to serve only the six
read tools:

```json
{
  "mcpServers": {
    "vaultspec-rag": {
      "command": "vaultspec-search-mcp",
      "args": ["--read-only"],
      "env": {
        "VAULTSPEC_RAG_ROOT": "/absolute/path/to/your/project"
      }
    }
  }
}
```

The six mutating tools are withdrawn from the advertised listing rather than
refused on call, so the model is never handed the schema of something it cannot
use. Reindexing then happens through the CLI, or through the service's own
watcher, which keeps the index current without being asked.

## Configure a client by hand

`install` does not write configs for every client. If yours is one it misses,
copy an example below. Both use the console-script shape, which matches `tool`
mode; for `dependency` or `dev` mode, set `command` to `uv` and `args` to
`["run", "--no-sync", "python", "-m", "vaultspec_rag.server"]`.

Add `"args": ["--read-only"]` to either example to withhold the mutating tools.

### Claude Desktop

Claude Desktop reads its MCP config from `claude_desktop_config.json`. The
location varies by operating system; open Claude Desktop's settings dialog to
find the path on your machine.

Add a `vaultspec-rag` entry under `mcpServers` and set `VAULTSPEC_RAG_ROOT` to
the absolute path of the project you want the assistant to search:

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

Restart Claude Desktop after editing the file.

### Claude Code

Create or edit `.mcp.json` at the project root:

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

## Troubleshooting

### The assistant does not see the tools

Confirm the console script is on `PATH`:

```bash
which vaultspec-search-mcp
```

Then confirm the service is running:

```bash
vaultspec-rag server status
```

If the service is down the tools connect but every call reports that the service
is not running. Start it with `vaultspec-rag server start` and reconnect.

If the script is missing, the `mcp` extra is probably absent. Run
`vaultspec-rag install` to reconcile it.

### `server doctor` reports an install-mode mismatch

The launch shape in your client config disagrees with the declared provisioning
mode. Re-run `vaultspec-rag install --mode <mode>` with the mode you want, or
rewrite the entry to match it. See
[Install the MCP server](#install-the-mcp-server).

### Results come from the wrong project

Set `VAULTSPEC_RAG_ROOT` to the absolute project path in the `env` block and
restart the client. Without it the server falls back to its working directory,
which rarely matches the project you want.

### The first call is slow

The first search of a session loads the models and can take several seconds.
Pre-warm them before launching the assistant:

```bash
vaultspec-rag server warmup
```

## Process lifetime

The stdio server exits when its client does, printing one JSON line on stderr as
it goes. It detects a departing client by watching the process that created its
stdin pipe, so it leaves no orphaned `uv -> launcher -> python` chains behind on
Windows when a client kills the launcher without closing the pipe. Nothing here
needs configuring.

Two knobs exist for unusual setups: `--parent-pid <pid>` adds an explicit
process to watch, and `VAULTSPEC_RAG_STDIO_WATCHDOG=0` disables the self-reap.

## Where to go next

- [Run and supervise the service](service-mode.md).
- [Search filters and result formats](search-and-index.md).
- [Commands, flags, and filter values](cli.md).

If something still does not work, see
[Status and help](../README.md#status-and-help) in the repo README.

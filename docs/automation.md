# Scripting and automation

Every vaultspec-rag command supports `--json`. The flag suppresses Rich console
formatting and emits exactly one JSON document on stdout, newline-terminated.
Use it when shell scripts, CI jobs, or agent loops need to read results
programmatically instead of parsing tables. The flag exists so an automation
pipeline never has to scrape a human-formatted table and can detect every error
category by code rather than substring-match on prose.

This page assumes you have vaultspec-rag installed. See
[installation.md](installation.md) for setup.

## The envelope shape

Every `--json` response is a single JSON object with four mandatory fields:
`ok`, `command`, and either `data` (on success) or `error` plus `message`
(on failure). Extras like `remediation` arrays, `port` numbers, or state codes
appear only on error envelopes that surface them.

Success:

```json
{
  "ok": true,
  "command": "search",
  "data": {
    "results": [
      {"id": "adr/overview", "path": "adr/overview.md", "title": "Overview",
       "score": 0.81, "snippet": "...", "source": "vault"}
    ]
  }
}
```

Error:

```json
{
  "ok": false,
  "command": "search",
  "error": "port_unreachable",
  "message": "MCP service on port 8766 is unreachable. The CLI will not silently fall back to in-process search; start the service or re-run with --allow-fallback (single-agent use only).",
  "port": 8766,
  "remediation": [
    "vaultspec-rag server service status",
    "vaultspec-rag server service start",
    "rerun with --allow-fallback (single-agent only)"
  ]
}
```

## Parse a search with jq

```bash
vaultspec-rag search "graph rebuild race" --json \
  | jq -r '.data.results[].path'
```

The `data.results` array contains one object per result with `id`, `path`,
`title`, `score`, `snippet`, and `source` fields. See [cli.md](cli.md) for
the per-command `data` payload shapes.

## Detect success vs error

The contract: `ok` is `true` on success, `false` on error. Gate further work
on `ok`:

```bash
out=$(vaultspec-rag index --json)
if ! echo "$out" | jq -e '.ok' >/dev/null; then
  echo "$out" | jq -r '.error + ": " + .message' >&2
  exit 1
fi
```

Branch on the error code:

```bash
case $(echo "$out" | jq -r '.error // empty') in
  port_unreachable)   echo "service down, retrying"; ;;
  local_store_locked) echo "another process holds the lock, aborting"; exit 1;;
  stopped)            echo "service stopped, start it first"; exit 3;;
  "")                 echo "ok";;
esac
```

Exit codes map one-to-one with error categories: `0` success, `1` generic
failure, `2` usage error, `3` service stopped, `4` service divergent or
crashed.

## Worked example: gate CI on index health

Run the indexer in CI and fail the build if the code index is empty
(typically a sign that the file scan was misconfigured).

```bash
#!/usr/bin/env bash
set -euo pipefail

out=$(vaultspec-rag index --json)

if ! echo "$out" | jq -e '.ok' >/dev/null; then
  echo "indexing failed: $(echo "$out" | jq -r '.error')" >&2
  exit 1
fi

code_total=$(echo "$out" \
  | jq '[.data.sources[] | select(.source=="code") | .total] | add // 0')

if [ "$code_total" -eq 0 ]; then
  echo "code index is empty; check ignore globs and source roots" >&2
  exit 1
fi
```

Wire this into your CI's pre-merge or nightly job.

## Caveats

- Rich-formatted output is fully suppressed in `--json` mode; stdout contains
  the JSON document and one trailing newline only.
- `--json` affects stdout only; log lines at INFO, WARNING, and ERROR still
  go to stderr or the service log. Redirect with `2>/dev/null` if you do not
  want them in your captured output.
- When `--port N` cannot reach the service (the background daemon described
  in [service-mode.md](service-mode.md)), the envelope is
  `{"ok": false, "error": "port_unreachable", "port": N, "remediation": [...]}`
  with exit `1`. Treat `port_unreachable` as transient and retry, or pass
  `--allow-fallback` to run the command in-process against the local store
  (the on-disk search index in your `.vault/data/` directory) instead. See
  [configuration.md](configuration.md) for the relevant settings.

## Error code reference

| Code                             | When it appears                                                     | Exit |
| -------------------------------- | ------------------------------------------------------------------- | ---- |
| `invalid_filter_for_search_type` | Filter flag does not apply to the chosen search type.               | 2    |
| `dry_run_requires_code`          | `index --dry-run` invoked without `--type code` or `--type all`.    | 2    |
| `rebuild_requires_explicit_type` | `index --rebuild` invoked without an explicit `--type`.             | 2    |
| `json_requires_yes`              | `clean --json` invoked without `--yes`.                             | 2    |
| `port_unreachable`               | `--port N` cannot reach the service.                                | 1    |
| `mcp_call_failed`                | MCP round-trip raised before completing.                            | 1    |
| `local_store_locked`             | Another process holds the local store lock.                         | 1    |
| `rebuild_locked`                 | The rebuild lock could not be acquired (another rebuild in flight). | 1    |
| `stopped`                        | `server service status` queried while no service is running.        | 3    |

Service-status divergent/crashed states (file present, signals disagree) surface as exit 4 with detail in the status output rows rather than as `error` strings in the JSON envelope.

See [cli.md](cli.md) for per-command exit-code lists.

## Automatic re-indexing (the filesystem watcher)

The background service (see [service-mode.md](service-mode.md)) runs a
filesystem watcher that **re-indexes incrementally on file change**, so a
long-lived service keeps its index fresh without a cron job or manual reindex.
It is enabled by default.

What it watches: `.vault/` documents and tracked source files under the project
root. Changes are coalesced over a debounce window, and each source (vault vs
code) has an independent cooldown so a burst of edits triggers at most one
reindex per cooldown.

Configure it at `service start`, or via environment for headless/containerised
deployments:

```bash
# Pull-only service: no watcher, index only when you ask.
vaultspec-rag server service start --no-watch
# or: VAULTSPEC_RAG_WATCH_ENABLED=0 vaultspec-rag server service start

# Tune responsiveness (defaults: debounce 2000 ms, cooldown 30 s).
vaultspec-rag server service start --watch-debounce-ms 500 --watch-cooldown-s 10
```

`--watch-enabled` is the only off switch. `0` for debounce or cooldown means
"no delay", **not** "disabled". Flags left unset do not clobber an operator-set
`VAULTSPEC_RAG_WATCH*` env var. See [configuration.md](configuration.md) for
the full env list.

Inspect and control the watcher on a running service (both reachable from the
CLI and the matching MCP tools):

```bash
vaultspec-rag server service watcher status            # config + watched roots
vaultspec-rag server service watcher start  <root>     # eager start one root
vaultspec-rag server service watcher stop   <root>     # pull-only for one root
vaultspec-rag server service watcher reconfigure <root> \
    --debounce-ms 1000 --cooldown-s 15                 # restart with new tuning
```

Each supports `--json` and follows the standard envelope and exit codes (`3`
when the service is not running). Prefer `watcher status` over guessing whether
the index is current.

## Need help?

See the [Support](../README.md#support-and-help) section of the repo README.

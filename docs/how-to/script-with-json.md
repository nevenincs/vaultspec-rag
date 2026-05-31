# How to script vaultspec-rag with `--json` output

This guide shows you how to drive vaultspec-rag from shell scripts, CI pipelines, and agent loops by parsing its structured JSON output instead of scraping Rich-formatted tables.

## When to reach for `--json`

Use `--json` whenever a machine consumes the output. Typical cases:

- Shell scripts that pipe results into `jq`, `awk`, or another command.
- CI jobs that need to gate a build on indexer health or search results.
- Agent loops that call vaultspec-rag as a tool and parse the response.

If a human is reading the terminal, omit `--json` and keep the Rich tables. The two modes are mutually exclusive on stdout.

## The envelope at a glance

Every command supports `--json` and emits exactly one JSON document to stdout, newline-terminated. Success uses one shape, failure uses another:

```json
{"ok": true, "command": "search", "data": {"results": [...]}}
{"ok": false, "command": "search", "error": "invalid_filter_for_search_type", "message": "..."}
```

The `command` field is the dotted command name, such as `search`, `index`, or `service.status`. Some error envelopes carry extras like a `remediation` array. For the full contract, see the [JSON envelope reference](../reference/json-envelope.md).

## Run a search and parse the results

Pipe the search command straight into `jq`:

```bash
uv run vaultspec-rag search "qdrant filter" --type code --json \
  | jq '.data.results[] | {path, score, snippet}'
```

If you only want the top hit's path:

```bash
uv run vaultspec-rag search "qdrant filter" --type code --json \
  | jq -r '.data.results[0].path'
```

The envelope always wraps the payload, so `.data.*` is your entry point on success.

## Detect success and read the error code

Test the `ok` flag with `jq -e`:

```bash
if uv run vaultspec-rag status --json | jq -e '.ok' >/dev/null; then
  echo "index healthy"
else
  echo "index check failed"
fi
```

On failure, read the stable `error` code and branch on it:

```bash
response=$(uv run vaultspec-rag search "x" --type vault --filter lang=py --json)
case "$(echo "$response" | jq -r '.error // empty')" in
  invalid_filter_for_search_type) echo "filter not valid for vault search" ;;
  port_unreachable)                echo "service is down" ;;
  gpu_unavailable)                 echo "no CUDA device visible" ;;
  "")                              echo "$response" | jq '.data' ;;
esac
```

Error codes are part of the public contract and map one-to-one with exit codes: `0` success, `1` generic failure, `2` usage error, `3` service stopped, `4` service divergent or crashed.

## Worked example: fail CI when nothing changed but files were expected

This script runs the indexer and fails the build when a source you expected to be growing produces zero added or updated chunks. The indexer envelope reports per-source counts under `data.sources[]`.

```bash
#!/usr/bin/env bash
set -euo pipefail

result=$(uv run vaultspec-rag index --json 2>/dev/null)

if ! echo "$result" | jq -e '.ok' >/dev/null; then
  echo "indexer failed: $(echo "$result" | jq -r '.message')" >&2
  exit 1
fi

# Each sources[] entry is { source, added, updated, removed, total, duration_ms }
code_total=$(echo "$result" | jq -r '.data.sources[] | select(.source=="code") | .total')

if [[ "$code_total" -eq 0 ]]; then
  echo "code index is empty - expected at least one chunk" >&2
  exit 1
fi
```

Wire that into your CI step and the build breaks the moment the indexer stops covering the files you care about.

## Caveats

Three behaviors surprise scripts:

- Rich-formatted output is fully suppressed in `--json` mode. Stdout contains the JSON document and one trailing newline, nothing else. No tables, color codes, or box-drawing characters leak in.
- `--json` controls stdout only. Log lines at `INFO`, `WARNING`, and `ERROR` still go to stderr or the service log file. If you do not want them, redirect with `2>/dev/null` as shown in the CI example.
- When `--port N` cannot reach the service, the envelope is `{"ok": false, "error": "port_unreachable", "port": N, "remediation": [...]}` and the process exits with code `1`. Treat `port_unreachable` as transient and retry, or fall back to the local store.

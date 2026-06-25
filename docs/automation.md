# Scripting and automation

Every vaultspec-rag command supports `--json`. The flag suppresses Rich console
formatting and emits exactly one JSON document on stdout, newline-terminated.
Use it when shell scripts, CI jobs, or agent loops need to read results
programmatically instead of parsing tables. Logs still go to stderr, so an
automation pipeline detects every error category by code rather than
substring-matching on prose. The continuous integration (CI) examples below
rely on that contract.

## Before you start

You need vaultspec-rag installed and a project indexed. See
[installation.md](installation.md) for setup and [getting-started.md](getting-started.md)
for indexing your first project.

Some commands delegate to the running HTTP service. Search and `index` auto-detect
a running service when you leave `--port` unset; pass `--port N` to target a
specific service. If the service is unreachable, the command returns the retryable
`port_unreachable` error (see [detecting errors](#detect-success-vs-error)).
Start the service with `vaultspec-rag server start`. For the full walkthrough, see
[service-mode.md](service-mode.md).

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

Branch on the error code. Treat `port_unreachable` as transient and retry, or
re-run with `--allow-fallback` to run in-process against the local store:

```bash
case $(echo "$out" | jq -r '.error // empty') in
  port_unreachable)   echo "service down, retry or use --allow-fallback";;
  local_store_locked) echo "another process holds the lock, aborting"; exit 1;;
  stopped)            echo "service not running, start it first"; exit 3;;
  "")                 echo "ok";;
esac
```

Exit codes map to error categories: `0` success, `1` generic failure, `2` usage
error, `3` service stopped, `4` service crashed or divergent. The
[exit codes and error strings](#exit-codes-and-error-strings) section lists the
codes; [cli.md](cli.md) is the authoritative per-command exit-code and error
list.

## Worked example: gate CI on index health

Run the indexer in CI and fail the build if the code index is empty (usually a
misconfigured file scan).

```bash
#!/usr/bin/env bash
set -euo pipefail

out=$(vaultspec-rag index --json)

if ! echo "$out" | jq -e '.ok' >/dev/null; then
  echo "indexing failed: $(echo "$out" | jq -r '.error')" >&2
  exit 1
fi

code_total=$(echo "$out" \
  | jq '[.data.sources[] | select(.source=="codebase") | .total] | add // 0')

if [ "$code_total" -eq 0 ]; then
  echo "code index is empty; check ignore globs and source roots" >&2
  exit 1
fi
```

Wire this into your CI's pre-merge or nightly job.

## The envelope shape

Every `--json` response is a single JSON object. The mandatory fields are `ok`,
`command`, and either `data` (on success) or `error` plus `message` (on failure).
Error envelopes may carry extras such as a `port` number or a `remediation`
array.

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
  "message": "MCP service on port 8766 is unreachable. Start the service or re-run with --allow-fallback (single-agent use only).",
  "port": 8766,
  "remediation": [
    "vaultspec-rag server status",
    "vaultspec-rag server start",
    "rerun with --allow-fallback (single-agent only)"
  ]
}
```

## Exit codes and error strings

Scripts gate on two signals: the process exit code and the `error` string. The
exit codes are `0` success, `1` generic failure, `2` usage error, `3` service
stopped, and `4` service crashed or divergent. The `error` field carries a stable
string code such as `port_unreachable`, `local_store_locked`, or `stopped`, which
is what the `case` branch above keys on. The [CLI reference](cli.md) is the
authoritative per-command list of exit codes and error strings.

## Caveats

- Rich-formatted output is fully suppressed in `--json` mode. Stdout contains the
  JSON document and one trailing newline only.
- `--json` affects stdout only. Log lines at INFO, WARNING, and ERROR still go to
  stderr or the service log. Redirect with `2>/dev/null` to keep them out of your
  captured output.
- `port_unreachable` is retryable. When `--port N` cannot reach the service, the
  envelope carries `error: "port_unreachable"`, the `port`, and a `remediation`
  array, and exits `1`. Retry, or pass `--allow-fallback` to run in-process
  against the on-disk store in your `.vault/data/` directory. See
  [configuration.md](configuration.md) for the relevant settings.

## Automatic re-indexing

The running service keeps the index fresh through its automatic-update watcher,
which re-indexes incrementally on file change. It is on by default, so a
long-lived service needs no cron job or manual reindex. For headless or
containerized deployments, set `VAULTSPEC_RAG_WATCH_ENABLED=0` to run pull-only.
Inspect and tune it with the `vaultspec-rag server updates ...` verbs. See
[service-mode.md](service-mode.md) for the full watcher story and
[configuration.md](configuration.md) for the environment variables.

## Where to go next

- [getting-started.md](getting-started.md) - index a project and run your first search.
- [service-mode.md](service-mode.md) - run the background service and its watcher.
- [cli.md](cli.md) - the authoritative per-command flag, exit-code, and error reference.
- [configuration.md](configuration.md) - environment variables and tuning knobs.

For anything else, see the [Support](../README.md#support-and-help) section of the
repo README.

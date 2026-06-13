# Storage backends

vaultspec-rag stores its search index in one of two backends: a managed, supervised local Qdrant server (the default) or a local-only embedded on-disk store. This page explains what each backend is, why the server is the default, when to choose local-only instead, and how to operate each one. Read it if you're deciding which backend to run, or you need the commands to provision, inspect, or switch backends.

The how-to sections here stay thin on purpose. For the full flag list on any command, see the [CLI reference](cli.md).

## The two backends in brief

The **managed Qdrant server** is a supervised local process. vaultspec-rag downloads a pinned Qdrant server binary, verifies it, runs it bound to loopback, and monitors it for the life of the search service. This is the default backend, and it handles its own concurrency, so many searches and index jobs can run at once.

The **local-only store** is an embedded on-disk Qdrant database. No separate process runs - the search service reads and writes the index files directly. The on-disk store lives under your project at `.vault/data/search-data/qdrant/`. It's the minimal alternative: nothing to download, nothing to supervise.

## Why the server is the default

The embedded mode serializes work through a single process. Under concurrent load - several searches arriving together, or a search competing with an index job - requests queue behind one another and throughput drops. The supervised server removes that limit. It accepts concurrent requests directly, so concurrent searches no longer queue behind a single process.

"Managed and supervised" means vaultspec-rag does the operational work. It downloads the server binary, runs it as a child process, monitors its health, restarts it once if it dies, and shuts it down cleanly when the service stops. You don't install or start Qdrant by hand.

A **pinned binary** is a specific version whose contents are known ahead of time - vaultspec-rag targets Qdrant `1.18.2` exactly, not "whatever is latest." A **checksum** is a fingerprint of the binary's contents, compared against a known-good value before the binary runs, so a tampered or corrupted download is refused.

## When to choose local-only instead

Local-only is a first-class, single-flag choice, not a degraded mode. Pick it when:

- You're running in continuous integration (CI), where a per-run binary download is wasteful.
- You're on an air-gapped machine that can't reach the download host.
- Your use is single-user or low-concurrency, so the server's parallelism adds little.
- Your environment forbids downloading and running an external binary.

The trade-off you accept is lower throughput under concurrent load. For one developer running occasional searches, that trade-off is usually invisible.

## How provisioning and verification work

During setup, vaultspec-rag downloads the pinned Qdrant server binary - version `1.18.2` - over HTTPS from an allowlist of hosts. It computes the SHA256 checksum of the downloaded archive and compares it to a checksum built into the tool. If the checksums don't match, vaultspec-rag deletes the partial download and refuses to continue. Only a verified binary is extracted, and it's re-checked against its recorded fingerprint immediately before it runs. The verified binary is stored in a managed location under your status directory.

For air-gapped machines, you supply your own binary instead of downloading one. The operator-supplied binary still flows through the same supervised path, and a checksum mismatch is still a hard failure.

Provisioning happens as part of `install`. For the setup command and its flags, see the [installation guide](installation.md).

## How to operate the managed server

Three commands under `server qdrant` cover the managed server's lifecycle. For the full flag list, see the [CLI reference](cli.md).

- `server qdrant install` downloads and verifies the managed Qdrant server, then records it. Use it to provision the binary outside of `install`, or to upgrade it.

  ```
  vaultspec-rag server qdrant install
  ```

- `server qdrant status` reports the managed version, the resolved executable, the server address, whether the connection is ready, the supervised process, and any other installs present.

  ```
  vaultspec-rag server qdrant status
  ```

- `server qdrant clean` deletes managed Qdrant installs. It never touches your index data. Deletion requires the `--yes` flag; without it, the command prints a preview of what it would remove.

  ```
  vaultspec-rag server qdrant clean --yes
  ```

A healthy `server qdrant status` reads roughly like this:

```
Managed version: 1.18.2
Executable:      ~/.vaultspec-rag/bin/qdrant/1.18.2/qdrant
Address:         http://127.0.0.1:8765
Connection:      accepting requests
Process:         running, started by vaultspec-rag
Available installs:
  1.18.2 - downloaded release (current)
```

## How to run local-only

To run the embedded on-disk store, set local-only mode. It's a single flag, available both at setup time and at service-start time, plus a matching environment variable:

- At setup: `vaultspec-rag install --local-only`. This skips the Qdrant binary download and persists the choice, so a later `server start` honors it without re-passing the flag.
- At service start: `vaultspec-rag server start --local-only`. This skips the binary and selects the on-disk store for that run.
- By environment variable: set `VAULTSPEC_RAG_LOCAL_ONLY=1`.

What changes is the backend: the embedded on-disk store is used instead of the supervised server. For a lighter, server-free install, choose local-only. See the [installation guide](installation.md) and the [service mode guide](service-mode.md).

## How projects stay isolated on one server

One shared server safely holds many projects' indexes without collision. vaultspec-rag namespaces each project's collections by a per-root prefix - a short hash derived from the project's resolved path - so two projects pointed at the same server never overwrite each other's data. This namespacing applies only in server mode; the on-disk store is per-project by location.

For running several projects against one service, see the multi-project section of the [service mode guide](service-mode.md).

## Troubleshooting

**The server can't start.** When server mode is selected but the managed binary is missing, `server start` fails loudly instead of falling back silently. It names both the fix and the escape hatch:

```
Qdrant server mode needs the managed Qdrant server, which is not installed.
Run: vaultspec-rag server qdrant install
(or re-run with --qdrant-auto-provision to consent to the download)
Local-only option: vaultspec-rag server start --local-only
```

Run `vaultspec-rag server qdrant install` to provision the binary, or `vaultspec-rag server start --local-only` to switch to the on-disk store.

**A checksum mismatch.** If a downloaded binary fails verification, vaultspec-rag deletes the partial download and stops with a mismatch error. Re-run `vaultspec-rag server qdrant install` to download a fresh copy. If it keeps failing, check that you can reach the download host without a proxy rewriting responses.

**Confirm which backend is active.** Run `vaultspec-rag server doctor`. It reports the active backend (`server` or `local-only`), whether the service is ready for requests, and the readiness of each dependency.

## Where to go next

- [Installation guide](installation.md) - run `install` and provision dependencies.
- [Service mode guide](service-mode.md) - start, stop, and run multiple projects against the service.
- [CLI reference](cli.md) - every command and flag.
- [Configuration reference](configuration.md) - the full environment-variable inventory.
- [Getting started](getting-started.md) - a first end-to-end walkthrough.
- [Architecture overview](architecture.md) - how the pieces fit together.

Need help? See [Support and help](../README.md#support-and-help).

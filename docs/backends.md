# Storage backends

vaultspec-rag stores its search index in one of two backends: **the managed server**, a supervised local Qdrant process, or **the local-only store**, an embedded on-disk database. The managed server is the default.

This page assumes vaultspec-rag is already installed. If it isn't, start with the [installation guide](installation.md).

The how-to sections stay thin on purpose. For the full flag list on any command, see the [CLI reference](cli.md). For the vocabulary, see the [glossary](glossary.md).

## The two backends in brief

**The managed server** is a supervised local process. vaultspec-rag downloads a pinned Qdrant binary, verifies it, runs it bound to loopback, and monitors it for the life of the search service. It handles its own concurrency, so many searches and index jobs can run at once.

**The local-only store** is an embedded on-disk Qdrant database. No separate process runs; the search service reads and writes the index files directly. It lives inside your project at `.vault/data/search-data/qdrant/`. Nothing to download, nothing to supervise.

|                        | Managed server                                   | Local-only store                                  |
| ---------------------- | ------------------------------------------------ | ------------------------------------------------- |
| Separate process       | Yes, supervised                                  | No                                                |
| Binary download        | Yes, pinned and checksummed                      | None                                              |
| Index location         | `~/.vaultspec-rag/qdrant-server/storage`, shared | `.vault/data/search-data/qdrant/`, in the project |
| Concurrent load        | Handled in parallel                              | Serialized through one process                    |
| Project isolation      | Namespaced per project inside one store          | Separate by location                              |
| Needs network at setup | Yes                                              | No                                                |
| GPU and models         | Required                                         | Required                                          |

## Why the managed server is the default

The local-only store serializes work through a single process. Concurrent load means several searches arriving together, or a search competing with an index job. Under that load, requests queue behind one another and throughput drops. The managed server removes that limit: it accepts many requests at once.

"Managed and supervised" means vaultspec-rag does the operational work. It downloads the binary, runs it as a child process, monitors its health, restarts it once if the process exits unexpectedly, and shuts it down cleanly when the service stops. You never install or start Qdrant by hand.

A **pinned binary** is a specific version whose contents are known ahead of time. vaultspec-rag targets one exact Qdrant version per release, not "whatever is latest"; `server qdrant status` reports which. A **checksum** is a fingerprint of the binary's contents, compared against a known-good value before the binary runs, so a tampered or corrupted download is refused.

## When to choose the local-only store instead

The local-only store is a first-class choice, not a degraded mode. Pick it when:

- You're on a CUDA-capable continuous integration worker, where a per-run binary download is wasteful.
- You're on an air-gapped machine with a pre-provisioned GPU runtime and model cache that cannot reach the download host.
- Your use is single-user or low-concurrency, so the server's parallelism adds little.
- Your environment forbids downloading and running an external binary.

The trade-off you accept is lower throughput under concurrent load. For one developer searching occasionally, that is usually invisible.

It changes the storage backend and nothing else. It does not remove the GPU or model requirements. A GPU-less continuous integration host can install the bare package for control-plane commands, but indexing and searching locally still need CUDA or Apple silicon.

## How projects stay isolated on one server

One managed server safely holds many projects' indexes. vaultspec-rag namespaces each project's collections by a per-root prefix, a short hash of the project's resolved path. Two projects pointed at the same server never overwrite each other's data.

This namespacing applies to the managed server only. The local-only store separates projects by location, because each one lives inside its own project directory.

## How to operate the managed server

Four commands under `server qdrant` manage it.

**Provision or upgrade the binary.** `server qdrant install` downloads and verifies the pinned Qdrant server, then registers it as the current install. Use it to provision outside of `install`, or pass `--upgrade` to move to a newer pinned version.

**Check it.** `server qdrant status` reports the managed version, the executable path, the address, and whether the process is running:

```
Qdrant storage service
Managed version: 1.19.0
Executable: ~/.vaultspec-rag/bin/qdrant/1.19.0/qdrant
Address: http://127.0.0.1:8765
Connection: accepting requests
Process: running, started by vaultspec-rag
```

The version and paths reflect the release you have installed.

**Remove installs.** `server qdrant clean` deletes managed Qdrant installs. Deletion requires `--yes`; without it the command prints a preview. Pass `--keep-current` to preserve the pinned version in use. It never touches index data.

**Recover from a corrupt collection.** `server qdrant quarantine` moves a corrupt collection aside so the server can start again. Run it with no argument to list the collections in the store, then name one to quarantine it, which requires `--yes`. Nothing is deleted: the quarantined collection re-indexes the next time it is used.

## How to run the local-only store

Three ways to select it:

- At setup: `vaultspec-rag install --local-only`. This skips the Qdrant binary download and persists the choice, so a later `server start` honors it without the flag.
- For one run: `vaultspec-rag server start --local-only`.
- By environment: set `VAULTSPEC_RAG_LOCAL_ONLY=1`.

Only the backend changes. vaultspec-rag reads and writes the on-disk store instead of talking to a managed server.

### Confirming which backend is active

`vaultspec-rag server doctor` reports the active backend as `server` or `local-only`. Check there when a machine has been configured more than once and you're not sure which selection won.

### Switching back to the managed server

Running `vaultspec-rag install` again without `--local-only` persists the server selection, reversing the setup-time choice. For a single run, `server start` without the flag and with `VAULTSPEC_RAG_LOCAL_ONLY` unset uses the managed server: a command-line flag and an environment variable both outrank the persisted marker.

Switching the selection does not move your index. To carry an existing index across, migrate it:

```bash
vaultspec-rag server storage migrate <project-root> --to server
```

Pass `--to local` for the other direction, `--dry-run` to preview without copying, and `--yes` to apply. See [storage maintenance](storage-maintenance.md).

## How provisioning and verification work

During setup, vaultspec-rag downloads the pinned Qdrant binary over HTTPS from an allowlist of hosts. It computes the SHA256 checksum of the archive and compares it to a checksum built into the tool. If they don't match, it deletes the partial download and refuses to continue.

vaultspec-rag extracts only a verified binary, and re-checks it against its recorded fingerprint immediately before running it. It stores the verified binary under `~/.vaultspec-rag/bin/qdrant/`.

For air-gapped machines you supply your own binary instead of downloading one. The operator-supplied binary still flows through the same supervised path, and a checksum mismatch is still a hard failure.

Provisioning happens as part of `install`. For the setup command and its flags, see the [installation guide](installation.md).

## Troubleshooting

### The server can't start

Run `server qdrant status` to see whether the binary is present and what the connection reports. If a collection is corrupt, `server qdrant quarantine` moves it aside so the server starts again. To run without the server while you investigate, `server start --local-only`.

### A checksum mismatch

The archive didn't match the digest built into the tool, and vaultspec-rag deleted the partial download. Retry: the usual cause is a truncated transfer. If it persists, provision your own binary with `server qdrant install --binary PATH`.

### You're not sure which backend is active

`server doctor` reports the active backend. See [Confirming which backend is active](#confirming-which-backend-is-active).

## Where to go next

- [Installation](installation.md) answers how to provision either backend at setup.
- [Service mode](service-mode.md) answers how the background service runs and is managed.
- [Storage maintenance](storage-maintenance.md) answers how to survey, migrate, and reclaim index storage.
- [Architecture](architecture.md) answers how the backends fit with the models and the index.
- [CLI reference](cli.md) catalogues every command and flag.
- For help, the [issue tracker](https://github.com/nevenincs/vaultspec-rag/issues) takes questions as well as bug reports.

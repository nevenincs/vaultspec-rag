# Storage backends

Examples use the installed-tool form and call `vaultspec-rag` directly. If
vaultspec-rag is a project dependency, prefix each command with `uv run`; see
the [installation guide](installation.md) for lane selection, including the
standalone tool and no-install routes.

## Choose a backend

vaultspec-rag uses a managed local Qdrant server by default. Choose local-only storage if you cannot run a separate Qdrant process.

|                        | Managed Qdrant (default)                 | Local-only                        |
| ---------------------- | ---------------------------------------- | --------------------------------- |
| Process                | Separate, supervised Qdrant process      | Embedded store                    |
| Default store location | `~/.vaultspec-rag/qdrant-server/storage` | `.vault/data/search-data/qdrant/` |
| Qdrant binary          | Pinned and checksum-verified             | No binary download                |

Managed storage separates projects by namespaces based on each project's resolved root. Local-only storage keeps the index inside each project. The project's data directory is `.vault/data/search-data/`, and the local store sits in its `qdrant/` subfolder.

Both backends need the [GPU runtime and models](installation.md). Local-only storage avoids the Qdrant binary download; packages and models still need downloading if they are not cached.

### Access to the managed server

The managed server listens on loopback, which every account on the machine can reach, so it requires an API key on both its HTTP and gRPC ports. The service generates a new key each time it starts the server and writes it to `credential.json` beside the storage directory (`~/.vaultspec-rag/qdrant-server/credential.json` by default), readable only by your account. vaultspec-rag reads it from there; nothing needs configuring.

To query the managed server yourself, send that key in the `api-key` header. Liveness and version routes answer without it; everything that reads or changes collections is refused. If you set `VAULTSPEC_RAG_QDRANT_API_KEY`, the managed server uses your key instead of generating one.

A service upgraded in place does not attach to a managed server that an older version started without a key. Run `vaultspec-rag server stop`, then start the service again.

## Change the backend

Switching backends does not transfer indexes. To keep an existing index, follow [index migration](storage-maintenance.md#migrate-a-root-between-backends). Otherwise, build an index after switching.

If the service is running, stop it first. This interrupts all connected clients. Starting an already-running service does not change its backend.

```sh
vaultspec-rag server stop
```

Wait for the stop to succeed, then choose one of the following starts.

<p id="how-to-run-the-local-only-store"></p>

### Use a local-only index

```sh
vaultspec-rag server start --local-only
```

Include `--local-only` on every start. A plain `server start` overrides a saved or environment-based local-only selection, including one saved by `install --local-only`.

<p id="switching-back-to-the-managed-server"></p>

### Use managed Qdrant

```sh
vaultspec-rag server start --qdrant
```

The explicit flag re-enables managed Qdrant if it was disabled. If the binary is missing, follow the install command printed by startup. See [startup options](cli.md#server-start) for automatic provisioning.

After either start, [build or refresh the project's index](search-and-index.md#build-and-refresh-the-index).

<p id="confirming-which-backend-is-active"></p>

## Check the service

```sh
vaultspec-rag server status
```

Check that the service is running. For managed Qdrant, also check its process and connection:

```sh
vaultspec-rag server qdrant status
```

`server doctor` assesses the invoking process's backend configuration alongside service health. It prints one `Backend: server` or `Backend: local-only` line, which describes that configuration and does not prove which backend the running daemon uses.

For startup failures, follow [service troubleshooting](service-mode.md#troubleshooting). For collection recovery or disk cleanup, use [storage maintenance](storage-maintenance.md).

# Storage backends

## Choose a backend

vaultspec-rag uses a managed local Qdrant server by default. Choose local-only storage if you cannot run a separate Qdrant process.

|                        | Managed Qdrant (default)                 | Local-only                        |
| ---------------------- | ---------------------------------------- | --------------------------------- |
| Process                | Separate, supervised Qdrant process      | Embedded store                    |
| Default index location | `~/.vaultspec-rag/qdrant-server/storage` | `.vault/data/search-data/qdrant/` |
| Qdrant binary          | Pinned and checksum-verified             | No binary download                |

Managed storage separates projects by namespaces based on each project's resolved root. Local-only storage keeps the index inside each project.

Both backends need the [GPU runtime and models](installation.md). Local-only storage avoids the Qdrant binary download; packages and models still need downloading if they are not cached.

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

`server doctor` assesses the invoking process's backend configuration alongside service health; its backend label does not prove which backend the running daemon uses.

For startup failures, follow [service troubleshooting](service-mode.md#troubleshooting). For collection recovery or disk cleanup, use [storage maintenance](storage-maintenance.md).

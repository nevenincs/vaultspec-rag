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

### Where the managed server binary comes from

The managed server is one pinned Qdrant release. `install` downloads it, and a host `server start` downloads it when none is installed. The archive is checked against a digest committed with this release before it is unpacked, and the executable against a second committed digest before it replaces an install and again before every launch, restarts included. An install that fails the check never runs; `vaultspec-rag server qdrant install --upgrade` replaces it.

To run your own executable instead, name it and vouch for it: set `VAULTSPEC_RAG_QDRANT_BINARY` to its absolute path and `VAULTSPEC_RAG_QDRANT_BINARY_SHA256` to the SHA256 of that file. The two are only accepted together, and the file is checked against the digest before every launch. A `qdrant` on `PATH` or in the working directory is never used. The digest committed with this release does not cover an operator-supplied executable, so `server start` announces it and `server qdrant status` labels it `operator-supplied`. A host with no route to the release source installs the managed server from a local copy of the official archive with `vaultspec-rag server qdrant install --archive <file>`. The [installation guide](installation.md#a-qdrant-on-path-is-no-longer-used) covers the operator settings, and [managed server provisioning](configuration.md#managed-server-provisioning) covers mirrors and the switch that stops `server start` from downloading.

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

The explicit flag re-enables managed Qdrant if it was disabled. If the binary is missing, the start downloads and verifies it first. With the download switched off (`--no-qdrant-auto-provision` or `VAULTSPEC_RAG_QDRANT_AUTO_PROVISION=0`), the start prints the install command instead. See [startup options](cli.md#server-start).

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

The `Source` line says where the executable came from, and a `Detail` line appears when a start would refuse that executable, naming the fix. The same source words appear in `--json` output, in `server doctor`, and in the running service's own report:

| Source        | Meaning                                                                                             | Held to                                                        |
| ------------- | --------------------------------------------------------------------------------------------------- | -------------------------------------------------------------- |
| `provisioned` | The managed install, downloaded as the pinned release                                               | The digest committed with this release                         |
| `env`         | The executable named by `VAULTSPEC_RAG_QDRANT_BINARY`                                               | The digest you declare in `VAULTSPEC_RAG_QDRANT_BINARY_SHA256` |
| `attached`    | Reported by a running service only: it joined a managed server that was already up and spawned none | Not applicable                                                 |

`server qdrant status` prints the first as `managed download (provisioned)` and marks the second `operator-supplied`. `server doctor` also reports `absent` when nothing resolves, and `invalid` when the two operator settings do not name a usable binary: only one of them is set, the path is not an absolute path to a regular file, or the file does not match the declared digest. A start refuses that rather than falling back to the managed install. See [supplying your own server binary](configuration.md#supplying-your-own-server-binary).

`server doctor` assesses the invoking process's backend configuration alongside service health. It prints one `Backend: server` or `Backend: local-only` line, which describes that configuration and does not prove which backend the running daemon uses.

For startup failures, follow [service troubleshooting](service-mode.md#troubleshooting). For collection recovery or disk cleanup, use [storage maintenance](storage-maintenance.md).

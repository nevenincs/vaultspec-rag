# Provisioning: what is downloaded and how it is checked

Examples use the installed-tool form and call `vaultspec-rag` directly. If
vaultspec-rag is a project dependency, prefix each command with `uv run`; see
the [installation guide](installation.md) for lane selection, including the
standalone tool and no-install routes.

A host installation needs two things that do not come with the Python package: the
model files and, for the default backend, a Qdrant server executable. vaultspec-rag
fetches both for you. This page is the one place that says what is fetched, from where,
how it is checked, where it is kept, which commands do it, and how to run without a
network. Settings are listed in the [configuration reference](configuration.md); this
page links to them rather than repeating their syntax.

## On this page

- [What is fetched](#what-is-fetched)
- [Which commands provision](#which-commands-provision)
- [A client installation provisions nothing](#a-client-installation-provisions-nothing)
- [The Qdrant server](#the-qdrant-server)
- [The model files](#the-model-files)
- [Change where downloads come from](#change-where-downloads-come-from)
- [Run without a network](#run-without-a-network)
- [How long a fetch can take](#how-long-a-fetch-can-take)
- [When provisioning fails](#when-provisioning-fails)

## What is fetched

| What                           | Default source                                       | Checked against                                             | Kept in                                  |
| ------------------------------ | ---------------------------------------------------- | ----------------------------------------------------------- | ---------------------------------------- |
| Qdrant server executable       | `https://github.com/qdrant/qdrant/releases/download` | Two SHA256 digests compiled into vaultspec-rag              | `~/.vaultspec-rag/bin/qdrant/<version>/` |
| Dense, sparse, reranker models | `https://huggingface.co`                             | A SHA256 digest for every file, compiled into vaultspec-rag | The Hugging Face cache, under `HF_HOME`  |

vaultspec-rag does not download PyTorch. `vaultspec-rag install` writes the CUDA wheel
index into your `pyproject.toml`, and `uv` downloads the build from it; see
[download sources](configuration.md#download-sources) and
[pin the GPU build](installation.md#pin-the-gpu-build).

Nothing else is fetched at run time. Indexing, searching, the status commands and the
MCP server make no download of their own.

## Which commands provision

Four commands fetch, all through one implementation, so they report the same progress
and the same failures.

| Command                               | Fetches                                     | Skip or switch off with                                                                          |
| ------------------------------------- | ------------------------------------------- | ------------------------------------------------------------------------------------------------ |
| `vaultspec-rag install`               | Missing model files, then the Qdrant server | `--skip-models`, `--skip-qdrant`, `--local-only` (no server), `--no-provision` (neither)         |
| `vaultspec-rag server start`          | Missing model files, then the Qdrant server | `--no-qdrant-auto-provision` or `VAULTSPEC_RAG_QDRANT_AUTO_PROVISION=0` (server), `--local-only` |
| `vaultspec-rag server warmup`         | Missing model files                         | Hub offline mode                                                                                 |
| `vaultspec-rag server qdrant install` | The Qdrant server                           | `--archive <file>` installs from a local copy instead of downloading                             |

Every one of them is safe to run again. A model repository already in the cache and a
server install that still passes its check cost no download.

`install --dry-run` and `server qdrant install --dry-run` preview what would be
fetched. They make no request and write nothing.

### What `server start` does first

Starting the service is the consent to fetch what it needs. On a host installation
`server start` works in this order and stops at the first step that fails, before any
service process exists:

1. It looks for a service that is already running, and reports that one if it finds it.
1. It judges the environment that would run the service. A client installation is
   refused, and so is a host whose PyTorch build cannot use a GPU. Nothing has been
   fetched or written by this point.
1. It checks that the port is free and that no other service owns this machine.
1. It fetches any model files that are missing, and checks the ones that are there.
1. It checks the Qdrant server that would run, and downloads the pinned release if
   none is installed.

Then it starts the service. The service itself downloads nothing: it checks the
Qdrant executable again before every launch, and loads models from the cache only.

A failed step exits `1`. With `--json` the one document carries an `error` code from the
[failure table](#when-provisioning-fails) and the step's detail.

### Exit codes and interrupts

`install` exits `1` with status `failed` when a provisioning step failed; the report
still lists every step. `server warmup` exits `1` when a model could not be fetched.
`server qdrant install` exits `1` when the install failed. All three exit `0` when
there was nothing to do. `server start`, `server warmup` and `server qdrant install`
take `--json` and then write exactly one document, on every way they can end.

Pressing Ctrl+C during a fetch ends the command with one outcome, like any other
failure, and exit `1`. `server start` reports `start_interrupted` and says that no
service was started. `server warmup` and `server qdrant install` report `interrupted`.
Files that finished downloading are kept, nothing half-installed is left behind, and
the outcome names the command that continues. One limit applies: while the Qdrant
download is waiting on a source that has gone silent, the interrupt is acted on when
that wait ends, which takes at most 30 seconds.

## A client installation provisions nothing

A client installation sends requests to a service that a host installation runs. It
loads no model and runs no server, so it has nothing to fetch, and no command makes it
fetch anything:

- `install` reports each provisioning step as skipped.
- `server warmup` and `server qdrant install` report that they are not needed and exit
  `0`. `--archive` changes nothing: the file is not read.
- `server start` is refused before it looks at a model or an executable.

The [installation guide](installation.md#choose-an-installation) explains the two
roles.

### A host that cannot run the service yet

A host installation whose PyTorch build cannot use a GPU cannot run the service, so
nothing is fetched for it either. This is the ordinary state of a project straight
after `vaultspec-rag install` has written the PyTorch configuration and before
`uv sync` has applied it.

- `install`, `server warmup` and `server qdrant install` report the model files and the
  Qdrant server as skipped, say why, and say that `server start` fetches them once the
  environment is ready. They exit `0`.
- `server start` is refused with the reason and the repair.
- `server doctor` reports what is missing truthfully, and does not send you to a
  command that would skip.

`install --local-only` is still recorded for such a host, so the `server start` that
follows the sync does not download a server you declined.

## The Qdrant server

### What is installed

One release of the Qdrant server is pinned in each vaultspec-rag release.
`vaultspec-rag server qdrant status` prints it as `Managed version`. The release asset
depends on the platform:

| Platform             | Release asset                              |
| -------------------- | ------------------------------------------ |
| Windows x64          | `qdrant-x86_64-pc-windows-msvc.zip`        |
| macOS, Apple silicon | `qdrant-aarch64-apple-darwin.tar.gz`       |
| macOS, Intel         | `qdrant-x86_64-apple-darwin.tar.gz`        |
| Linux x64            | `qdrant-x86_64-unknown-linux-musl.tar.gz`  |
| Linux arm64          | `qdrant-aarch64-unknown-linux-musl.tar.gz` |

Both Linux builds are static musl builds and do not depend on the host's C library. A
platform that is not in the table has no managed server: the install fails with a
message that says so, and you [supply your own executable](#use-your-own-executable).

The archive is fetched from `{base}/v{version}/{asset}`, where the base is
`https://github.com/qdrant/qdrant/releases/download` unless you
[set a mirror](#change-where-downloads-come-from).

### How it is checked

Two SHA256 digests for each asset are compiled into vaultspec-rag: one for the archive
and one for the executable inside it. No setting, file or mirror can change them. A
mirror changes where the bytes come from and never which bytes are accepted.

1. The archive is hashed and compared before anything is extracted from it.
1. Only the one executable is taken from the archive. Paths stored in the archive are
   ignored.
1. The extracted executable is hashed and compared before it replaces an install.
1. The installed executable is hashed and compared again before every launch: a start,
   a restart, and a retry.

A mismatch at any step is a failure. Nothing is installed from an archive that failed,
and a previous install is left as it was.

The manifest written beside the executable records what was installed. It is never
what a check trusts: the expected digest always comes from vaultspec-rag itself.

`server qdrant status` and `server doctor` run the same check a launch runs, so they
do not report an install as usable when a start would refuse it. In the readiness
report a check that cannot finish in 10 seconds is reported as
`qdrant_binary_unchecked`, and the install is not reported ready.

**Between the check and the launch.** On Windows the file is held so that nothing can
change it between the check and the launch. On Linux the server is started from the
file that was hashed, whatever its path names by then; a rewrite of that same file in
place in that instant is detected by a second hash after the launch, not prevented. On
macOS the path is confirmed and the file hashed again after the launch; a replacement
that is put back before that second look is not seen.

One consequence on Linux: the managed server is started from the open file, so process
listings show it under a number instead of the name `qdrant`. Find it with
`vaultspec-rag server qdrant status`, which prints its process ID, or with
`pgrep -f bin/qdrant`.

### Where it is kept

The executable and its manifest are in `bin/qdrant/<version>/` under the service
directory, which is `~/.vaultspec-rag` unless `--status-dir` or
`VAULTSPEC_RAG_STATUS_DIR` moves it. A lock file, `bin/qdrant/provision.lock`, makes
sure only one command installs at a time. A second command run meanwhile says which
process it is waiting for, then finds the install present and downloads nothing.

`vaultspec-rag server qdrant clean --yes` deletes the installed servers. It deletes
executables only. Index data is kept elsewhere and is not touched. The next
`server start` downloads the server again.

### Replace an install that fails its check

An install whose executable no longer matches is refused at start with
`qdrant_binary_unverified`. `server qdrant install` does not overwrite it unasked,
because something changed that file and you may want to look first. Replace it with:

```bash
vaultspec-rag server qdrant install --upgrade
```

`--upgrade` leaves an install that passes its check alone. On Windows, stop the service
first: a running server holds its executable, and the install says so.

### Use your own executable

To run a Qdrant server you built or obtained yourself, name it with two environment
variables, set together:

- `VAULTSPEC_RAG_QDRANT_BINARY` is the absolute path of the executable. It must be a
  regular file, not a symbolic link.
- `VAULTSPEC_RAG_QDRANT_BINARY_SHA256` is the SHA256 of that file. Print it with
  `Get-FileHash -Algorithm SHA256 <path>` on Windows, or `sha256sum <path>` or
  `shasum -a 256 <path>` elsewhere.

The file is hashed and compared with your digest before every launch, exactly as the
managed install is compared with the compiled-in one. Your executable is never copied,
and while both variables are set `install` and `server start` download no server: a
file that fails the check stops the command and is never replaced by the pinned
release. `server start` announces the server as operator-supplied, and
`server qdrant status` shows its source as `operator-supplied (env)`.

Both variables are read from the process environment only. See
[supplying your own server binary](configuration.md#supplying-your-own-server-binary).

A `qdrant` executable on `PATH` or in the working directory is never used.

## The model files

### What is fetched

Search uses up to three public models. Each is a repository on the Hugging Face Hub,
and its files are downloaded into the Hugging Face cache.

| Model    | Default repository                         | Fetched                                 |
| -------- | ------------------------------------------ | --------------------------------------- |
| Dense    | `Qwen/Qwen3-Embedding-0.6B`                | Always                                  |
| Sparse   | `Linkup-Platform/linkup-sparseup-embed-v1` | Unless `VAULTSPEC_RAG_SPARSE_ENABLED=0` |
| Reranker | `BAAI/bge-reranker-v2-m3`                  | Always, whether or not reranking is on  |

No account or token is needed. [Model selection](configuration.md#model-selection)
lists the settings that name other repositories.

### How they are checked

Each default model is pinned to one commit of its repository, and vaultspec-rag carries
the SHA256 of every file of that commit. No setting, file or mirror can change those
digests. A mirror changes where the bytes come from and never which bytes are accepted.

1. A fetch ends with the check. Every file of the snapshot is hashed and compared, and
   a repository is reported as downloaded only when all of them match.
1. A cached file that fails is downloaded again once. A repository that still fails is
   a failure, `models_unverified`, that names the file.
1. A file in the snapshot that the pinned commit does not have is a failure too. It is
   never deleted for you: the message gives its path.
1. Every load begins with the same check. A model is never built from a snapshot that
   did not pass.

Weights are loaded from the `safetensors` format only. A model that ships its weights
only as a pickle file is refused, because a pickle file is code from whatever endpoint
served it.

The sparse model builds itself from a source file in its own repository. vaultspec-rag
does not ask the model library to import it. It reads that file once, compares it with
its committed digest, and runs the bytes it compared, so what runs is what was checked.

**A model you name yourself is unpinned.** Setting a model to another repository, or a
default model to another commit, leaves vaultspec-rag with no digests for it. It is
checked for its files and for `safetensors` weights, loaded without running any code
from its repository, and named as `unpinned` by `install`, `server warmup`,
`server doctor` and the readiness report. The dense and reranker commits are settings;
the sparse model has none, because a commit you could change would select code that
has no committed digest. See [model selection](configuration.md#model-selection).

**Between the check and the load.** On Windows every file of the snapshot is held open
from before it is hashed until the model has loaded, so nothing can change one in
between, and a file added to the directory meanwhile discards the load. Elsewhere a
process that can write the model cache could replace a file between the hash and the
library's own read of it. Because weights are `safetensors` and the one executed source
file is the bytes that were hashed, that window can yield wrong numbers, not run code.

`vaultspec-rag server doctor` runs the full check without starting the service. It reads
several gigabytes and takes a few seconds.

### How they are fetched

Each repository that is missing is downloaded by a separate download process, one
repository at a time. The command you ran makes no request to the hub itself; it starts
that process, watches what it reports, and can always stop it.

1. The download process asks the hub how large the repository is.
1. The command compares that size with the free space in the cache, less the files of
   that repository the cache already holds. A download that cannot fit is refused
   before its first byte, with the shortfall.
1. The files are downloaded. A file that finished is kept. A file that was interrupted
   is removed and fetched whole next time; nothing is resumed part-way.

Only one command fetches into a cache at a time. A second one says which process it is
waiting for, then looks at the cache again and downloads only what is still missing.

### Loading never downloads

The service does not download a model when it loads one. It reads the
cache, checks the files, and stops with one message when a model is absent or fails
its check. The message names the model and the command that repairs it:
`vaultspec-rag server warmup` fetches what is missing, and `vaultspec-rag server doctor`
confirms the cache passes. The fetch that `server start` runs before it starts the
service is the only download on that path.

### Where they are kept

In the Hugging Face cache: the `hub` directory under `HF_HOME`, which defaults to
`~/.cache/huggingface`. Set `HF_HOME` before the first download to keep the models
somewhere else. See [Hugging Face cache](configuration.md#hugging-face-cache).

## Change where downloads come from

| Download      | Setting                                                                        | Reference                                                                   |
| ------------- | ------------------------------------------------------------------------------ | --------------------------------------------------------------------------- |
| Qdrant server | `VAULTSPEC_RAG_QDRANT_RELEASE_BASE_URL`, `VAULTSPEC_RAG_QDRANT_DOWNLOAD_HOSTS` | [Managed server provisioning](configuration.md#managed-server-provisioning) |
| Model files   | `VAULTSPEC_RAG_HF_ENDPOINT`                                                    | [Model download source](configuration.md#model-download-source)             |

Both sources must be `https`. The Qdrant download follows a redirect only to `https`
and only to a host on the allowed list. A mirror that redirects to its own storage
host needs that host listed.

**A mirror with a private certificate authority.** Certificate verification is never
skipped. For the Qdrant download, add the authority to the system trust store or name
its bundle in `SSL_CERT_FILE`. For the model hub, set `SSL_CERT_FILE` to a PEM bundle
that includes the authority, or `SSL_CERT_DIR` to a directory of such certificates.

## Run without a network

### The Qdrant server from a local file

On a host that cannot reach a release source, install the server from a copy of the
official release archive:

1. On a machine with network access, download the asset for the target platform from
   the table under [what is installed](#what-is-installed). `server qdrant install --dry-run` on the target host prints the exact asset name, version and digest.
1. Copy the file to the host. Its name does not matter; it is identified by its digest.
1. Install from it:

```bash
vaultspec-rag server qdrant install --archive <file>
```

The file goes through the same archive and executable checks as a download. No request
is made, and the file is read where it lies: it is not copied, moved or removed. Keep
it outside `~/.vaultspec-rag/bin/qdrant`. The report names the source it used. Add
`--upgrade` to replace an install that fails its check.

### The models from a copied cache

1. On a machine with network access, run `vaultspec-rag server warmup` with the same
   model settings the offline host will use.
1. Copy the `hub` directory of that machine's Hugging Face cache into the same place
   under `HF_HOME` on the offline host.
1. Set `HF_HUB_OFFLINE=1` in the environment that runs vaultspec-rag there.

With the offline switch set, nothing is requested from the hub. A model that is
missing from the cache is then a failure, `models_offline`, that names the switch; it
is never a download attempt. `TRANSFORMERS_OFFLINE=1` has the same effect.

### No server at all

`--local-only` on `install` and `server start` selects the on-disk store, which needs
no Qdrant server. See [storage backends](backends.md).

## How long a fetch can take

No fetch waits without limit. These are the bounds, so you can tell a slow link from a
command that is stuck.

| Fetch         | Limit                                                                                                                       |
| ------------- | --------------------------------------------------------------------------------------------------------------------------- |
| Qdrant server | 15 minutes for the whole download, every retry included                                                                     |
| Qdrant server | 30 seconds with nothing arriving ends one attempt; a transient failure is tried 3 times in all                              |
| Qdrant server | A response that declares or sends more than 256 MiB is refused                                                              |
| Qdrant server | A second command waits up to 16 minutes for the first to finish installing                                                  |
| Model files   | 10 seconds with nothing arriving ends one attempt at a file; 6 attempts in a row with no data fail the file, about a minute |
| Model files   | 10 seconds for the hub to answer how large a repository is                                                                  |
| Model files   | Fewer than 1 MiB in any 10 minutes after the first byte stops the download                                                  |
| Model files   | A download that receives nothing at all is stopped after 11 minutes                                                         |
| Model files   | A command waits up to 1 hour in all for another one that is fetching into the same cache                                    |
| Model files   | 4 hours for the whole fetch, every repository and every wait included                                                       |

The first two model limits are the Hugging Face Hub client's own. Raise them with
`HF_HUB_DOWNLOAD_TIMEOUT` and `HF_HUB_ETAG_TIMEOUT` on a link that pauses for longer.
The last is a setting, `VAULTSPEC_RAG_MODEL_FETCH_DEADLINE_SECONDS`; raise it for a
link that needs longer. A fetch it stops keeps every file that finished, so running
the command again continues. The others are vaultspec-rag's and are not settings. They exist because a hub that
keeps sending a few bytes at a time never trips a read timeout. One mebibyte in ten
minutes is about 14 kbit/s, so no link anyone would wait on is caught by it. Stopping
a download adds at most about 11 seconds: the progress is looked at every half second,
and the download process is given 10 seconds to be confirmed gone.

A refusal that asking again will not change is not retried: a missing file, a
certificate that does not verify, a redirect off the allowed hosts, a digest mismatch.

Both fetches check free space before the first byte and fail with the shortfall when
the volume cannot hold the download.

## When provisioning fails

Each failure ends the command with one outcome that names the cause and what to do.
`server start --json` reports the code as `error`; `install --json` reports it as the
step's `code`.

### Model files

| What happened                                                                        | Code                           | What to do                                                                                                                                                                        |
| ------------------------------------------------------------------------------------ | ------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| A model is missing and the hub is in offline mode                                    | `models_offline`               | Unset `HF_HUB_OFFLINE` and `TRANSFORMERS_OFFLINE` and run `vaultspec-rag server warmup`, or copy a cache                                                                          |
| The hub cannot be reached, or stopped answering                                      | `models_fetch_failed`          | Check network access to the hub; raise `HF_HUB_DOWNLOAD_TIMEOUT` on a link that pauses                                                                                            |
| The hub has no such repository or revision                                           | `models_not_found`             | Correct the model setting that names it                                                                                                                                           |
| The cache volume cannot hold the download                                            | `models_no_space`              | Free space on that volume, or set `HF_HOME` to a larger one                                                                                                                       |
| The hub's certificate is not trusted                                                 | `models_untrusted_certificate` | Set `SSL_CERT_FILE` or `SSL_CERT_DIR` to include the mirror's certificate authority                                                                                               |
| Too little arrived for too long and the download was stopped                         | `models_stalled`               | Copy a complete cache and set `HF_HUB_OFFLINE=1`, or point `VAULTSPEC_RAG_HF_ENDPOINT` at a mirror                                                                                |
| The download process ended without a result                                          | `models_download_died`         | Run the command again; if it ends the same way, report the detail it printed                                                                                                      |
| Another process was still fetching after an hour                                     | `models_busy`                  | Wait for that process to finish, then run the command again                                                                                                                       |
| A snapshot fails its check: a file differs, is extra, or the weights are pickle only | `models_unverified`            | The detail names the file. Point `VAULTSPEC_RAG_HF_ENDPOINT` at a mirror that serves the official files, remove an extra file by hand, or name a model with `safetensors` weights |
| The time allowed for the whole fetch ran out                                         | `models_fetch_deadline`        | Run the command again to continue, or raise `VAULTSPEC_RAG_MODEL_FETCH_DEADLINE_SECONDS`                                                                                          |
| A file or directory of the model cache could not be used                             | `models_cache_unusable`        | Make the cache writable by the account running the command, or set `HF_HOME` to a directory that is                                                                               |
| `huggingface_hub` is not installed                                                   | `models_hub_missing`           | Reinstall vaultspec-rag                                                                                                                                                           |

When several repositories fail for different reasons the code is
`models_fetch_failed` and the detail says which repository had which. Every repository
is attempted before the command reports, so one failure does not hide the next.

### Qdrant server

| What happened                                            | Code                       | What to do                                                                              |
| -------------------------------------------------------- | -------------------------- | --------------------------------------------------------------------------------------- |
| No server is installed and downloading is switched off   | `qdrant_missing`           | Run `vaultspec-rag server qdrant install`, or start with `--qdrant-auto-provision`      |
| The install failed: see the causes below                 | `qdrant_provision_failed`  | The detail names the cause and its remedy                                               |
| The installed executable is not the pinned release       | `qdrant_binary_unverified` | `vaultspec-rag server qdrant install --upgrade`                                         |
| The executable cannot be read                            | `qdrant_binary_busy`       | Close whatever holds it, or correct its permissions, then try again                     |
| Something that is not a file is at the install's name    | `qdrant_install_invalid`   | Remove it and run `vaultspec-rag server qdrant install`                                 |
| Your own executable's settings do not name a usable file | `qdrant_binary_invalid`    | Correct `VAULTSPEC_RAG_QDRANT_BINARY`, or unset both settings to use the managed server |
| Your own executable does not match its declared digest   | `qdrant_binary_unverified` | Correct the path or the digest, or unset both                                           |

Causes of `qdrant_provision_failed`, each named in the detail with what to do:

- The source cannot be reached, is failing or rate-limiting, or is too slow for the 15
  minute limit. The detail also names the route that needs no network:
  `server qdrant install --archive <file>`.
- The source's certificate is not trusted, the file is not there, or the source
  refused the request.
- A redirect led to a host that is not allowed, or the redirects never end at the file.
- The response is larger than the 256 MiB cap, so the source is not serving the
  release asset.
- The archive or the executable inside it does not match its digest.
- The volume cannot hold the download, or filled while it was being written.
- The installed executable is in use, on Windows, because the service is running.
- A local archive given with `--archive` is not the pinned one.
- The platform has no managed server.
- Another command was still installing after 16 minutes.

The model files are fetched before the Qdrant server, so a start that cannot get its
models is not also sent to download a server it cannot use yet.

A separate failure belongs to the environment and not to any fetch: `server start`
reports `service_env_no_gpu` for a client installation and for a host whose PyTorch
build cannot use a GPU, with the reason and the repair.

### After a failure

There is nothing to clean up by hand, and running the same command again is always the
next step once the cause is fixed.

- A failed Qdrant install removes its working files. A previous install is untouched.
  Working files left by a run that was killed are removed by the next install.
- A failed model fetch keeps every file that finished and removes the one that did
  not. The next run downloads only what is missing.

## Where to go next

- [Installation guide](installation.md) - choose a host or client installation and set
  it up.
- [Configuration reference](configuration.md) - every setting named on this page.
- [Storage backends](backends.md) - the managed server and the local-only store.
- [CLI reference](cli.md) - every option of the commands above.

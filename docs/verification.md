# When search results look wrong

Search reads the index, not your working tree. When a result looks wrong, the
cause is usually one of three: the service is not healthy (`server doctor`), the
index is behind the tree (`status`), or the tree it indexed is not the tree you
meant (`index --dry-run`). Two more sections follow those: how to reindex, and
how to gate a script on the same checks.

This guide assumes an installed, provisioned workspace. If you do not have that
yet, start with the [installation guide](installation.md). For what the service
is and how it stays warm, see the [service mode guide](service-mode.md).

Output below is from a run against this repository. Your paths, counts, and
versions will differ.

## Is the service healthy?

```
vaultspec-rag server doctor
```

```
Service readiness
Backend: server
Readiness: ready for requests
Live service:
  status: running (running)
  process: pid 46220 (alive)
  network: port 8766 (listening)
  heartbeat: 13s ago
  release: 0.4.21 (matches this client)
Installed dependencies: ready
  torch: ready - CUDA available on NVIDIA GeForce RTX 4080 SUPER
  models: ready - all 3 model repos present in the cache
  qdrant: ready - qdrant binary resolves from provisioned
Provisioning (vaultspec-rag):
  declared mode: tool
  install mode: mismatch - .mcp.json launch shape disagrees with the declared mode
  version floor: ok
```

One line above reports a failure state, and that run exits `1`.

So do not gate on the word `ready`. A service can be running, reachable, on a
matching release, and still fail this check. Scan the lines rather than the
summary - but scan the state each one reports, not the words it happens to use.
Most of these lines never say `ready` or `ok` at all: `Backend: server`,
`heartbeat: 13s ago` and `declared mode: tool` are all healthy, and taking the
first line without those words would stop at the first of them. The fault is
the line whose state is a problem, and it says so with a dash and an
explanation after it. Above, that is `install mode: mismatch`.

Two common failures and their fixes. A `release: ... (INCOMPATIBLE)` line means
the running service is an older build than the client asking for it. Stop and
start it after upgrading the package:

```
vaultspec-rag server stop
vaultspec-rag server start
```

For a `Provisioning` mismatch, the [installation guide](installation.md) covers
reconciling the install with the declared mode.

## Is the index current?

```
vaultspec-rag status
```

```
Project index
Project: /path/to/your/project
Index data: running service storage
Vault documents: 5140
Source code sections: 11279
Document sections: 0
Compute: CUDA - NVIDIA GeForce RTX 4080 SUPER (16.0 GiB VRAM)
Support profile: managed-service
Index generations:
  code: generation 1, succeeded, job 54afa4d5
  document: generation 1, succeeded, job 91a74931
  vault: generation 1, succeeded, job 0ba8fb89
Server: running
Address: http://127.0.0.1:8766
Next action:
  vaultspec-rag index --type document
```

The counts and the generation lines answer different questions.

The counts describe what is stored right now. `Document sections: 0` above is
not a fault: this project routes no files through preprocessing, which is why
`Next action` offers to index that domain. A suggestion there is a suggestion,
not a diagnosis.

The generation lines describe whether your current configuration has been
indexed at all. A generation fingerprints your indexing configuration: the
profile, the routes, the ignores, and more, with code, documents, and the vault
each carrying their own. The [indexing guide](indexing.md) lists everything that
goes into one.

The combination to watch for is a non-zero count beside a generation that reads
`not indexed yet`:

```
Vault documents: 5140
Index generations:
  vault: not indexed yet
```

That means stored data from an earlier run, under a configuration that no longer
matches. Search will still return results, built from the previous
configuration.

Compare the counts against the tree, but do not expect them to match. A document
is stored as several sections, so a healthy index reports more rows than the
tree has files. This repository holds 2,396 Markdown files under `.vault/`
(`find .vault -name '*.md' | wc -l`) and indexes them to the 5,140 documents
shown above, a little over two apiece. A count well below the file count is the
warning sign: that is what a partial or abandoned run looks like, and nothing in
the tool flags the ratio for you.

## Is it indexing the right files?

Even a current index is useless if it covers the wrong tree. Ask before
indexing, not after:

```
vaultspec-rag index --type code --dry-run --dry-run-limit 5
```

`--dry-run-limit` shows 50 paths by default. Raise it, or use `--json`, which
lists every path regardless.

```
Dry run: 717 source-code files would be indexed.
Admission summary:
  - unowned/rejected/ignored: 12
  - code/rejected/source_profile_excluded: 181
  - code/admitted/source_profile: 717
Files shown:
  - conftest.py
  - src/vaultspec_rag/__init__.py
  - src/vaultspec_rag/__main__.py
  - src/vaultspec_rag/_anchor_claim.py
  - src/vaultspec_rag/_atomic_write.py
712 more files not shown. Use --dry-run-limit 717 or --json for the full list.
```

That run is this project's own source. Another page shows the same command
against a smaller repository and reports a different admitted count, which is
the point of running it: the numbers describe the tree in front of you.

The admission summary is the answer: 714 files admitted out of the 906
considered (714 admitted, 180 rejected, 12 ignored). A gap that size is not a
fault by itself, because the profile exists to keep vendored trees and build
output out of your results.

Scan the file list to confirm the profile admitted what you expected. These are
the project's own modules, which is what you want. If instead the list opens
with vendored dependencies or tooling scripts, the profile is admitting the
wrong tree, and indexing it will bury your code under things you did not write.

Fix that before you index. Narrow with `--exclude`, which takes a repeatable
gitignore-syntax pattern, or change the profile. The
[indexing guide](indexing.md) covers the profiles and how admission is decided.

## Reindexing

When `status` shows a generation that does not match your configuration:

```
vaultspec-rag index
```

Scope it with `--type vault`, `--type code`, or `--type document` when only one
kind has moved. Add `--rebuild` to delete the selected data before rebuilding
it.

The running service reindexes as files change, so a healthy setup rarely needs
this by hand. Reach for it after an upgrade, after a profile change, or when a
generation goes stale.

## Gating a script on these checks

Gate on the exit code. The top of the JSON body is not enough: `server doctor
--json` returns `ok: true` with `data.ready: true` on the run above and still
exits `1`. The mismatch that caused it is in the payload, but further down than
a health check usually looks - `data.mode.mode_mismatch` reads `mismatch` on
that run - so a script that gates on `ok` alone calls a failing workspace
healthy.

```bash
if ! vaultspec-rag server doctor --json >/dev/null 2>&1; then
  echo "service check failed; run 'vaultspec-rag server doctor' to see why" >&2
  exit 1
fi
```

For the index the exit code is not enough either, in the opposite direction:
`status` exits `0` whenever it can report, including when what it reports is an
empty or stale index. Read the counts and the generations from `status --json`
and compare them against what you expect the tree to hold. A check that only
asserts the service is running will pass against an index built last month.

[Scripting and automation](automation.md) covers the JSON envelope and the exit
codes in full.

## Related documentation

- [Storage maintenance](storage-maintenance.md) covers pruning what indexing leaves behind.
- [Search and index](search-and-index.md) covers the search and index commands in full.

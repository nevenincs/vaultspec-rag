# When search results look wrong

Search reads the stored index. Start with an [installed and provisioned
workspace](installation.md). Output examples in this guide come from this
repository. Counts and paths vary by project.

## Is the service healthy?

```bash
vaultspec-rag server doctor
```

Inspect `Live service`, `Installed dependencies`, and, when present,
`Provisioning (vaultspec-rag)`.

- For dependency faults, follow the [installation troubleshooting guide](installation.md#when-something-goes-wrong).
- For service faults, follow the [service troubleshooting guide](service-mode.md#troubleshooting).
- For provisioning faults, read the reported detail.

If none of these checks reports a problem, [check whether the index is current](#is-the-index-current).

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

The admission summary is the answer: read it off the three lines above rather
than off this sentence, because the counts move with the tree. In that run it
is 717 admitted, 181 rejected by the source profile, and 12 ignored as
unowned, which is 910 files considered. A gap that size is not a fault by
itself, because the profile exists to keep vendored trees and build output out
of your results.

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

See [scripting and automation](automation.md) for JSON output and exit-code handling.

## Related documentation

- [Storage maintenance](storage-maintenance.md) covers pruning what indexing leaves behind.
- [Search and index](search-and-index.md) covers the search and index commands in full.

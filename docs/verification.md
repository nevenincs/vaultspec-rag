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

If none of these checks reports a problem, [check index status](#check-index-status).

<a id="is-the-index-current"></a>

## Check index status

```bash
vaultspec-rag status
```

Counts describe stored sections, not source files, and don't prove the index is current.

Under `Index generations`, each domain shows its latest recorded indexing job
for this project. `not indexed yet` means no matching job was found in the
retained history; it doesn't establish that the store is empty. `succeeded`
records that job's success, not whether the index matches your current files.

To index the domains you need, follow [reindexing](#reindexing). If expected
files are missing, [check file coverage](#is-it-indexing-the-right-files).

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

To update the index after changing files or indexing settings:

```
vaultspec-rag index
```

Scope it with `--type vault`, `--type code`, or `--type document` when only one
kind has changed. To delete and rebuild a domain, pass both `--type` and `--rebuild`.

The running service reindexes as files change. See [watcher operation](automation.md#automatic-re-indexing)
for automatic updates.

## Gating a script on these checks

See [scripting and automation](automation.md) for JSON output and exit-code handling.

## Related documentation

- [Storage maintenance](storage-maintenance.md) covers pruning what indexing leaves behind.
- [Search and index](search-and-index.md) covers the search and index commands in full.

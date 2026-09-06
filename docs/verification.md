# When search results look wrong

Search reads the stored index. Start with an [installed and provisioned
workspace](installation.md).

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

Preview which source files would be indexed without changing the index:

```bash
vaultspec-rag index --type code --dry-run
```

Check that expected files appear and unwanted files stay out. The admission
summary counts admitted and rejected files by reason.

By default, the preview displays up to 50 paths. Use `--dry-run-limit N` to
change that limit, or add `--json` for the full admitted path list.

If file selection is wrong, review the [admission rules](indexing.md#indexing-pipeline)
and [routing configuration](preprocessing-hooks.md#configure-rules). Repeat the
preview after making changes.

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

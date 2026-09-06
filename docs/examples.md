# Retrieval recipes

Use these examples with an indexed project. Replace query terms and feature tags with
your own. Commands use a standalone installation; for other routes, use the
[matching command prefix](installation.md#install-with-python).

For query wording and filters, see the [query guide](query-craft.md).

## Why was this decided?

Search decision records for the behavior you want to understand:

```bash
vaultspec-rag search "cache control on deployed assets" --type vault --doc-type adr
```

Read the matching ADRs for their rationale and scope.

## What happened on this feature?

Search one feature across document types. Replace `service-graph` with your feature tag:

```bash
vaultspec-rag search "graph rebuild race" --type vault --feature service-graph --max-results 3
```

Use the matching records to resume work or investigate a change. Search ranks passages;
it doesn't list every record for the feature.

## Where does this identifier live?

Both searches above looked at documents. Code searches take the same shape, and
a bare identifier is the easiest kind: you do not need to describe it, because
exact terms match exactly. `--scores` prints the relevance number beside each
hit:

```
vaultspec-rag search "EXIT_WARMING" --type code --max-results 4 --scores
```

```
1. src/vaultspec_rag/cli/_status_render.py:981 (score 0.8044)
2. src/vaultspec_rag/serviceclient/_status.py:41 (score 0.7332)
3. src/vaultspec_rag/tests/test_cli_server_start.py:220 (score 0.6329)
4. src/vaultspec_rag/tests/test_cli_status.py:534 (score 0.3539)
```

Code hits carry a line number. `grep -rl` over the same tree finds two files:
one defines the constant, the other consumes it. Search ranked those two first
and then offered the tests that exercise them.

## Why are test files crowding out the code I want?

Because they legitimately match. Use `--exclude-path` when one part of the tree
outranks the part you want:

```
vaultspec-rag search "fixture that builds a fake service status file" --type code --max-results 5
```

```
src/vaultspec_rag/server/_lifecycle.py
src/vaultspec_rag/serviceclient/_discovery.py
src/vaultspec_rag/serviceclient/_discovery.py
src/vaultspec_rag/tests/test_service_version_compatibility.py
src/vaultspec_rag/tests/integration/test_service_job_control.py
```

Excluding the tests frees two slots. `_service_status.py` takes one, and the
other goes to a third passage from `_discovery.py`:

```
vaultspec-rag search "fixture that builds a fake service status file" --type code --max-results 5 --exclude-path "**/tests/**"
```

```
src/vaultspec_rag/serviceclient/_discovery.py
src/vaultspec_rag/server/_lifecycle.py
src/vaultspec_rag/cli/_service_status.py
src/vaultspec_rag/serviceclient/_discovery.py
src/vaultspec_rag/serviceclient/_discovery.py
```

One file occupies several slots in both runs. Results are passages, not files,
so a long file can answer more than once.

`--language` narrows a polyglot tree the same way. It changes nothing here,
because every indexed file in this repository is Python.

## What does the score mean?

See [inspect result scores](query-craft.md#inspect-result-scores) for interpreting
`--scores` output and its limits.

## What it answers badly

### Can it list every place something appears?

No. Search ranks; it does not enumerate.

```
vaultspec-rag search "body_hash" --type vault --max-results 100
```

That returned 24 results, where `grep -rl body_hash .vault/` matches 2,397 files.
The rows are not printed here because the count is the whole argument: asking for
a hundred did not produce a hundred, and no flag turns ranking into a complete
list.

So never answer "how many places do this?" or "have I changed every caller?"
with a search. Use `grep` or `rg`, which are exhaustive by construction. Search
tells you where to start reading, not what the full set is.

### Can it find what was never indexed?

No, and coverage is narrower than the file count suggests. Indexing this
repository considers 906 files and admits 714 of them. The other 192 are turned
away: 180 fall outside the source profile and 12 are ignored outright. Only
admitted files can answer a query, and the proportion differs per project.

When results seem unrelated to what you asked, check coverage before rewording.
[Verify the index](verification.md) has the commands.

### Can it answer two questions at once?

No. A query carrying two concepts ranks against both and matches neither well.
Asking about the reranker and the binary checksum together puts a settings file
on top, which is neither:

```
vaultspec-rag search "how the reranker scores results and how the qdrant binary is verified" --type code --max-results 4 --scores
```

```
1. src/vaultspec_rag/config/_settings.py:239 (score 0.7414)
2. src/vaultspec_rag/tests/test_provision.py:415 (score 0.3466)
3. src/vaultspec_rag/search/_searcher.py:628 (score 0.2585)
4. src/vaultspec_rag/search/_searcher.py:475 (score 0.1739)
```

Split it and both halves land on the right file, scoring far higher:

```
vaultspec-rag search "reranker scores and reorders the candidate list" --type code --max-results 1 --scores
vaultspec-rag search "verify the downloaded qdrant binary checksum" --type code --max-results 1 --scores
```

```
1. src/vaultspec_rag/search/_searcher.py:440 (score 0.9029)
1. src/vaultspec_rag/qdrant_runtime/_provision.py:313 (score 0.9856)
```

### Are the results current?

Only as current as the last successful index. Results describe that index, not
your working tree: a file saved seconds ago is not searchable until the next
index run, and a stale generation makes every answer describe an older shape of
the project.

## Related documentation

- [Verify the index](verification.md) covers health, currency, and coverage.
- [Indexing](indexing.md) covers profiles, admission, and the encoders.

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

<p id="what-it-answers-badly"></p>
<p id="can-it-list-every-place-something-appears"></p>
<p id="can-it-find-what-was-never-indexed"></p>
<p id="can-it-answer-two-questions-at-once"></p>
<p id="are-the-results-current"></p>

## Search limits

- Semantic search ranks passages. For exact occurrences, use text search and check
  which paths and ignore rules it uses.
- A low score or missing result doesn't prove absence.
  [Check file coverage](verification.md#is-it-indexing-the-right-files) to see whether
  expected files are selected for indexing.
- Unrelated questions can make matches harder to interpret.
  [Split them into separate queries](query-craft.md#name-the-nouns-and-ask-one-thing).
- Results reflect stored index data.
  [Check index status](verification.md#check-index-status) when files change; a
  successful indexing job doesn't prove the index matches the current project.

## Related documentation

- [Verify the index](verification.md) covers health, currency, and coverage.
- [Indexing](indexing.md) covers profiles, admission, and the encoders.

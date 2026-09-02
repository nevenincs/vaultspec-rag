# Retrieval recipes

Worked searches for the questions this tool answers well, and a plain account of
the ones it answers badly. Every command and every number on this page came from
a real run against this repository, whose index holds 5,140 vault documents and
11,279 code passages.

Searches return ten results by default. Raise that with `--max-results` when you
are surveying rather than looking something up. Result snippets below are
shortened, and example filenames are shown without their date prefix; the paths,
counts, and scores are as the tool reported them.

[Writing a query that finds it](query-craft.md) covers phrasing and the full
filter surface. This page covers what to reach for and when.

## Why was this decided?

Ask for the reasoning behind a behaviour, and restrict the answer to decision
records so plans and execution logs do not crowd them out:

```
vaultspec-rag search "cache control on deployed assets" --type vault --doc-type adr
```

```
1. .vault/adr/store-eviction-log-rotation-adr.md
   adr | feature: store-eviction-log-rotation | 2026-04-12
   ## Rationale

   The decision pattern is: keep the smallest amount of state under
   the smallest number of locks, reuse existing teardown paths ...
2. .vault/adr/service-graph-adr.md
   adr | feature: service-graph | 2026-04-02
   ## Rationale

   - **MCP-as-service**: zero new infrastructure. The server process already
     owns GPU resources, has thread-safe lazy init, ...
```

Each hit is a path, a metadata line naming the document type, feature, and date,
and the passage that matched. You are describing a concept rather than naming a
file. Rationale gets written in whatever words its author chose that day, which
is what makes it hard to grep for.

## What happened on this feature?

Swap `--doc-type` for `--feature` and the search stops asking why and starts
asking what:

```
vaultspec-rag search "graph rebuild race" --type vault --feature service-graph --max-results 3
```

```
1. .vault/adr/service-graph-adr.md
   adr | feature: service-graph | 2026-04-02
2. .vault/research/service-graph-research.md
   research | feature: service-graph | 2026-04-02
3. .vault/plan/service-graph-phase1-plan.md
   plan | feature: service-graph | 2026-04-02
```

The decision, the research that informed it, and the plan that carried it out.
Reach for this when you are picking up work you have not touched in a while.

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

`--scores`, used above, prints a number per hit. Rank order is only meaningful
within a single query. Absolute magnitude is coarse but usable: tenths mean the
corpus held something, thousandths mean it did not.

```
vaultspec-rag search "medieval falconry glove stitching patterns" --type code --max-results 3 --scores
```

```
1. src/vaultspec_rag/indexer/_ignore_specs.py (score 0.0066)
2. tools/citation_gate.py (score 0.0019)
3. src/vaultspec_rag/indexer/_ignore_specs.py (score 0.0009)
```

Ten rows came back for that query regardless. No threshold filters results out,
so a search never reports "nothing found". A top score in the thousandths is how
you tell.

## What it answers badly

### Can it list every place something appears?

No. Search ranks; it does not enumerate.

```
vaultspec-rag search "body_hash" --type vault --max-results 100
```

That returned 24 results. `grep -rl body_hash .vault/` matches 2,397 files.
Asking for a hundred did not produce a hundred, and no flag turns ranking into a
complete list.

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

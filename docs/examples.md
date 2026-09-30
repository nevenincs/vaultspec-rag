# Retrieval recipes

Use these examples with an indexed project. Replace query terms and feature tags with
your own. Commands use a standalone installation; for other routes, use the
[matching command prefix](installation.md#install-with-python).

For query wording and filters, see the [query guide](query-craft.md).

## Why was this decided?

Search decision records for the behavior you want to understand. The query below is an
illustration; replace it with a behavior in your own project:

```bash
vaultspec-rag search "cache control on deployed assets" --type vault --doc-type adr
```

Read the matching ADRs for their rationale and scope.

## What happened on this feature?

Search one feature across document types. Both the query and the feature tag are
illustrations; replace them with your own:

```bash
vaultspec-rag search "graph rebuild race" --type vault --feature service-graph --max-results 3
```

Use the matching records to resume work or investigate a change. Search ranks passages;
it doesn't list every record for the feature.

## Where does this identifier live?

Both searches above looked at documents. Code searches take the same shape, and
a bare identifier is the easiest kind: you do not need to describe it, because
exact terms match exactly. This is a real run against this repository:

```
vaultspec-rag search "SERVICE_PHASE_WARMING" --type code --max-results 4
```

The result lines, with each passage cut to its first lines:

```text
1. src/vaultspec_rag/serviceclient/_discovery.py:43-65
   #: after it acquires the machine lock and ``running`` when it starts serving;
   #: the CLI parent's spawn-time write carries no phase. An absent field keeps
   ...
   SERVICE_PHASE_WARMING = "warming"
   SERVICE_PHASE_RUNNING = "running"
   ...
2. src/vaultspec_rag/serviceclient/_status.py:150-169
   def lifecycle_from_signals(facts: LivenessSignals) -> ServiceLifecycle:
       ...
       if facts.phase == SERVICE_PHASE_WARMING:
           return ServiceLifecycle.STARTING
   ...
3. src/vaultspec_rag/cli/_service_start.py:781-805
   def _attach_warming_service(json_mode: bool) -> bool:
   ...
4. src/vaultspec_rag/cli/_service_start.py:1046-1066
   def _startup_phase_label(health: dict[str, object] | None) -> str:
   ...
```

Code hits carry a line range. `grep -rl SERVICE_PHASE_WARMING src --include=*.py` lists seven files, one
of them a test, and gives no order. Search put the file that defines the constant
first, then the code that reads it. `--scores` prints a relevance number beside each
hit.

## Why are test files crowding out the code I want?

Because they legitimately match. Tests are demoted by default but still returned. When
the query describes something tests are built to do, they can fill the page. Use
`--exclude-path` when one part of the tree outranks the part you want. This is a real run:

```
vaultspec-rag search "fixture that builds a fake service status file" --type code --max-results 5
```

```text
1. src/vaultspec_rag/tests/_cli_helpers.py:138-166
2. src/vaultspec_rag/tests/test_service_lifecycle_helpers.py:29-47
3. src/vaultspec_rag/tests/integration/test_service_doctor_liveness.py:45-58
4. src/vaultspec_rag/tests/test_service_lifecycle_helpers.py:70-92
5. src/vaultspec_rag/tests/test_cli_service_status.py:1226-1263
```

Excluding the tests brings the production code that reads and writes the status file
into view:

```
vaultspec-rag search "fixture that builds a fake service status file" --type code --max-results 5 --exclude-path "**/tests/**"
```

```text
1. src/vaultspec_rag/serviceclient/_discovery.py:762-794
2. src/vaultspec_rag/server/_lifecycle.py:73-104
3. src/vaultspec_rag/cli/_service_status.py:1-42
4. src/vaultspec_rag/serviceclient/_discovery.py:172-198
5. src/vaultspec_rag/serviceclient/_discovery.py:363-386
```

The inline form `exclude:tests` in the query text gives near-identical results for a
client that sends only a query string. One file can fill several slots in both runs. Results are
passages, not files, so a long file can answer more than once.

`--language` narrows a tree that holds several languages the same way.

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

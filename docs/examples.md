# Retrieval recipes

Worked searches for the questions this tool answers well, and a plain account of
the ones it doesn't. Every command and every result on this page came from a
real run against a project holding 297 vault documents and 93 admitted source
files.

For how to phrase and narrow a query, read [writing a query that finds
it](query-craft.md). This page is the shapes themselves.

## Why was this decided?

Ask for the reasoning behind a behaviour, and restrict the answer to decision
records so plans and execution logs don't crowd them out:

```
uv run vaultspec-rag search "cache control on deployed assets" --type vault --doc-type adr
```

```
1. Decision record: documentation cache policy
2. Decision record: deployment cache policy
3. Decision record: landing-page cache policy
```

This is the strongest shape in the tool. You're describing a concept rather than
naming a file, which is exactly what a project's own history is hard to grep for.

## What happened on this feature?

Swap the filter and the same words ask a different question:

```
uv run vaultspec-rag search "cache control on deployed assets" --type vault --feature docs-site
```

```
1. Plan record: documentation cache policy
2. Execution record: cache-control implementation
3. Decision record: documentation cache policy
```

A plan, the execution record that carried out the change, and the decision that
authorised it. Reach for this when you're picking up work you haven't touched
in a while.

## Where does this identifier live?

Feed a bare identifier and let the term-matching half do the work:

```
uv run vaultspec-rag search "vs_page_meta" --type vault --max-results 4 --scores
```

```
1. Plan record: page metadata extension (score 0.4369)
2. Execution record: metadata implementation (score 0.3515)
3. Execution record: metadata verification (score 0.3457)
4. Execution record: metadata publication (score 0.3383)
```

`grep -rl` over the same tree returns those four files and no others. Search
found the same set and ranked it, putting the plan that introduced the extension
above the records that merely mention it.

Note the scores. A rare token scores an order of magnitude higher than a
conceptual query does against the same corpus, where the top hit scored 0.0260.
A low top score is worth reading as a warning that nothing in the corpus matches
directly.

## Steering into the right part of the tree

Two filters do most of the day-to-day work on code. `--language` picks which
part of a polyglot project answers:

```
uv run vaultspec-rag search "detect antipatterns in the page DOM" --type code --language python
```

`--exclude-path` matters when a tree is mirrored, which quietly halves how much
you see. Before, two distinct chunks filled four result slots; after excluding
one copy, four slots carried four different pieces of code:

```
uv run vaultspec-rag search "detect antipatterns in the page DOM" --type code --exclude-path ".claude/*"
```

## What it answers badly

### Anything that has to be exhaustive

Search ranks; it doesn't enumerate. The gap is wider than it looks:

```
uv run vaultspec-rag search "body_hash" --type vault --max-results 100
```

That returned 23 results. `grep -rl body_hash` over the same tree matches 298
files. Asking for a hundred didn't produce a hundred, and no flag turns ranking
into a complete list.

So never answer "how many places do this?" or "have I changed every caller?"
with a search. Use `grep` or `rg`, which are exhaustive by construction. Search
tells you where to start reading, not what the full set is.

The default is ten results. Raise it with `--max-results` when you're surveying
rather than looking something up.

### Anything outside what was indexed

A query can only answer from admitted files. This project admits 93 source files
out of nearly a thousand considered, so a code search here reaches a small
fraction of the tree by design. When results seem unrelated to what you asked,
check coverage before rewording. [Verify the index](verification.md) has the
commands.

### Two questions at once

A query carrying two concepts ranks against both and tends to match neither well.
Split it and run both.

### Freshness

Results describe the last successful index, not the working tree. A file saved
seconds ago may not be searchable yet, and a stale generation makes every answer
describe an older shape of the project.

## Related documentation

- [Writing a query that finds it](query-craft.md) covers phrasing and the full
  filter surface.
- [Verify the index](verification.md) covers health, currency, and coverage.
- [Indexing](indexing.md) covers profiles, admission, and the encoders.

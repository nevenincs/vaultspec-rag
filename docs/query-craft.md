# Writing a query that finds the right result

Search returns the closest matches it can rank, never an exhaustive list. So when
a query finds nothing useful, the wording is rarely the cause. Usually the corpus
doesn't hold the answer, or the query asks two things at once.

This page shows you how to tell those apart, what to type, and what to change
when a result looks wrong. For how the ranking works underneath, read the
[architecture overview](architecture.md) and the
[indexing internals](indexing.md).

Examples use the `uv run` prefix, which runs the command inside a project
environment. If you installed vaultspec-rag as a standalone tool, drop the prefix
and call `vaultspec-rag` directly; see the
[installation guide](installation.md).

## Check coverage before you blame the query

An index that doesn't hold what you're looking for produces confusing results,
and no amount of rewording fixes that. Ask what's admitted:

```
uv run vaultspec-rag index --type code --dry-run --dry-run-limit 5
```

```
Dry run: 93 source-code files would be indexed.
Admission summary:
  - unowned/rejected/ignored: 12
  - code/rejected/source_profile_excluded: 865
  - code/admitted/source_profile: 93
```

Read the count, not the sample. Ninety-three files out of nearly a thousand
considered is the number to weigh against the tree you have in mind. The five
paths a dry run prints are the head of the list, not the most important files. A
sample full of vendored tool scripts doesn't mean the rest of the set is vendored
too.

If the count is far off what you expect, fix admission before you pay for a full
indexing run. [Verify the index](verification.md) covers this check and the two
that go with it, and [indexing](indexing.md) covers how admission is decided.

## Filters do more than phrasing

Filters are the sharpest tool here, because they remove candidates before
ranking rather than competing with it.

### Narrowing document results

The same query against a vault of 555 sections, narrowed two ways:

```
uv run vaultspec-rag search "cache control on deployed assets" --type vault --doc-type adr
```

```
1. Decision record: documentation cache policy
2. Decision record: deployment cache policy
3. Decision record: landing-page cache policy
```

Three decision records, which is the shape you want when you're asking why
something was decided. Ask instead for everything on one feature:

```
uv run vaultspec-rag search "cache control on deployed assets" --type vault --feature docs-site
```

```
1. Plan record: documentation cache policy
2. Execution record: cache-control implementation
3. Decision record: documentation cache policy
```

Same query, different question. One asked "what was decided", the other asked
"what happened on this feature". Neither needed better wording.

### Narrowing code results

Path filters earn their place when a tree is mirrored. Here the same file is
indexed under two roots, and every result arrives doubled:

```
uv run vaultspec-rag search "detect antipatterns in the page DOM" --type code
```

```
1. .claude/skills/impeccable/scripts/detector/detect-antipatterns-browser.js:8278
2. .agents/skills/impeccable/scripts/detector/detect-antipatterns-browser.js:8278
3. .claude/skills/impeccable/scripts/detector/detect-antipatterns-browser.js:5039
4. .agents/skills/impeccable/scripts/detector/detect-antipatterns-browser.js:5039
```

Two distinct chunks occupying four slots. Drop one copy of the tree and the same
four slots carry four different pieces of code:

```
uv run vaultspec-rag search "detect antipatterns in the page DOM" --type code --exclude-path ".claude/*"
```

```
1. .agents/skills/impeccable/scripts/detector/detect-antipatterns-browser.js:8278
2. .agents/skills/impeccable/scripts/detector/detect-antipatterns-browser.js:1
3. .agents/skills/impeccable/scripts/detector/detect-antipatterns-browser.js:1322
4. .agents/skills/impeccable/scripts/detector/detect-antipatterns-browser.js:5039
```

`--language` steers the same question into a different part of the project.
Asked without one, that query answers from JavaScript. Asked with
`--language python`, it answers from the project's own Python:

```
1. src/vaultspec_marketing/scrape/__init__.py:1
2. src/vaultspec_marketing/__main__.py:1
```

The index holds both sets. The filter decided which one you were asking
about.

## Name the nouns, and ask one thing

Search matches your query two ways at once: by meaning, and by exact term. Pure
natural language gives the second half little to work with. So describe the
behavior and name the concrete nouns the target would use, in the same breath:

```
uv run vaultspec-rag search "immutable cache-control on non-hashed assets" --type vault
```

Plain questions work. Against a current index, `why did we change how caching works` returned the right execution record first. Name the nouns when a rare
identifier, symbol, or spelling is involved, where the exact half has something
to catch.

Ask one thing at a time. A query carrying two concepts ranks against both and
matches the middle, which is usually neither. Run two searches.

## The filter surface

`--type` picks the content domain first: `vault`, `code`, `document`, or
`combined`. The filters below then split by what they narrow, so a code filter on
`--type vault` has no candidates to act on.

Code results:

| Filter                              | Narrows to                               |
| ----------------------------------- | ---------------------------------------- |
| `--language`                        | one programming language                 |
| `--path`                            | one exact project-relative path          |
| `--include-path` / `--exclude-path` | paths matching or missing a pattern      |
| `--function-name` / `--class-name`  | one function or class                    |
| `--structure`                       | one source-code structure kind           |
| `--prefer`                          | production code, tests, or documentation |

Document and vault results:

| Filter          | Narrows to                                                                     |
| --------------- | ------------------------------------------------------------------------------ |
| `--doc-type`    | `adr` (decision), `plan`, `exec` (execution), `audit`, `research`, `reference` |
| `--feature`     | one feature tag                                                                |
| `--date`        | one date                                                                       |
| `--tag`         | one frontmatter tag                                                            |
| `--source-path` | one originating file, for extracted documents                                  |

### Query markers

Write markers anywhere in the query text. Most mirror a flag, so `type:adr` does
what `--doc-type adr` does. Five have no flag equivalent and can only be written
this way.

| Group            | Markers                                      |
| ---------------- | -------------------------------------------- |
| Documents        | `type:` `feature:` `date:` `tag:`            |
| Code             | `lang:` `path:` `func:` `class:` `nodetype:` |
| Noise, no flag   | `only:` `exclude:` `include:`                |
| Ranking, no flag | `status:` `intent:`                          |

The noise markers take one or more domains from `prod`, `tests`, `docs`,
`locale`, `generated`, `vendored`, and `worktree`. Everything except `prod` is
treated as noise by default, so `only:prod` keeps production code and
`exclude:tests` drops the test tree. Comma-separated sets accumulate when
repeated.

`status:` takes `all`, `active`, or a comma-separated set such as
`accepted,proposed`. `intent:` takes `orientation`, the default, or `debugging`,
which reorders results for tracking down a fault rather than getting your
bearings.

```
uv run vaultspec-rag search "auth token validation only:prod" --type code
uv run vaultspec-rag search "gpu lock decision type:adr status:active"
```

`path:` is the in-query spelling of `--include-path`: it takes a pattern, and a
plain one matches that path and everything under it. `--path` is a different,
exact-path filter.

### Telling a weak result from an empty corpus

Search always returns its ten closest chunks, so a query with nothing to match
looks the same as one with a poor answer. `--scores` separates them.

A query the corpus genuinely answers scores in the tenths:

```
1. .vault/audit/large-index-resilience-ledger-concurrency-audit.md (score 0.7836)
2. .vault/research/service-concurrency-research.md (score 0.7180)
3. .vault/adr/store-eviction-log-rotation-adr.md (score 0.4746)
```

A query with nothing relevant scores in the thousandths, and still returns ten
rows:

```
1. .vault/adr/rate-collapse-baseline-adr.md (score 0.0013)
2. .vault/audit/encode-batch-adaptivity-audit.md (score 0.0008)
3. .vault/adr/service-graph-adr.md (score 0.0002)
```

Three orders of magnitude separate them. Absolute scores aren't comparable
between different queries, but that gap is: a top score in the thousandths means
the corpus holds no answer, and rewording won't produce one. Index the right
content instead.

`--json` gives a script the same results without the human formatting.

## When a result looks wrong

Work down this list rather than rewording repeatedly. Rewording is the last step,
not the first.

1. Run `--scores`. If the top score sits in the thousandths, the corpus holds no
   answer and no wording will find one.
1. If you're searching code, check coverage with a dry run.
1. Add the filter that states which kind of thing you want.
1. If results arrive doubled, exclude the mirrored tree with `exclude:worktree`
   or an `--exclude-path` pattern.
1. If the query carries two ideas, split it into two searches.
1. Reword, naming the concrete nouns the target would contain.

If none of that helps, the [issue tracker](https://github.com/nevenincs/vaultspec-rag/issues)
takes questions as well as bug reports. Include the query, the flags, and the
`--scores` output.

## Related documentation

- [Retrieval recipes](examples.md) shows worked searches, including the questions
  this tool answers badly.
- [Search and index](search-and-index.md) covers running searches and refreshing
  the index.
- [CLI reference](cli.md) lists every flag with its type and default.
- [Verify the index](verification.md) covers health, currency, and coverage.
- [Indexing](indexing.md) covers profiles, admission, and the encoders.
- [Architecture](architecture.md) covers how the two signals are fused.
- [Glossary](glossary.md) defines the vocabulary used here.

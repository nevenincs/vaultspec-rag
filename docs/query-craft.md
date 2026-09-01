# Writing a query that finds it

Search returns the closest matches it can rank, never an exhaustive list. That
one property drives everything on this page. A query that finds nothing useful
is usually not badly worded. It's aimed at a corpus that doesn't hold the
answer, or it's asking for more than one thing at once.

For how the ranking works, read the [architecture overview](architecture.md) and
the [indexing internals](indexing.md). This page is about what to type.

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
paths a dry run prints are the head of the list rather than the most important
files, so a sample full of vendored tool scripts doesn't mean the whole set is.

If the count is far off what you expect, fix admission before spending the
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

Both sets were admitted all along. The filter decided which one you were asking
about.

## Name the nouns, and ask one thing

Each chunk is encoded twice, and so is your query. The dense half matches
meaning and handles paraphrase well. The sparse half matches terms and catches
a rare identifier the dense half would smooth over. A query written as pure
natural language gives the sparse half little to work with.

So describe the behaviour and name the concrete nouns the target would use, in
the same breath:

```
uv run vaultspec-rag search "immutable cache-control on non-hashed assets" --type vault
```

Plain questions do work. Against a current index, `why did we change how caching works` returned the right execution record first. Treat naming the nouns as
sharpening a query rather than rescuing one.

Ask one thing at a time. A query carrying two concepts ranks against both and
matches the middle, which is usually neither. Run two searches.

## The filter surface

Filters split by what they narrow. Mixing classes is allowed and does nothing:
a code filter on `--type vault` has no candidates to act on.

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

| Filter          | Narrows to                                              |
| --------------- | ------------------------------------------------------- |
| `--doc-type`    | `adr`, `plan`, `exec`, `audit`, `research`, `reference` |
| `--feature`     | one feature tag                                         |
| `--date`        | one date                                                |
| `--tag`         | one frontmatter tag                                     |
| `--source-path` | one originating file, for extracted documents           |

Filters also work inline, so `type:adr` in the query text does what
`--doc-type adr` does.

Two flags matter outside those classes. `--scores` shows the numeric relevance
behind the ordering, which tells you whether the top hit won or merely came
first among weak matches:

```
1. Decision record: documentation cache policy (score 0.0260)
2. Decision record: deployment cache policy (score 0.0097)
```

`--json` gives a script the same results without the human formatting.

## When a result looks wrong

Work down this list rather than rewording repeatedly.

Check with `--scores` that the top result didn't merely win a weak field. Check
coverage with a dry run if you're searching code. Add the filter that states
which kind of thing you want, and exclude a mirrored tree if results arrive
doubled. Split the query if it carries two ideas. Then reword.

## Related documentation

- [Verify the index](verification.md) covers health, currency, and coverage.
- [Indexing](indexing.md) covers profiles, admission, and the encoders.
- [Architecture](architecture.md) covers how the two signals are fused.

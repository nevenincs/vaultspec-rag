# Writing a query that finds the right result

Describe the behavior you want to find, then narrow the search with filters.

Examples use the `uv run` prefix, which runs the command inside a project environment.
If you installed vaultspec-rag as a standalone tool, drop the prefix and call
`vaultspec-rag` directly; see the [installation guide](installation.md).

<p id="check-coverage-before-you-blame-the-query"></p>

## Check file coverage

If expected code is missing from results,
[check which files would be indexed](verification.md#is-it-indexing-the-right-files) and
[check index status](verification.md#check-index-status). A dry run previews file
selection; it does not show what is already stored.

## Filters do more than phrasing

Filters are the sharpest tool here, because they remove candidates before
ranking rather than competing with it.

### Narrowing document results

The same query against one project's vault, narrowed two ways:

```
uv run vaultspec-rag search "cache control on deployed assets" --type vault --doc-type adr
```

```text
1. .vault/adr/2026-08-28-docs-site-adr.md
   adr | feature: docs-site | 2026-08-28
2. .vault/adr/2026-07-01-neve-deployment-adr.md
   adr | feature: neve-deployment | 2026-07-01
3. .vault/adr/2026-06-28-landing-page-adr.md
   adr | feature: landing-page | 2026-06-28
4. .vault/adr/2026-09-02-docs-site-version-truth-adr.md
   adr | feature: docs-site | 2026-09-02
```

Every result is an `adr`, which is the filter doing its work and the shape you
want when you're asking why something was decided. The matching passage that
prints under each result is cut from the blocks here; the ranks, the paths, and
the type-and-feature lines are as printed. Ask instead for everything on one
feature:

```
uv run vaultspec-rag search "cache control on deployed assets" --type vault --feature docs-site
```

```text
1. .vault/plan/2026-08-28-docs-site-plan.md
   plan | feature: docs-site | 2026-08-28
2. .vault/exec/2026-08-28-docs-site/2026-08-28-docs-site-W05-P09-S50.md
   exec | feature: docs-site | 2026-08-28
3. .vault/adr/2026-08-28-docs-site-adr.md
   adr | feature: docs-site | 2026-08-28
```

Nine came back and the first three are shown. A plan, an execution record, and
the decision behind them: the document type is no longer fixed, and the feature
is. Same query, different question. One asked "what was decided", the other asked
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
Asked without one, that query answers from JavaScript. Add `--language python`
to the command above and the same question answers from the project's own
Python instead:

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
`locale`, `generated`, `vendored`, and `worktree`. The default profile treats
them unequally: `generated` and `worktree` are hidden outright, while `tests`,
`docs`, `locale` and `vendored` stay visible and are demoted below production.
So `only:prod` keeps production code, and `exclude:tests` drops a test tree that
would otherwise still be returned, lower down. Comma-separated sets accumulate when
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

<p id="telling-a-weak-result-from-an-empty-corpus"></p>

### Inspect result scores

Show numeric scores alongside results:

```bash
uv run vaultspec-rag search "graph rebuild race" --type vault --scores
```

Scores help compare ranked results; they aren't probabilities that your question has
been answered. Their meaning depends on the ranking configuration. No universal score
cutoff establishes whether your index contains an answer.

`--max-results` caps the results at 10 by default, but doesn't guarantee that many
matches. Results can be irrelevant, and empty output doesn't explain why.

Use `--json` for structured output. See the [search options](cli.md#search) for details.

## When a result looks wrong

1. Read the returned passages to check whether they answer your question.
1. [Check file coverage](#check-file-coverage) and index status if expected code is missing.
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

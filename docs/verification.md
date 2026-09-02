# Verify the index

Search answers from what it indexed, not from what's on disk. When a result looks wrong, the cause is usually one of three. The service isn't healthy, the index is behind the tree, or the tree it indexed isn't the tree you meant. Each has its own command.

This guide assumes an installed, provisioned workspace. If you haven't got that yet, start with the [installation guide](installation.md). For what the service is and how it stays warm, see the [service mode guide](service-mode.md).

## Is the service healthy?

```
uv run vaultspec-rag server doctor
```

```
Service readiness
Backend: server
Readiness: ready for requests
Live service:
  status: running (running)
  process: pid 75528 (alive)
  network: port 8766 (listening)
  heartbeat: 3s ago
  release: 0.4.6 (INCOMPATIBLE)
Installed dependencies: ready
  torch: ready - CUDA available on NVIDIA GeForce RTX 4080 SUPER
  models: ready - all 3 model repos present in the cache
  qdrant: ready - qdrant binary resolves from provisioned
```

Read that output carefully, because it says two things at once. The service is running and will answer queries, and the running release is marked `INCOMPATIBLE` with the client asking. That run exits `1`.

So don't gate on the word `ready` in the output. Gate on the exit code. A service can be alive, reachable, and still the wrong build. Only the exit status carries the whole verdict.

Stop and start the service after upgrading the package, and the incompatibility goes away:

```
uv run vaultspec-rag server stop
uv run vaultspec-rag server start
```

## Is the index current?

```
uv run vaultspec-rag status
```

```
Project index
Project: /path/to/your/project
Index data: running service storage
Vault documents: 20
Source code sections: 2589
Document sections: 0
Index generations:
  code: not indexed yet
  document: not indexed yet
  vault: not indexed yet
Server: running
```

Two different facts sit in that report, and they're often read as one.

The counts describe what's stored right now. The generation lines describe whether the current configuration has been indexed at all. A generation fingerprints the profile, the ordered routes, the preprocessing targets and versions, the ignores, the decoder policy, and the schema versions. Code and documents carry their own.

That report has both a non-zero count and a generation reading `not indexed yet`. That combination means stored data from an earlier run, under a configuration that no longer matches. Search will answer, and it'll answer from the old shape of the project.

Compare the counts against the tree itself, but not as an equality. A vault document is stored one point per chunk, so a healthy index reports more rows than the tree has files. The project used throughout this page holds 297 Markdown files under `.vault/` and indexes to 557.

What's diagnostic is a count well *below* the file count. The report above shows 20 against a tree of 294 files, which is the shape of a partial or abandoned run. Nothing in the tool will tell you that; you have to look.

## Does it cover the tree you think?

This is the question people skip, and it's the one that produces the most confusing results. Ask before indexing rather than after:

```
uv run vaultspec-rag index --type code --dry-run --dry-run-limit 5
```

```
Dry run: 93 source-code files would be indexed.
Admission summary:
  - unowned/rejected/ignored: 12
  - code/rejected/source_profile_excluded: 865
  - code/admitted/source_profile: 93
Files shown:
  - .agents/skills/impeccable/scripts/detector/detect-antipatterns-browser.js
  - .agents/skills/impeccable/scripts/live-browser-dom.js
  - .agents/skills/impeccable/scripts/live-browser-session.js
  - .agents/skills/impeccable/scripts/live-browser.js
  - .agents/skills/impeccable/scripts/modern-screenshot.umd.js
88 more files not shown. Use --dry-run-limit 93 or --json for the full list.
```

Ninety-three files admitted out of nearly a thousand considered. That ratio isn't a fault by itself, since the source profile exists to keep vendored trees and build output away from your results. What deserves a second look is which files came back first: tool scripts vendored into a skills directory, not the project's own source.

If that list doesn't look like the code you'd want to search, fix it before you spend the indexing run. Widen or narrow with `--exclude`, or change the profile. The [indexing guide](indexing.md) covers the profiles and how admission is decided.

Use `--json` for the full list when the human output truncates it.

## Bringing it up to date

```
uv run vaultspec-rag index
```

Scope it with `--type vault`, `--type code`, or `--type document` when only one kind has moved. Add `--rebuild` to delete the selected data first. Reach for it after changing a profile: a generation change means the stored vectors describe a configuration you've abandoned.

The running service reindexes as files change, so a healthy setup rarely needs this by hand. Reach for it after an upgrade, after a profile change, or when `status` shows a generation that doesn't match your configuration.

## Gating a script

Both commands take `--json`:

```
uv run vaultspec-rag status --json
uv run vaultspec-rag server doctor
```

For the service, the exit code carries the verdict. For the index, read the counts and the generations, and compare them against what you expect the tree to hold. A check that only asserts the service is running will pass against an index built last month.

## Related documentation

- [Indexing](indexing.md) covers profiles, admission, and what a generation fingerprints.
- [Service mode](service-mode.md) covers starting, stopping, and keeping the models warm.
- [Storage maintenance](storage-maintenance.md) covers pruning what indexing leaves behind.

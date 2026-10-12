# Installation, model supply and Torch configuration: evidence group s1-0034

Read this part when working with: [src/vaultspec_rag/builtins/__init__.py](../../../../src/vaultspec_rag/builtins/__init__.py), [src/vaultspec_rag/builtins/mcps/vaultspec-rag.builtin.json](../../../../src/vaultspec_rag/builtins/mcps/vaultspec-rag.builtin.json).

This is static evidence. Implementation observations, documentation claims, and test expectations remain distinct; no tests were run. An imported dependency uninspected within this evidence group may be covered in another capability reference. All listed full-file ranges are covered; report-local dependency boundaries are not inventory gaps.

[Installation, model supply and Torch configuration](installation-provisioning.md) provides module summaries, connections, and reconciled limitations.

## Capability summary

- [src/vaultspec_rag/builtins/__init__.py](../../../../src/vaultspec_rag/builtins/__init__.py) provides package-resource discovery and seeding for bundled builtin files. It finds the package root, walks and sorts files while excluding Python artifacts, and exposes `list_builtins()` and `seed_builtins()` as its public exports (lines 31-54, 141-150).
- Its seeder maps each bundled relative path under a target directory, can omit relative-path prefixes, skips existing files unless forced, classifies acted-on files as `[ADD]`, `[UPDATE]`, or `[UNCHANGED]`, and supports dry-run classification (lines 57-70, 73-113, 119-138). Actual changed files are passed to `atomic_write`; successful writes are added to the optional `written` list (lines 122-138).
- [src/vaultspec_rag/builtins/mcps/vaultspec-rag.builtin.json](../../../../src/vaultspec_rag/builtins/mcps/vaultspec-rag.builtin.json) is a seven-line MCP mode configuration template. It has install-mode command and argument placeholders and identifies the package (`vaultspec-rag`), module (`vaultspec_rag.server`), and tool-spec extra (`vaultspec-rag[mcp]`) (lines 1-7). This file alone does not show how placeholders are substituted or how the configuration is consumed.

## Interfaces and data flow

- `seed_builtins(target_dir, *, force=False, dry_run=False, written=None, exclude_prefixes=())` walks bundled files, derives slash-separated relative paths, filters prefixes, and checks/creates the target directory path through `open_plain_directory`. Unless `force` is true, existing destinations are skipped. It returns sorted `(relative_path, action)` pairs for files considered; under `dry_run`, it classifies without writing. With a supplied `written` list, it appends the relative path after each successful actual write (lines 73-80, 119-138).
- For forced or missing destinations, `_classify_action` compares destination and source bytes; a missing destination is `[ADD]`, matching bytes are `[UNCHANGED]`, and differing bytes or a caught read `OSError` are `[UPDATE]` (lines 57-70). The implementation calls `atomic_write(dest, src_file.read_text(encoding="utf-8"))` for non-unchanged files outside dry-run (lines 132-135).
- `list_builtins()` returns sorted slash-separated paths discovered under the bundled root, without copying them (lines 141-147).
- The module docstring describes the bundled tree as folding into `.vaultspec/` and says `vaultspec_rag.commands` consumes it (lines 1-16). These are documentation claims; the consumer was not inspected.
- The JSON template's `command` and sole `args` entry contain substitution markers; the remaining keys supply mode package, module, and tool-spec identifiers (JSON lines 1-7). The replacement and runtime data flow are not established by the assigned source.

## Boundaries and dependencies

- Implementation imports package resource support and `Path`, `vaultspec_core.core.helpers.atomic_write`, and local `open_plain_directory` (lines 19-29). Resource lookup is converted to `Path` at `_builtins_root()` (lines 31-38).
- Directory validation/creation is delegated to `open_plain_directory`; writing is delegated to `atomic_write` (lines 93-98, 119-135). Their detailed guarantees are asserted in the docstring but cannot be independently verified from this slice.
- The module names `vaultspec_rag.commands` as a consumer in its docstring (lines 9-10); that caller is outside the assigned range. The JSON names `vaultspec_rag.server` as a configured module (JSON line 5), but this does not establish its runtime behavior.
- No tests or other package files were read. No test expectations or runtime behavior beyond the shown code are asserted.

## Evidence

| Claim                                                                                                                                              | Project-relative file:line-range                                                                                                            | Kind                                   |
| -------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------- |
| Builtins are described as package resources folded into `.vaultspec/`, consumed by commands, with atomic-write and rollback-related design claims. | [src/vaultspec_rag/builtins/__init__.py:1-16](../../../../src/vaultspec_rag/builtins/__init__.py#L1)                                        | documentation claim                    |
| Root derives from `resources.files(__package__)`; file walk sorts paths and filters Python artifacts.                                              | [src/vaultspec_rag/builtins/__init__.py:31-54](../../../../src/vaultspec_rag/builtins/__init__.py#L31)                                      | implementation                         |
| Action classification compares bytes, labels absent files `[ADD]`, and treats caught read errors as changed.                                       | [src/vaultspec_rag/builtins/__init__.py:57-70](../../../../src/vaultspec_rag/builtins/__init__.py#L57)                                      | implementation                         |
| Seeder signature, return contract, and documented behavior for force, dry-run, written paths, prefix exclusions, and errors.                       | [src/vaultspec_rag/builtins/__init__.py:73-118](../../../../src/vaultspec_rag/builtins/__init__.py#L73)                                     | implementation and documentation claim |
| Prefix filtering, directory helper call, skip-existing behavior, atomic write, written-list append, and sorted result.                             | [src/vaultspec_rag/builtins/__init__.py:119-138](../../../../src/vaultspec_rag/builtins/__init__.py#L119)                                   | implementation                         |
| Public listing and exports.                                                                                                                        | [src/vaultspec_rag/builtins/__init__.py:141-150](../../../../src/vaultspec_rag/builtins/__init__.py#L141)                                   | implementation                         |
| MCP config placeholders and mode identifiers.                                                                                                      | [src/vaultspec_rag/builtins/mcps/vaultspec-rag.builtin.json:1-7](../../../../src/vaultspec_rag/builtins/mcps/vaultspec-rag.builtin.json#L1) | configuration data                     |
| No test source was read; there is no test expectation evidence in this slice.                                                                      | Assigned files only                                                                                                                         | test                                   |

## Uncertainty and follow-up

- To verify the delegated directory and write guarantees, inspect [src/vaultspec_rag/\_plain_directory.py](../../../../src/vaultspec_rag/_plain_directory.py) for `open_plain_directory` and the definition of `vaultspec_core.core.helpers.atomic_write`; both are outside this slice.
- To confirm the documented consumer and JSON placeholder substitution, inspect the relevant `vaultspec_rag.commands` caller and the code that loads this MCP JSON template. Those were not assigned, so no caller behavior is inferred.

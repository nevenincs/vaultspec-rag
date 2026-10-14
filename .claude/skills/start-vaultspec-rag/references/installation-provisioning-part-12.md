# Installation, model supply and Torch configuration: evidence group s1-0149

Read this part when working with: [src/vaultspec_rag/torch_config/__init__.py](../../../../src/vaultspec_rag/torch_config/__init__.py), [src/vaultspec_rag/torch_config/\_constants.py](../../../../src/vaultspec_rag/torch_config/_constants.py), [src/vaultspec_rag/torch_config/\_direct_dep.py](../../../../src/vaultspec_rag/torch_config/_direct_dep.py), [src/vaultspec_rag/torch_config/\_index.py](../../../../src/vaultspec_rag/torch_config/_index.py), [src/vaultspec_rag/torch_config/\_inspect.py](../../../../src/vaultspec_rag/torch_config/_inspect.py), [src/vaultspec_rag/torch_config/\_lockfile.py](../../../../src/vaultspec_rag/torch_config/_lockfile.py), [src/vaultspec_rag/torch_config/\_mutate.py](../../../../src/vaultspec_rag/torch_config/_mutate.py).

This is static evidence. Implementation observations, documentation claims, and test expectations remain distinct; no tests were run. An imported dependency uninspected within this evidence group may be covered in another capability reference. All listed full-file ranges are covered; report-local dependency boundaries are not inventory gaps.

[Installation, model supply and Torch configuration](installation-provisioning.md) provides module summaries, connections, and reconciled limitations.

## Capability summary

### Implementation

- [src/vaultspec_rag/torch_config/__init__.py](../../../../src/vaultspec_rag/torch_config/__init__.py) contains package documentation and exports no names itself; it describes the package as pure logic for install/uninstall torch configuration and names the package split (1-24).
- [src/vaultspec_rag/torch_config/\_constants.py](../../../../src/vaultspec_rag/torch_config/_constants.py) centralizes TOML table-like typing and tget, the canonical source marker, minimum/direct torch requirement, managed-dependency marker key, state/action enums, and apply/remove and direct-dependency report dataclasses (37-48, 59-76, 79-121, 124-154).
- [src/vaultspec_rag/torch_config/\_index.py](../../../../src/vaultspec_rag/torch_config/_index.py) defines the fixed accelerated index name and URL (33-36).
- [src/vaultspec_rag/torch_config/\_lockfile.py](../../../../src/vaultspec_rag/torch_config/_lockfile.py) reads uv.lock with stdlib tomllib, selects package entries named torch whose registry matches the requested index URL after trimming trailing slashes, and requires exactly one distinct version; read, parse, missing-match, and ambiguous-match cases raise LockedTorchVersionError (27-58).
- [src/vaultspec_rag/torch_config/\_inspect.py](../../../../src/vaultspec_rag/torch_config/_inspect.py) loads TOML, recognizes UTF-8 BOMs, probes CRLF, and classifies the accelerated index and torch source entries as missing, canonical, or customised (30-67, 97-135, 138-173, 176-328, 353-371). Unsupported index/source shapes and partial or conflicting configurations are classified as customised; is_half_applied separately identifies a single canonical half with the other half absent (331-350).
- [src/vaultspec_rag/torch_config/\_mutate.py](../../../../src/vaultspec_rag/torch_config/_mutate.py) builds the manual snippet from the same index/source helpers used for application (47-71). apply_patch returns absent/already/conflict without writing and writes the canonical block for a missing state; remove_patch removes canonical entries and handles a half-applied state, while skipping other customised states (74-159). Its writer serializes, reparses before writing, restores CRLF and the original trailing-newline count, then calls atomic_write (162-230). Helpers create index/source tables, append or promote supported source forms, remove canonical entries, and clean empty containers (238-443).
- [src/vaultspec_rag/torch_config/\_direct_dep.py](../../../../src/vaultspec_rag/torch_config/_direct_dep.py) recognizes torch among PEP 621 dependencies and extras, PEP 735 groups, uv dev dependencies, Poetry dependency tables/groups, PDM dev groups, and Hatch environment dependencies (72-229). It parses PEP 508 requirement strings with packaging and normalizes project names (38-69). It can report an existing direct dependency, add torch>=2.4 to project dependencies or a selected PEP 735 group, record the written location in [tool.vaultspec-rag], and remove only the recorded managed requirement (232-265, 268-361, 364-439, 442-490).

### Documentation claims

- Package documentation calls this the pure-logic layer for install/uninstall and says it has no CLI, Rich, prompts, or process side effects beyond one atomic write ([src/vaultspec_rag/torch_config/__init__.py](../../../../src/vaultspec_rag/torch_config/__init__.py) 1-16). These are source-doc claims, not independently checked across callers.
- Module docs describe the index URL as fixed and the lockfile derivation as build/checkout-only, with installed runtime resolution using an installation receipt ([src/vaultspec_rag/torch_config/\_index.py](../../../../src/vaultspec_rag/torch_config/_index.py) 10-27; [src/vaultspec_rag/torch_config/\_lockfile.py](../../../../src/vaultspec_rag/torch_config/_lockfile.py) 7-11). Runtime/build consumers were not inspected.
- The writer and apply/remove docs claim round-trip preservation of unrelated content and symmetric apply/remove behavior ([src/vaultspec_rag/torch_config/\_mutate.py](../../../../src/vaultspec_rag/torch_config/_mutate.py) 4-7, 86-87, 114-125, 162-230). These claims were not tested in this task.

### Test expectations

- No test files were assigned or read. No passing-test status or test expectation can be reported from test sources.
- Docstrings describe expected outcomes for missing, canonical, customised, absent, and half-applied configurations ([src/vaultspec_rag/torch_config/\_mutate.py](../../../../src/vaultspec_rag/torch_config/_mutate.py) 74-88, 114-125); these are documented contracts, not evidence of passing tests.

### Inference

- The functions form a likely consumer-project flow: inspect/classify a pyproject, apply/remove the cu130 entries, and separately ensure/remove the direct torch dependency. This follows the package docs and local calls, but the orchestrator/caller was not read.

## Interfaces and data flow

- detect_state(pyproject) -> TorchConfigState loads the consumer TOML and classifies it without writing; invalid TOML is re-raised by the loader ([src/vaultspec_rag/torch_config/\_inspect.py](../../../../src/vaultspec_rag/torch_config/_inspect.py) 49-67, 299-329, 353-371).
- apply_patch(pyproject) and remove_patch(pyproject) return PatchReport values with action, path, conflicts, and optional preview ([src/vaultspec_rag/torch_config/\_constants.py](../../../../src/vaultspec_rag/torch_config/_constants.py) 124-145; [src/vaultspec_rag/torch_config/\_mutate.py](../../../../src/vaultspec_rag/torch_config/_mutate.py) 74-159). The configuration is represented by \[[tool.uv.index]\] and [tool.uv.sources].torch; generated values come from [src/vaultspec_rag/torch_config/\_index.py](../../../../src/vaultspec_rag/torch_config/_index.py) and [src/vaultspec_rag/torch_config/\_constants.py](../../../../src/vaultspec_rag/torch_config/_constants.py) ([src/vaultspec_rag/torch_config/\_mutate.py](../../../../src/vaultspec_rag/torch_config/_mutate.py) 262-349).
- The direct-dependency API is has_direct_torch_dep(pyproject), ensure_direct_torch_dep(pyproject, torch_group=None), and remove_managed_direct_torch_dep(pyproject); it returns presence/location or a DirectTorchDepReport ([src/vaultspec_rag/torch_config/\_direct_dep.py](../../../../src/vaultspec_rag/torch_config/_direct_dep.py) 232-265, 378-439, 456-490; [src/vaultspec_rag/torch_config/\_constants.py](../../../../src/vaultspec_rag/torch_config/_constants.py) 147-154). The ownership/location marker is stored under [tool.vaultspec-rag]; removal resolves that location and removes only an exact DIRECT_TORCH_REQUIREMENT entry.
- locked_torch_version(root, index_url=CU130_INDEX_URL) -> str reads root/uv.lock; it does not write that file ([src/vaultspec_rag/torch_config/\_lockfile.py](../../../../src/vaultspec_rag/torch_config/_lockfile.py) 31-58).
- Local module relationships: \_direct_dep uses constants, TOML inspection, and the shared shape-preserving writer; \_mutate uses constants, index constants, and inspection/classification helpers; \_lockfile uses the index URL ([src/vaultspec_rag/torch_config/\_direct_dep.py](../../../../src/vaultspec_rag/torch_config/_direct_dep.py) 19-32; [src/vaultspec_rag/torch_config/\_mutate.py](../../../../src/vaultspec_rag/torch_config/_mutate.py) 21-41; [src/vaultspec_rag/torch_config/\_lockfile.py](../../../../src/vaultspec_rag/torch_config/_lockfile.py) 19-20).

## Boundaries and dependencies

- Inspected code reads consumer [pyproject.toml](../../../../pyproject.toml) files and uv.lock; the write path shown is only the pyproject writer ([src/vaultspec_rag/torch_config/\_inspect.py](../../../../src/vaultspec_rag/torch_config/_inspect.py) 49-67; [src/vaultspec_rag/torch_config/\_lockfile.py](../../../../src/vaultspec_rag/torch_config/_lockfile.py) 31-58; [src/vaultspec_rag/torch_config/\_mutate.py](../../../../src/vaultspec_rag/torch_config/_mutate.py) 201-230). No command/process execution is shown in these ranges.
- Imported implementations are uninspected. In particular, vaultspec_core.core.helpers.atomic_write is called, but its atomicity guarantees and failure behavior cannot be established from this slice ([src/vaultspec_rag/torch_config/\_mutate.py](../../../../src/vaultspec_rag/torch_config/_mutate.py) 17-19, 223-230). TOMLKit, packaging, and typing/runtime dependency behavior is likewise outside the read set.
- Package documentation names the install/uninstall step and MCP-extra reconciler as consumers ([src/vaultspec_rag/torch_config/__init__.py](../../../../src/vaultspec_rag/torch_config/__init__.py) 4-8; [src/vaultspec_rag/torch_config/\_constants.py](../../../../src/vaultspec_rag/torch_config/_constants.py) 1-7); their implementation and actual call sites were not read. The build-tool/runtime boundaries in [src/vaultspec_rag/torch_config/\_index.py](../../../../src/vaultspec_rag/torch_config/_index.py) and [src/vaultspec_rag/torch_config/\_lockfile.py](../../../../src/vaultspec_rag/torch_config/_lockfile.py) are documented claims only.

## Evidence

- Constants, enums, reports, and table access: [src/vaultspec_rag/torch_config/\_constants.py:37-48,59-76,79-121,124-154](../../../../src/vaultspec_rag/torch_config/_constants.py#L37) | implementation.
- Fixed accelerated index identity: [src/vaultspec_rag/torch_config/\_index.py:33-36](../../../../src/vaultspec_rag/torch_config/_index.py#L33) | implementation.
- Lockfile selection and exact-one rule: [src/vaultspec_rag/torch_config/\_lockfile.py:31-58](../../../../src/vaultspec_rag/torch_config/_lockfile.py#L31) | implementation.
- TOML loading, BOM handling, and line-ending probe: [src/vaultspec_rag/torch_config/\_inspect.py:30-67](../../../../src/vaultspec_rag/torch_config/_inspect.py#L30) | implementation.
- Canonical index/source criteria: [src/vaultspec_rag/torch_config/\_inspect.py:138-173](../../../../src/vaultspec_rag/torch_config/_inspect.py#L138) | implementation.
- State combination and half-applied detection: [src/vaultspec_rag/torch_config/\_inspect.py:299-350](../../../../src/vaultspec_rag/torch_config/_inspect.py#L299) | implementation.
- Apply/remove outcomes: [src/vaultspec_rag/torch_config/\_mutate.py:74-159](../../../../src/vaultspec_rag/torch_config/_mutate.py#L74) | implementation.
- Write shaping and atomic-write call: [src/vaultspec_rag/torch_config/\_mutate.py:201-230](../../../../src/vaultspec_rag/torch_config/_mutate.py#L201) | implementation (the imported writer implementation is uninspected).
- Dependency recognition surfaces: [src/vaultspec_rag/torch_config/\_direct_dep.py:72-229](../../../../src/vaultspec_rag/torch_config/_direct_dep.py#L72) | implementation.
- Managed dependency write/removal: [src/vaultspec_rag/torch_config/\_direct_dep.py:268-361,378-439,442-490](../../../../src/vaultspec_rag/torch_config/_direct_dep.py#L268) | implementation.
- Package export/caller framing: [src/vaultspec_rag/torch_config/__init__.py:1-24](../../../../src/vaultspec_rag/torch_config/__init__.py#L1) | documentation claim.
- Lockfile runtime/build framing: [src/vaultspec_rag/torch_config/\_lockfile.py:7-11](../../../../src/vaultspec_rag/torch_config/_lockfile.py#L7) | documentation claim.
- Likely end-to-end consumer flow: [src/vaultspec_rag/torch_config/__init__.py:4-8](../../../../src/vaultspec_rag/torch_config/__init__.py#L4); [src/vaultspec_rag/torch_config/\_mutate.py:74-159](../../../../src/vaultspec_rag/torch_config/_mutate.py#L74); [src/vaultspec_rag/torch_config/\_direct_dep.py:378-490](../../../../src/vaultspec_rag/torch_config/_direct_dep.py#L378) | inference.
- Test status/expectations: no test source in the assigned read set | no test evidence.

## Uncertainty and follow-up

- No follow-up is needed to describe the assigned implementation. To verify production callers and their orchestration, inspect the install/uninstall torch flow named in [src/vaultspec_rag/torch_config/__init__.py:4-8](../../../../src/vaultspec_rag/torch_config/__init__.py#L4); to verify the claimed MCP-extra consumer, inspect the reconciler named in [src/vaultspec_rag/torch_config/\_constants.py:1-7](../../../../src/vaultspec_rag/torch_config/_constants.py#L1). To confirm actual atomic-write guarantees, inspect vaultspec_core.core.helpers.atomic_write, imported at [src/vaultspec_rag/torch_config/\_mutate.py:17-19](../../../../src/vaultspec_rag/torch_config/_mutate.py#L17). Test expectations require the relevant test files, which were outside this slice.

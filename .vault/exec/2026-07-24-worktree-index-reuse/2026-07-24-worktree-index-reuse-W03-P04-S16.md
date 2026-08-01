---
tags:
  - '#exec'
  - '#worktree-index-reuse'
date: '2026-07-24'
modified: '2026-07-24'
body_hash: 'sha256:f2b2901f2194a5b3394f8dc93da354553db95fffc2798cf982291dc2d3e7a98c'
step_id: 'S16'
related:
  - "[[2026-07-24-worktree-index-reuse-plan]]"
---

# run the full quality gates on the changed surface: ruff, formatting, type check with the project settings, complexity gate, and the affected pytest suites

## Scope

- `repository quality gates`

## Description

- Enumerated the changed surface: new files `_reuse.py`, `_donor_candidates.py`, `test_index_reuse.py`, `test_donor_candidates.py`, `test_store_donor_reads.py`, plus feature edits to the seam and store.
- Ran ruff check, ruff format --check, the citation gate, the complexity gate, basedpyright, ty (`--python-platform all`), and the affected pytest suites.

## Outcome

- `ruff check src tools`: All checks passed.
- `ruff format --check` (feature files): 5 files already formatted.
- citation gate (`tools/citation_gate.py`): clean - no active development-record citations or workstation-identity path leaks.
- ty (`ty check src/vaultspec_rag --python-platform all`): All checks passed.
- basedpyright: 0 errors on the feature files. Whole-tree run reports 3 pre-existing errors in `memory_probe.py` (unused function + two `contextmanager` deprecation notices); that file is unmodified by this feature and the errors predate it.
- complexity gate (`tools/complexity_gate.py`): cyclomatic (xenon absolute \<= C) PASS; nesting depth PASS; **cognitive complexity FAIL** - `_reuse.py` `adopt_verified_vectors` scores CCR001 26 > 20.
- pytest (affected surface, 14 files: reuse, donor candidates, donor reads, streaming segments, encode hygiene, jobs unit, job control, server routes, config, config epoch, chunk-worker parity, torch-load centralized, mcp import isolation, cli no-mcp import): 331 passed.

## Notes

The changed surface is green on ruff, formatting, citations, ty (all platforms), basedpyright (feature files), the cyclomatic and nesting complexity checks, and all 331 affected tests.

One genuine gate failure, reported honestly rather than papered over: the project complexity gate's cognitive-complexity check (CCR001 \<= 20) fails on `adopt_verified_vectors` at complexity 26. This is present in the code-complete baseline of the feature (the file was byte-identical to its pre-verification state throughout - the failure is not an artefact of any mutation, which were all restored). The mission's explicit constraint that the source files remain byte-identical to the pre-mutation state precludes refactoring the method here; the cognitive-complexity reduction of `adopt_verified_vectors` belongs to an implementation step and is surfaced for the plan owner to action before landing. The named complexity requirement in the step (cyclomatic max absolute rank C via the radon-backed xenon check) does pass.

basedpyright's 3 `memory_probe.py` errors are out of scope (unmodified file, pre-existing).

## Resolution: CCR001 cognitive-complexity refactor (2026-07-24)

The deferred CCR001 failure is now cleared with a zero-behavior-change refactor of `_reuse.py`. `adopt_verified_vectors` was decomposed by extracting two cohesive helpers, keeping the semantics byte-for-byte (donors consulted in rank order, first verified hit wins per point, byte-for-byte payload-content verify, sparse-required gate, read failures logged and degraded to miss, identical stats-counter increments):

- Module function `_verify_and_adopt(chunk, point, expected_content, *, sparse_required) -> bool` - the per-point verify (content byte-compare + sparse-present gate) and dense/sparse adoption, returning whether the point was adopted.
- Method `DonorReuseContext._adopt_from_collection(...)` - the per-donor batch lookup (the `retrieve_donor_points` call plus its read-failure log-and-degrade), iterating found points and clearing each verified hit from `remaining`.

`adopt_verified_vectors` retains only identity precompute, the remaining-id map build, the rank-order collection loop with the `if not remaining: break` short-circuit, and the final hit/miss accounting.

New CCR001 scores: `adopt_verified_vectors` 26 -> 4; new helpers `_verify_and_adopt` 9, `_adopt_from_collection` 6; module worst is `resolve_donor_reuse` at 11 (unchanged). File passes `flake8 --select=CCR --max-cognitive-complexity=20`.

Guard-proof re-run (one uninterrupted sequence): flipped the content comparison in `_verify_and_adopt` (`!=` -> `==`) so a content mismatch adopts; `test_content_mismatch_at_same_point_id_is_a_miss_and_encodes` went red on `assert context.stats.reuse_hits == 0` (`assert 1 == 0`), confirming the assertion binds to the content-verify branch; restored the comparison; test green again.

Gates on the file, all green: ruff check + ruff format, basedpyright (0 errors), ty `--python-platform all`, citation gate clean, radon cc no block at grade C or worse, CCR001 \<= 20. Test totals: `test_index_reuse.py` + `test_donor_candidates.py` + `test_store_donor_reads.py` = 42 passed.

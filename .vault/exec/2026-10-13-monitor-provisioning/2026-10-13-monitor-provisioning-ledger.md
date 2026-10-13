---
tags:
  - '#exec'
  - '#monitor-provisioning'
date: '2026-10-13'
modified: '2026-10-13'
body_schema: 'body-v2'
body_hash: 'sha256:775da68347579d4cb5a70e5b600c49489119b9f34f7f106454ff4b804eec37e5'
related:
  - "[[2026-10-13-monitor-provisioning-plan]]"
---

<!-- Machine-owned, whole file: `vaultspec-core vault exec log` creates it
     on first use and appends every row; never hand-edit it. Add no
     frontmatter fields. Wiki-links belong in `related:` only.

     ONE ledger per plan, the only execution artifact. Each row's first
     column names its Step. -->

# `monitor-provisioning` ledger

## Changes

<!-- MECHANICAL LOG, append-only, one row per path touched per Step, written
     by `--row`:
       - `S##` `A` `path`   added
       - `S##` `M` `path`   modified
       - `S##` `D` `path`   deleted
       - `S##` `R` `old` -> `new`   renamed
     Paths are repo-relative, in backticks. No prose: the Step row states the
     intent and the commit carries the diff.

     Optional per-Step rows, written by `--verify` and `--by`:
       - `S##` `verify:` `<command>` -> `pass` | `fail`
       - `S##` `by:` `<persona>`

     Rows are appended in Step order and never rewritten. Only rows in this
     section register a Step as covered. `--note` adds a `## Notes` section
     ONLY on exception (data loss, skipped work, a scaffold left in code, a
     persistent failure), one `S##`-prefixed line each; it is otherwise
     omitted. -->

- `S01` `A` `src/vaultspec_rag/native_binary/__init__.py`
- `S01` `A` `src/vaultspec_rag/native_binary/_install.py`
- `S01` `R` `src/vaultspec_rag/qdrant_runtime/_download.py` -> `src/vaultspec_rag/native_binary/_download.py`
- `S01` `R` `src/vaultspec_rag/qdrant_runtime/_executable_hold.py` -> `src/vaultspec_rag/native_binary/_hold.py`
- `S01` `M` `src/vaultspec_rag/qdrant_runtime/_constants.py`
- `S01` `M` `src/vaultspec_rag/qdrant_runtime/_managed_install.py`
- `S01` `M` `src/vaultspec_rag/qdrant_runtime/_provision.py`
- `S01` `M` `src/vaultspec_rag/qdrant_runtime/_spawn_trust.py`
- `S01` `M` `src/vaultspec_rag/tests/_fake_qdrant_binary.py`
- `S01` `M` `src/vaultspec_rag/tests/_qdrant_provision_seam.py`
- `S01` `M` `src/vaultspec_rag/tests/integration/test_helpers_qdrant_mirror.py`
- `S01` `M` `src/vaultspec_rag/tests/test_cli_progress_surfaces.py`
- `S01` `M` `src/vaultspec_rag/tests/test_provision.py`
- `S01` `M` `src/vaultspec_rag/tests/test_qdrant_download.py`
- `S01` `M` `src/vaultspec_rag/tests/test_qdrant_download_faults.py`
- `S01` `M` `src/vaultspec_rag/tests/test_qdrant_executable_hold.py`
- `S01` `M` `src/vaultspec_rag/tests/test_qdrant_install.py`
- `S01` `M` `src/vaultspec_rag/tests/test_qdrant_offline_install.py`
- `S01` `M` `src/vaultspec_rag/tests/test_qdrant_restart_accounting.py`
- `S01` `M` `src/vaultspec_rag/tests/test_qdrant_runtime.py`
- `S01` `M` `src/vaultspec_rag/tests/test_qdrant_spawn_trust.py`
- `S01` `M` `src/vaultspec_rag/tests/test_qdrant_store_format.py`
- `S01` `M` `src/vaultspec_rag/tests/test_start_provisioning.py`
- `S01` `M` `tools/binaries/bun_toolchain.py`
- `S01` `M` `tools/binaries/tests/test_bun_toolchain.py`
- `S01` `M` `tools/monitor/acquire.py`
- `S01` `M` `tools/monitor/build.py`
- `S01` `M` `tools/monitor/frontend.py`
- `S01` `M` `tools/monitor/linux_exec.py`
- `S01` `M` `tools/monitor/offline.py`
- `S01` `M` `tools/monitor/provenance.py`
- `S01` `M` `tools/monitor/release.py`
- `S01` `M` `tools/monitor/smoke.py`
- `S01` `M` `tools/monitor/tests/test_frontend.py`
- `S01` `M` `tools/qdrant_pin_digests.py`
- `S01` `verify:` `uv run --no-sync ruff check src tools dev conftest.py` -> `pass`
- `S01` `verify:` `uv run --no-sync ruff format --check src tools dev conftest.py` -> `pass`
- `S01` `verify:` `uv run --no-sync ty check src tools dev conftest.py` -> `pass`
- `S01` `verify:` `uv run --no-sync pytest test_qdrant_* test_provision test_managed_install test_start_provisioning test_cli_progress_surfaces test_config_operator_binary tools/binaries/tests tools/monitor/tests -q` -> `pass`
- `S01` `by:` `implementation-engineer-high`
- `S02` `A` `src/vaultspec_rag/native_binary/_targets.py`
- `S02` `A` `src/vaultspec_rag/monitor_runtime/__init__.py`
- `S02` `A` `src/vaultspec_rag/monitor_runtime/_assets.py`
- `S02` `A` `src/vaultspec_rag/monitor_runtime/_pins.py`
- `S02` `A` `tools/monitor/pins.py`
- `S02` `A` `tools/monitor/tests/test_pins.py`
- `S02` `A` `src/vaultspec_rag/tests/test_monitor_pins.py`
- `S02` `D` `tools/binaries/native.py`
- `S02` `M` `tools/binaries/build_pyapp.py`
- `S02` `M` `tools/binaries/bun_toolchain.py`
- `S02` `M` `tools/monitor/acquire.py`
- `S02` `M` `tools/monitor/build.py`
- `S02` `M` `tools/monitor/offline.py`
- `S02` `M` `tools/monitor/release.py`
- `S02` `M` `tools/monitor/smoke.py`
- `S02` `M` `tools/packaging/bundles.py`
- `S02` `M` `tools/packaging/products.py`
- `S02` `M` `pyproject.toml`
- `S02` `M` `.gitignore`
- `S02` `verify:` `uv run --no-sync ruff check src tools dev conftest.py` -> `pass`
- `S02` `verify:` `uv run --no-sync ruff format --check src tools dev conftest.py` -> `pass`
- `S02` `verify:` `uv run --no-sync ty check src tools dev conftest.py` -> `pass`
- `S02` `verify:` `uv run --no-sync pytest src/vaultspec_rag/tests/test_monitor_pins.py tools/monitor/tests tools/binaries/tests -q` -> `pass`
- `S02` `verify:` `uv build --wheel --sdist, then both artifacts listed carrying vaultspec_rag/monitor_runtime/_generated_pins.py` -> `pass`
- `S02` `by:` `implementation-engineer-high`
- `S03` `A` `src/vaultspec_rag/monitor_runtime/_errors.py`
- `S03` `A` `src/vaultspec_rag/monitor_runtime/_resolve.py`
- `S03` `A` `src/vaultspec_rag/monitor_runtime/_provision.py`
- `S03` `A` `src/vaultspec_rag/monitor_runtime/_launch.py`
- `S03` `A` `src/vaultspec_rag/native_binary/_report.py`
- `S03` `A` `src/vaultspec_rag/tests/test_monitor_resolution.py`
- `S03` `A` `src/vaultspec_rag/tests/test_monitor_provisioning.py`
- `S03` `M` `src/vaultspec_rag/monitor_runtime/_pins.py`
- `S03` `M` `src/vaultspec_rag/monitor_process.py`
- `S03` `M` `src/vaultspec_rag/_program_lookup.py`
- `S03` `M` `src/vaultspec_rag/config/_types.py`
- `S03` `M` `src/vaultspec_rag/config/_settings.py`
- `S03` `M` `src/vaultspec_rag/config/_schema.py`
- `S03` `M` `src/vaultspec_rag/config/_registry.py`
- `S03` `M` `src/vaultspec_rag/qdrant_runtime/_constants.py`
- `S03` `M` `src/vaultspec_rag/qdrant_runtime/_provision.py`
- `S03` `M` `src/vaultspec_rag/cli/_service_qdrant.py`
- `S03` `M` `src/vaultspec_rag/commands/_provision.py`
- `S03` `M` `src/vaultspec_rag/tests/_qdrant_provision_seam.py`
- `S03` `M` `src/vaultspec_rag/tests/test_config_operator_binary.py`
- `S03` `M` `src/vaultspec_rag/tests/test_monitor_process.py`
- `S03` `M` `src/vaultspec_rag/tests/test_program_lookup_sites.py`
- `S03` `M` `src/vaultspec_rag/tests/test_python_child_spawn_sites.py`
- `S03` `M` `src/vaultspec_rag/tests/test_qdrant_install.py`
- `S03` `M` `src/vaultspec_rag/tests/test_qdrant_install_recovery.py`
- `S03` `M` `.env.example`
- `S03` `M` `docs/configuration.md`
- `S03` `verify:` `uv run --no-sync ruff check src tools dev conftest.py` -> `pass`
- `S03` `verify:` `uv run --no-sync ruff format --check src tools dev conftest.py` -> `pass`
- `S03` `verify:` `uv run --no-sync ty check src tools dev conftest.py` -> `pass`
- `S03` `verify:` `uv run --no-sync pytest monitor and config suites (328 tests)` -> `pass`
- `S03` `verify:` `uv run --no-sync pytest qdrant install, runtime, cli, provisioning and tools suites (311 tests)` -> `pass`
- `S03` `verify:` `uv run --no-sync python -m dev lint markdown` -> `pass`
- `S03` `verify:` `uv run --no-sync python -m dev lint docs-conventions` -> `pass`
- `S03` `by:` `implementation-engineer-high`
- `S04` `M` `src/vaultspec_rag/commands/_provision.py`
- `S04` `M` `src/vaultspec_rag/cli/_render.py`
- `S04` `M` `src/vaultspec_rag/_readiness.py`
- `S04` `M` `src/vaultspec_rag/monitor_runtime/_provision.py`
- `S04` `A` `src/vaultspec_rag/tests/test_monitor_provision_step.py`
- `S04` `M` `src/vaultspec_rag/tests/conftest.py`
- `S04` `M` `src/vaultspec_rag/tests/test_provision.py`
- `S04` `M` `src/vaultspec_rag/tests/test_readiness.py`
- `S04` `M` `src/vaultspec_rag/tests/test_install_provision.py`
- `S04` `M` `src/vaultspec_rag/tests/test_program_lookup_sites.py`
- `S04` `M` `src/vaultspec_rag/tests/test_server_doctor.py`
- `S04` `verify:` `uv run --no-sync ruff check src tools dev conftest.py` -> `pass`
- `S04` `verify:` `uv run --no-sync ruff format --check src tools dev conftest.py` -> `pass`
- `S04` `verify:` `uv run --no-sync ty check src tools dev conftest.py` -> `pass`
- `S04` `verify:` `uv run --no-sync pytest -m unit -k 'start or provision or readiness or install or doctor or client or monitor or model_fetch or render or health or status' (1810 passed, 8 pre-existing environment failures)` -> `pass`
- `S04` `verify:` `uv run --no-sync python -m dev lint markdown` -> `pass`
- `S04` `by:` `implementation-engineer-high`
- `S05` `M` `.github/workflows/publish.yml`
- `S05` `M` `.github/workflows/binaries.yml`
- `S05` `M` `justfile`
- `S05` `M` `tools/monitor/pins.py`
- `S05` `M` `tools/monitor/release.py`
- `S05` `M` `tools/packaging/bundles.py`
- `S05` `M` `tools/conftest.py`
- `S05` `M` `tools/packaging/tests/test_bundles.py`
- `S05` `M` `tools/monitor/tests/test_pins.py`
- `S05` `M` `tools/monitor/tests/test_release.py`
- `S05` `M` `tools/monitor/tests/test_provenance.py`
- `S05` `M` `tools/binaries/tests/test_release_workflow.py`
- `S05` `verify:` `uv run --no-sync ruff check src tools dev conftest.py` -> `pass`
- `S05` `verify:` `uv run --no-sync ruff format --check src tools dev conftest.py` -> `pass`
- `S05` `verify:` `uv run --no-sync ty check the changed tools modules and their tests` -> `pass`
- `S05` `verify:` `uv run --no-sync python -m dev.actionlint, the pinned actionlint over every workflow` -> `pass`
- `S05` `verify:` `uv run --no-sync pytest tools dev (415 passed, 4 skipped)` -> `pass`
- `S05` `verify:` `uv run --no-sync pytest the citation, marker, pointer, monitor-pin and monitor-runtime suites (206 passed)` -> `pass`
- `S05` `by:` `implementation-engineer-high`

## Notes

- `S01` The lift moved two modules, so five orientation documents under .vaultspec/skills/start-vaultspec-rag/references/ now link to `src/vaultspec_rag/qdrant_runtime/_download.py` and `_executable_hold.py,` which no longer exist, and the documentation link check fails on 14 such links. Those files are user-owned policy sources and were left untouched.
- `S01` No managed-install state machine was lifted beyond the digest, staging and single-member extraction primitives: the free-space admission, the atomic replace remedy, the provisioning lock and the manifest carry Qdrant-specific wording and stay with their owner. The transport and the executable hold moved because they name nothing Qdrant-specific and a second owner would have had to import across runtime packages.
- `S02` Guard proofs run as break, run alone, fail on the named assertion, restore, pass: an absent pin module returning an empty pin; dropping the provenance half of the admissibility check; comparing only the major version; accepting any string as a digest; importing the pin module by bare name instead of its package-dotted name; treating an absent direct-URL record as a development install; writing the generated file before rendering it; and removing the wheel target's artifacts entry. The major-version mutation first passed, so the version case was parametrized with the preceding patch release and the mutation re-run; the artifacts mutation first failed on a KeyError, so the reader was given a default and the mutation re-run.
- `S02` The pin loader judges a development installation from the PEP 610 direct-URL record: a record naming a directory is a local source install, no record or an archive record is a built artifact, and an unparseable record counts as a built artifact because that is the answer that refuses a development pin.
- `S03` Guard proofs run as break, run alone, fail on the named assertion, restore, pass: yielding the managed install before the installation sibling; admitting a candidate without comparing its content; adding the PATH tier back to the sibling lookup; swallowing a half-set operator pair; dropping the digest comparison from the launch hold; skipping that comparison for an empty digest; reporting nothing as installed whatever is at the installed name; moving the archive digest comparison after the extraction; dropping the executable digest comparison; retiring every version including the one in use; and naming the operator path variable in a download failure. The PATH mutation first passed, because the planted program failed the digest check instead, so the test was rewritten to plant the pinned content and the mutation re-run; the extract-before-verify mutation first passed, because nothing is kept either way, so the test was given the reported stage order and the mutation re-run.
- `S03` Deliberate difference from the Qdrant provisioner: monitor provisioning takes no cross-process lock. Two runs each stage under a unique name and install with one atomic replace of a file both verified against the same digest, so the loser costs a wasted download and nothing else; a lock would have to be held across a download to save only bytes. Recorded for review.
- `S03` Three more orientation documents under .vaultspec/skills/start-vaultspec-rag/references/ now link to tools/binaries/native.py, which this Step deleted, so the documentation link check fails on 17 such links in all. Those files are user-owned policy sources and were left untouched.
- `S03` Adding the three new monitor environment variables required documenting them in .env.example and docs/configuration.md, which the repository's own coverage, parity and reference gates demand of any declared variable. The monitor rows of docs/configuration.md are therefore already written; S06 owns the removal of manual monitor setup elsewhere in the docs.
- `S04` Guard proofs run as break, run alone, fail on the named assertion, restore, pass: asking the provisioner before the installation role; judging a client installation after resolving in the readiness row; and removing the monitor's label from the provisioning summary.
- `S04` Eight tests in two modules fail on this machine with or without this change, because the machine has neither a compiled monitor nor a running Vite dev server: `test_monitor_access.py's` four Vite cases, and `test_monitor_process_integration.py's` four compiled-lifecycle cases, whose own precondition already required a monitor this checkout does not build. S06 makes the development recipes build one.
- `S04` The monitor step exposed a defect in the S03 provisioner: it asked for the release pins before asking whether an operator had already named a monitor, so an operator-supplied monitor could not satisfy provisioning at all. The entry point now asks about the operator's own executable first, verifies it, and consults no pin in that case.
- `S04` The suite needed a monitor the way it needs a server binary. A session fixture names one through the operator settings, which is a production route and not a substitution; the monitor's own tests clear both settings for their own blocks, so the release's resolution is still exercised.
- `S05` S05 Guard proofs run as break, run alone, fail on the named assertion, restore, pass: removing the bundle's monitor-pin comparison (five refusal cases, DID NOT RAISE); removing the monitor archive's single-member check; dropping the generator-shape validation from the wheel pin reader; returning partial digests instead of refusing an unfinalized target; dropping the executable digest comparison in the staging step; hashing the archive in place of the wheel's pinned archive digest before extraction; moving the pin generation after the package build; removing the monitor archive download from the attestation job; removing the per-target monitor archive requirement from the draft gate; and removing the checksum verification from the monitor archive fetch.
- `S05` S05 The monitors now reach the bundle lane as public release assets rather than as a cross-run artifact handoff: the lane that builds the wheel compiles, finalizes, packs and attaches them, and the bundle lane takes each target's archive off the draft checked against SHA256SUMS exactly as it already takes the wheel, then verifies it against that wheel's own pin before extracting. One attestation call covers the four bundles and the four monitor archives. The frontend digest, which the bundle lane no longer builds, travels to it as a validated dispatch input.
- `S05` S05 A rehearsal of the bundle lane keeps its own frontend job and gains a per-target monitor job, both reaching only a rehearsal, and generates release-provenance pins into the unpublished wheel it builds in that run, so the pin comparison runs for real instead of being waived. The binary-bundle decision allows that equivalent same-run handoff. The alternative, a rehearsal that cannot build a bundle at all, would have removed a maintainer capability nothing authorized removing.
- `S05` S05 RELEASING.md's local reproduction sequence is now stale: it builds the wheel before the monitor, does not generate pins, and calls the bundle recipe without the wheel directory. Left to S06, which owns the documentation.
- `S05` S05 acquisition.yml and tools/packaging/validate.py needed no change. Public acquisition still admits bundle archives only, which the plan leaves unchanged, and channel pointers already refuse a monitor archive because the buildable set is the bundle names, which is what 'not a channel install unit' requires.

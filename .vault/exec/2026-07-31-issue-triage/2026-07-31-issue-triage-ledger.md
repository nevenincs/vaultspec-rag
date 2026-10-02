---
tags:
  - '#exec'
  - '#issue-triage'
date: '2026-07-31'
modified: '2026-10-01'
body_schema: 'body-v2'
body_hash: 'sha256:b0ef1dfd99aaab02df8af1b8303b927ae76e94ff614bbf24392bdc25c1b74080'
related:
  - "[[2026-07-31-issue-triage-plan]]"
---

# `issue-triage` ledger

## Changes

- `S02` `M` `.python-version`
- `S03` `M` `.github/workflows/ci.yml`
- `S04` `M` `.github/workflows/ci.yml`
- `S05` `A` `.github/pull_request_template.md`
- `S06` `M` `src/vaultspec_rag/cli/_service_jobs_presentation.py`
- `S07` `M` `src/vaultspec_rag/cli/_cli_format.py`
- `S08` `M` `pyproject.toml`
- `S10` `M` `src/vaultspec_rag/_index_breadth.py`
- `S11` `A` `.vault/adr/2026-07-25-non-destructive-index-publication-adr.md`
- `S12` `M` `src/vaultspec_rag/storage_ops.py`
- `S13` `A` `.vault/adr/2026-07-25-index-resume-drift-race-adr.md`
- `S14` `A` `.vault/adr/2026-07-31-job-state-invariant-ownership-adr.md`
- `S01` `verify:` `Read-only PR328 contains seven stranded PR327 commits and all are origin-main ancestors` -> `pass`
- `S09` `verify:` `Current read-only common-Git-dir acceptance-search-index directory enumeration` -> `fail`
- `S09` `verify:` `Current common-Git-dir acceptance-search-index enumeration after preserved move count0` -> `pass`
- `S09` `verify:` `Post-passing-full-CPU common-Git-dir acceptance-search-index enumeration count0` -> `pass`
- `S09` `M` `.vault/plan/2026-07-31-issue-triage-plan.md`
- `S09` `verify:` `post-complete-CPU-and-both-GPU acceptance no-recreation=pass;9directories40filesandZIP preservation` -> `pass`

## Notes

- `S02` Historical attribution: 97099b4fdb8852246a64efa18d7a1c1c4c0c168e ci: enforce the pinned interpreter at patch granularity. Historical change attribution only, not complete Step acceptance or original gates PASS.
- `S03` Historical attribution: 97099b4fdb8852246a64efa18d7a1c1c4c0c168e ci: enforce the pinned interpreter at patch granularity. Historical change attribution only, not complete Step acceptance or original gates PASS.
- `S04` Historical attribution: 97099b4fdb8852246a64efa18d7a1c1c4c0c168e ci: enforce the pinned interpreter at patch granularity. Historical change attribution only, not complete Step acceptance or original gates PASS.
- `S05` Historical attribution: 97099b4fdb8852246a64efa18d7a1c1c4c0c168e ci: enforce the pinned interpreter at patch granularity. Historical change attribution only, not complete Step acceptance or original gates PASS.
- `S06` Historical attribution: 5e50c8d474e9e40430d4bb875a866b601969da07 fix(cli): read a non-finite published value as absent, not as zero. Historical change attribution only, not complete Step acceptance or original gates PASS.
- `S07` Historical attribution: 5e50c8d474e9e40430d4bb875a866b601969da07 fix(cli): read a non-finite published value as absent, not as zero. Historical change attribution only, not complete Step acceptance or original gates PASS.
- `S08` Historical attribution: 285effb72921e29f31a2d238ed0993fa2bcb78ba build: stop shipping the test suite in the wheel. Historical change attribution only, not complete Step acceptance or original gates PASS.
- `S10` Historical attribution: 680255c9138d1017c5a38788e5ec8b689fcb1df1 feat(search): warn when every result resolves to one file. Historical change attribution only, not complete Step acceptance or original gates PASS.
- `S11` Historical attribution: b2e3cba53d038c8f228c4cc54f3ee45c6bebbcaf docs(adr): decide how a rebuilt index publishes without destroying the served one. Historical change attribution only, not complete Step acceptance or original gates PASS. ADR historical recorded status supported; do not infer human approval identity or complete acceptance from document addition alone. ADR historical recorded status supported; do not infer human approval identity or complete acceptance from document addition alone.
- `S12` Historical attribution: 1de9f232ea5da6d36d9eaf32c07e618c90a14dd2 feat(storage): run the generation reclaim from the scheduled cycle. Historical change attribution only, not complete Step acceptance or original gates PASS.
- `S13` Historical attribution: e93e5dbeee3ccbd8c8b4cec1b2d5c57772bdf6d2 docs(adr): seam the codebase indexer and give drift a single owner. Historical change attribution only, not complete Step acceptance or original gates PASS.
- `S14` Historical attribution: b3e428aea01145c5680072ec759b32ef96139845 docs(vault): decide generation-level invariant ownership at the persisted boundary. Historical change attribution only, not complete Step acceptance or original gates PASS. One design decision record addition supported; does not establish all five blocking design calls answered. One design decision record addition supported; does not establish all five blocking design calls answered.
- `S01` Actual GitHub PR328 titled ci:rescue the fleet health remediation work stranded off main targets main, merged2026-07-31T08:29:53Z as529c60cfef598d0b3b2918f431c53d5919da9c1b. Its commit list contains all seven PR327 commits; seven current merge-base ancestor checks each exit0. Remote compare of d43f06cd to main has `behind_by0` and that merge-base. The recovery used the existing feature branch rather than a newly named branch; historical branch-creation argv is not claimed. Read-only evidence proves actual fresh PR and delivered ancestry.
- `S09` 2026-10-01 genuine failed original criterion: nine orphan-named directories remain in the resolved common Git directory (suffixes206ee75,4132bd4,59a53d7,92fd661,94b4600,a5732d7,be0e763,ecd524e,fe1e007). Source/tools/dev producer search finds no matching producer; this does not establish safe deletion ownership alone. Explicit user all-warning repair authorizes continuation. Root owns inspection and safe removal plus post-full-test no-recreation proof; no Git filesystem mutation by curator. Earlier history preserved.
- `S09` Root preserved allnine stale pytest-cache directories intact outside Git, with ZIP40-file byte-verification and manifest acceptance-index-preservation.json in ignored review artifacts. Curator current read-only exact common-directory enumeration returns0. This proves current removal from Git while preserving contents; post-successful-full-test no-recreation remains pending because latest full CPU run has one failure. S09 stays open until final evidence.
- `S09` After root-owned just test-python actual5810passed8platformskipszero warnings, current curator read-only exact common Git directory enumeration remains0. Preserved originalnine directories remain outside Git with original byte-verified archives. This proves no recreation after the successful CPU lane only; full GPU lanes are still running/repairing, so S09 remains open for final broader no-recreation confirmation rather than claiming their success.
- `S09` Actual S09 criterion verified AFTER the completed frozen-v12 exactfullCPU5844PASS and fullGPU738resident+76subprocessPASS, allnative0/0warnings. Resolved commonGitdirectory contains NO acceptance-search-index artifacts; no fulltest lane recreated them. Nine originaldirectories/40files remain preserved outside commonGit, exactrelativefile/hash sets and nineZIP hashes+contents match originalmanifest. Evidence .pytest-tmp/acceptance-index-post-full-v12-verification.json and acceptance-index-preservation.json. No artifacts were discarded and no activeprocessdirectory was removed. This supports ONLY S09 currentcriterion closure, not wider historicalStep execution/humanapprovals. Keep older partialattributionnotes and issueplanhistory intact; do not retire entireissueplan because its boxesarechecked.

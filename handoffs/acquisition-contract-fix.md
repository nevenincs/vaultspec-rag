# Acquisition contract handoff

## Root cause

`.github/workflows/acquisition.yml` downloaded the two private raw, target-qualified executables directly from the release URL. It neither consumed the public target archive nor checked the published `SHA256SUMS`, so acquisition could pass against artifacts that a user cannot install. The release-side dispatch was also explicitly nonfatal and promoted without waiting for the six hosted x64/ARM acquisition legs; that producer-side edit is intentionally left to the release-contract owner because it overlaps `binaries.yml`.

## Diff

- Pinned the AlmaLinux, Debian, and Ubuntu container indexes by immutable SHA256 digest; retained all six hosted x64/ARM matrix legs.
- Added a run name carrying the dispatched tag so a caller can identify the exact acquisition run.
- Downloaded the published `SHA256SUMS` and `${tag}-${triple}` archive (`.tar.gz` for Unix and `.zip` for Windows), requiring one exact checksum entry and failing before extraction on missing, duplicate, or mismatched entries.
- Extracted only the two stable executable members with stream extraction (`tar -xOzf`/`unzip -p`), then required the resulting files to be executable before loader probing.
- Left `.github/workflows/binaries.yml` unchanged to avoid overlapping the release-contract owner’s dispatch/promotion block.

## Tests

- `uv run --no-sync python -m dev.actionlint` — pass.
- `uv run --no-sync pytest -q tools/binaries/tests/test_release_workflow.py` — 7 passed.
- `uv run --no-sync pytest -q dev/guards/test_ci_jobs_reach_a_verdict.py` — 3 passed.
- Focused inline contract assertions — pass (six matrix legs, six digest pins, no raw download URL, checksum and both archive extraction paths).
- `git diff --check -- .github/workflows/acquisition.yml` — pass.

## Mutation proof

The focused assertions require the archive URL, `SHA256SUMS`, `sha256sum -c`, and both stable-name extraction paths while explicitly rejecting the former raw download shape. Removing any of those contract strings makes the assertion command fail; no mutation was left on disk or sent to GitHub.

## Required producer-side continuation

In the non-overlapping release-contract block of `binaries.yml`, make acquisition a hard release guarantee: dispatch `acquisition.yml` for `TAG`, fail if dispatch or exact-run identification fails, wait for the dispatched run to reach a terminal conclusion, require `success` after all six `fail-fast: false` matrix legs finish, and only then allow promotion. Do not retain the current warning fallback or promote immediately after dispatch. Use the acquisition `run-name`/tag to avoid watching an unrelated scheduled or concurrent run; keep a bounded wait consistent with the job timeout.

## Mutation proof / external state

No GitHub workflow was dispatched, no release asset was uploaded or changed, and no remote state was mutated. The image digests were read-only registry metadata checks.

## Risks

- The pinned Docker index digests reflect the images resolved during this run; changing them requires a deliberate digest review.
- The six acquisition legs remain Linux loader probes. The `.zip` extraction branch is defensive for the producer contract but is not a Windows execution leg; no Windows loader claim was added.
- `SHA256SUMS` is selected by exact archive filename; a missing or duplicate archive row fails closed, while the release-side aggregate remains responsible for exact all-asset coverage.

---
tags:
  - '#audit'
  - '#monitor-delivery'
date: '2026-10-02'
modified: '2026-10-02'
body_schema: 'body-v2'
body_hash: 'sha256:b6fd3bd0761671afb797a843cbc7277b9c39bfe019cadb7921fd32f78342d178'
related:
  - "[[2026-10-02-monitor-delivery-plan]]"
---

# `monitor-delivery` audit: `Integrated frontend delivery and acquisition review`

## Scope

2026-10-02 review: completed S07, S08, S01-S05 and S10. Diff base `7ede984314b0eb54081105041fbf697f692ecd45`, reviewed target `f7798008` before the bounded extractor correction below. Full implementation and affected test diffs reviewed against the accepted delivery, browser, tooling, binary bundle, release-standard and merge-gate constraints. The reviewer is the single executor; this review was not independent.

Trace: npm lock and one Vite inventory -> committed native Bun pins -> embedded node:http/shared bridge -> resource/signing/floor finalization -> native asset/browser/port/bounds/shutdown evidence -> exact three-command bundle v2 -> channel installation -> actual draft proof and reviewed committed catalog -> independent PyPI admission -> public acquisition. The old Linux loader coverage remains for all backend commands, without running their bootstrappers. No remote dispatch, publication, channel write or default-branch operation occurred.

Verification coverage: reuse the S01-S05 ledger's separately passing Ruff, format, ty/basedpyright, frontend lint/type/format, actionlint/Prettier, affected tests and intentional guard-failure/restoration proofs. Latest combined relevant suite: 176 passing tests at S05. S10 Markdown, generated CLI, version/convention and citation checks pass, with 13 convention tests. The finalized Windows prototype from producer `7f74275b0e28fa5d2f4c786655361760bafd75d6`, version 0.5.1, Bun 1.4.2, SHA256 `89ee0e214637356d99d49f448f414bbe96b560025167bbc3c0ea00f4d05cb7f5`, passes all 94 served assets, native browser rendering, unavailable backend, foreign-origin denial, strict port refusal, upward managed allocation, ignored ambient configuration, request bounds, cancellation recovery and bounded EOF with a partial request. Its smoke report is retained with that owned temporary binary. It is prototype evidence, not a completed release or a current-head four-platform bundle.

Verdict: **PENDING**. No critical or high defect identified. S09 and S06 remain open; the following required evidence is unresolved.

## Findings

### zip-member-mode | medium | Shared extractor admits ZIP special-file modes

At `src/vaultspec_rag/qdrant_runtime/_provision.py:314`, ZIP admission excludes directories and symlinks but does not reject FIFO, device or socket mode bits. The containing archive is independently pinned, and public bundle validation already excludes non-file members, so this is a defense-contract gap rather than an unpinned execution path. Tighten the canonical extractor to regular/unspecified ZIP modes and prove refusal before writing.

### lifecycle-integration | medium | Canonical supervisor is still owned by an unmerged workstream

`tools/monitor/release.py:25` requires the wheel's exact lifecycle, inventory and CLI owners before the frontend job. The original monitor worktree still has uncommitted `monitor_process.py` and daemon/discovery integration, so S09 cannot yet merge the completed owner commit. Earlier real compiled interop used the stable in-flight owner and is not evidence of a merged implementation. Two expected lifecycle ADR links remain dangling in this isolated worktree until that merge. Preserve owner work and review the combined runtime, generated CLI and decision reconciliation after it commits.

### native-offline-proof | medium | Remaining native platforms and OS egress denial are unproven

The Windows prototype proves executable behavior, all local assets and browser rendering. The browser driver blocks external document requests, but neither it nor an empty PATH proves OS-level outbound network denial for the executable. The accepted delivery constraint still requires that isolated condition. Linux x64/ARM64 and macOS ARM64 compilation, loader/signing and native browser results are also absent. `binaries.yml` requires four native reports and prevents a shell-only/source-render result from satisfying archive admission. Obtain those actual host results and executable egress-denial evidence before final PASS.

### public-acquisition-proof | medium | No independently reviewed public release is available yet

`tools/monitor/release-pins.json` intentionally has no entries. Unit guards prove committed authority, producer-before-extraction, unique checksum and publication ordering, but no approved public monitor release has been downloaded and launched. The candidate-only handoff and verifier-only retry are documented in `RELEASING.md`; the first release must independently review the exact four native artifact hashes, land its catalog entry, and then provide public acquisition reports. Keep this evidence gap separate from pre-draft native proof.

### zip-member-mode-resolution | low | Regular ZIP admission is corrected and proven

2026-10-02 follow-up at `3cfbc0c2`: S01 now admits only regular or unspecified ZIP file modes, preserving unique flattened members and verification before extraction. Reviewed the correction and its interactions with Bun provisioning, public acquisition and Qdrant. Ruff across qdrant_runtime/binary tooling, affected formatting, ty and strict basedpyright pass. The combined monitor, packaging, workflow, Bun, Qdrant and CLI progress suite passes 176 tests. An uninterrupted bypass removed the mode predicate: five intended DID NOT RAISE assertions failed; exact source bytes were restored and the same five guards passed. This resolves zip-member-mode. Other reviewed runtime/workflow inputs are unchanged; lifecycle/native-offline/public evidence gaps keep the verdict PENDING.

## Recommendations

Resolve zip-member-mode through the approved S01 extractor scope. Leave the final verdict pending until the lifecycle owner commits and S09 merges it, all native and offline evidence arrives, and the first reviewed public acquisition completes. Then append the changed interactions/results to this audit without repeating unchanged analysis.

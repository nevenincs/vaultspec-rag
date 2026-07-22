---
tags:
  - '#audit'
  - '#code-document-index-boundary'
date: '2026-07-22'
modified: '2026-07-22'
related:
  - "[[2026-07-22-code-document-index-boundary-plan]]"
  - "[[2026-07-21-code-document-index-boundary-adr]]"
---

# `code-document-index-boundary` audit: `S47 per-kind policy fingerprints`

## Scope

Audit `W01.P01.S47` against the accepted per-kind generation identity boundary. Review source
profile, ordered route and ignore semantics, transform targets, schema, extractor isolation,
persistent/operation membership, execution separation, closed kind access, determinism, and
pickle reconstruction.

## Findings

Status: **PASS**. No critical, high, medium, or low findings remain within S47 scope.

Membership signatures include the policy schema, source profile, ordered explicit routes,
ordered persistent ignores, transform targets and precedence, and operation-only excludes in
the operation projection only. Target flips change both origin and destination membership.

Content signatures filter extractor semantics by content kind. Invocation, options, version,
error behavior, timeout, batching, decoder, parser, chunk, transform schema, and applicable
byte caps remain deterministic without coupling an unrelated kind's extractor changes.
Execution mode stays outside membership/content identity. Focused Ruff, Ty, pickle,
extractor-change, target-flip, profile-change, exclude, and closed-kind probes pass.

## Recommendations

Proceed to `W01.P01.S07`. Verify real configuration loading, ordered routing, one-owner
enforcement, immutable fingerprints, and mutation-free migration refusal.

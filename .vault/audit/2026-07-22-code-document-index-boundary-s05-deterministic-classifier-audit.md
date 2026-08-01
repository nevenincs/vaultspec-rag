---
tags:
  - '#audit'
  - '#code-document-index-boundary'
date: '2026-07-22'
modified: '2026-07-22'
body_hash: 'sha256:b62b790309cf5f6e6e31f46f32d173fbcf2f002e7e80c9d34fe130b6482ece16'
related:
  - "[[2026-07-22-code-document-index-boundary-plan]]"
  - "[[2026-07-21-code-document-index-boundary-adr]]"
---

# `code-document-index-boundary` audit: `S05 deterministic classifier`

## Scope

Audit `W01.P01.S05` against the accepted content-boundary decision. Review ignore
precedence, explicit ownership agreement, source-profile admission, parser separation,
stable reasons, and path-layout independence.

## Findings

Status: **PASS**. No critical, high, medium, or low findings remain within S05 scope.

Ignore decisions short-circuit all routes and profiles. Matching root routes and transform
targets must agree on one owner or classification raises `AdmissionPolicyError`. The
explicit-only profile rejects unowned paths, while the conventional profile admits only its
versioned source-extension set.

Parser capability is consulted only after admission. Explicitly routed formats retain their
declared owner and may use either a registered structured parser or the generic text splitter;
parser-only formats no longer establish code membership. Focused Ruff, Ty, and real behavior
probes pass.

## Recommendations

Proceed to `W01.P01.S06`. Resolve routing, preprocessing, decoding, execution mode, and
normalized fingerprints into one immutable policy snapshot.

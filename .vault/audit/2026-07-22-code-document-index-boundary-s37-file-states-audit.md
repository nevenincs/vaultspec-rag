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

<!-- FRONTMATTER RULES:
     tags: one directory tag (hardcoded #audit) and one feature tag.
     Replace code-document-index-boundary with a kebab-case feature tag, e.g. #foo-bar.
     Additional tags may be appended below the required pair.

     Related: use wiki-links as '[[yyyy-mm-dd-foo-bar]]'.

     modified: CLI-maintained last-modified stamp; set at scaffold time,
     refreshed by mutating CLI verbs and vault check fix; never hand-edit.

     DO NOT add fields beyond those scaffolded; metadata lives
     only in the frontmatter. -->

<!-- LINK RULES:
     - [[wiki-links]] are ONLY for .vault/ documents in the related: field above.
     - NEVER use [[wiki-links]] or markdown links in the document body.
     - NEVER reference file paths in the body. If you must name a source file,
       class, or function, use inline backtick code: `src/module.py`. -->

# `code-document-index-boundary` audit: `S37 explicit file states`

## Scope

Audit `W01.P01.S37` against the accepted explicit-outcome boundary. Review convergence,
retry ownership, stable vocabulary, canonical path/hash identity, constructor invariants,
pickling, error classification, and remediation.

## Findings

### convergence-stability | high | resolved with evidence-aware rejection state

The first draft converged every policy rejection. Convergence now accepts configuration-only
rejections directly, requires a canonical source hash for source-derived size/binary
rejections, and keeps probe failures non-converged.

### retry-ownership | high | resolved by service-owned retry classification

Only `extract_retryable` is intrinsically retryable. Decode and chunk failures remain visible
non-success states whose retry behavior is decided by later service policy, preventing an
unconditional retry loop.

### canonical-identity | medium | resolved across tokens, paths, hashes, and enums

File and job tokens now agree. Paths reject absolute, drive-qualified, traversal,
backslash, and noncanonical aliases. Success evidence requires lowercase BLAKE2b-512 hex.
Direct construction rejects plain strings in every closed enum field, preserving identity
comparisons and retry projections after deserialization.

Status: **PASS** after remediation. No critical, high, medium, or low findings remain open.
Focused Ruff, Ty, state-matrix, convergence, retry, error/remediation, path, hash, enum,
import, and pickle probes pass.

## Recommendations

Proceed to `W01.P01.S47`. Derive kind-aware membership and content signatures from the
resolved policy and explicit file-state authority.

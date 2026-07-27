---
tags:
  - '#research'
  - '#active-corpus-conformance'
date: '2026-07-27'
modified: '2026-07-27'
related:
  - "[[2026-07-27-vault-corpus-curation-audit]]"
---
# `active-corpus-conformance` research: `Active corpus conformance options`

## Findings

### Retained preamble

The live vault has 951 body-section diagnostics across 518 documents; 109 affected documents are current and 409 predate 2026-07-20. The requested zero-warning outcome cannot be reached by filling sections without inventing historical evidence. This research compares preserving the active corpus with a reversible archival cutover.

### The failures are mixed into every feature

`vault check body-sections --json` on 2026-07-27 reports failures across 115 mixed features and no feature for which every live document fails. Existing feature-wide archive would therefore archive clean documents too. `vaultcore.query.archive_feature` is not a suitable selector.

### The current archive surface cannot select the failing set

The existing archive command accepts a feature tag and moves matching documents sequentially. It has no individual-document manifest or transactional preflight. A new owning command must validate an explicit path manifest, reject collisions and escapes, preserve document bytes, and report the outcome before the corpus is cut over.

### Archival is the only non-fabricating zero-warning option

The scanner excludes `.vault/_archive`, while graph resolution treats archived stems as historical targets. Archiving the exact failing documents preserves evidence and makes the active corpus conforming. Filling 951 missing sections would require historical sources not available in the affected records; deleting loses evidence.

## Sources

- `file:.vault/audit/2026-07-27-vault-corpus-curation-audit.md`
- `file:src/vaultspec_core/vaultcore/checks/body_sections.py`
- `file:src/vaultspec_core/vaultcore/query.py`
- `file:src/vaultspec_core/vaultcore/scanner.py`

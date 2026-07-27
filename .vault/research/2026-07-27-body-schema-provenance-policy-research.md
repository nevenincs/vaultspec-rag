---
tags:
  - '#research'
  - '#body-schema-provenance'
date: '2026-07-27'
modified: '2026-07-27'
related: []
---

# `body-schema-provenance` research: `Policy`

The live corpus must be retained and validated against immutable, historically accurate section contracts. The current checker retroactively derives requirements from mutable templates, so it produces template-drift warnings rather than evidence of missing architectural content.

## Findings

### Current validation is retroactive rather than document-specific

`check_body_sections` extracts required `##` headings from the current template for every scanned document. It was introduced by commit `e1418dfd`; the research template gained `## Sources` in `837b640d`, demonstrating a later template change being applied to earlier records. The restored corpus therefore reports 994 diagnostics despite retaining substantive historical documents.

### A baseline ledger preserves provenance without suppressing validation

A committed baseline keyed by project-relative path, body SHA-256, and immutable schema identifier can attest existing documents to their historical contract. A changed, newly created, or unlisted document cannot acquire legacy status merely by declaring it. That is stricter than date cutoffs or broad exemptions.

### Immutable contracts keep future authoring strict

New scaffolds should declare the current schema. The checker resolves contracts from a versioned Core registry rather than the mutable template. Historical schemas remain enforced against their original section rules; a later template change cannot silently reclassify old evidence.

### Alternatives

A date cutoff is easy but cannot distinguish backfilled or altered files. Bulk filling headings fabricates provenance. Archival or deletion removes live governance. A blanket legacy exemption hides malformed new documents. The evidence favors an immutable registry plus hash-attested baseline; the ADR must settle its location and review authority for ambiguous files.

## Sources

`src/vaultspec_core/vaultcore/checks/body_sections.py:103`

`src/vaultspec_core/builtins/templates/research.md`

commit `e1418dfd`

commit `837b640d`

`2026-07-27-active-corpus-conformance-research`

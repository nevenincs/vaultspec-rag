---
tags:
  - '#exec'
  - '#body-schema-provenance'
date: '2026-07-27'
modified: '2026-08-14'
body_schema: 'body-v1'
body_hash: 'sha256:5e27364cc5a11dff3e522ed6ca017e497848b99b15dea1b0068396b89950af23'
step_id: 'S04'
related:
  - "[[2026-07-27-body-schema-provenance-plan]]"
---

# Prove restored corpus and new documents validate correctly

## Scope

- `checks tests and vault check body-sections`

## Description

Prove that the existing corpus and newly created documents both validate correctly against the immutable schema contracts.

## Outcome

Both directions hold, measured rather than asserted.

The historical corpus: `vault check body-sections` reports zero warnings over 2,284 documents, 1,983 of which carry no schema stamp at all. Unstamped records resolve to their own historical contract and pass.

New documents: the twelve execution records scaffolded during this session were created through the owning verb, stamped `body-v1`, and validate - after their required sections were authored. Two of them initially failed the same check for empty `## Description` and `## Notes` sections, which is the gate working: a scaffolded document with unwritten sections is not silently accepted.

The one document that warned at the start of this pass was a `body-v1` record missing `## Scope`, not a legacy record. It was fixed by writing the section, which is the correct remedy for a strictly-validated new document and the one a baseline entry would have wrongly suppressed.

## Notes

The distinction this step turns on is the one the decision was written to protect: a historical document gets its own contract, and a current document gets the current contract with no way to opt out. Both were observed here on real documents rather than constructed cases - 1,983 legacy records passing untouched, and a post-contract audit correctly refused until its missing section was written.

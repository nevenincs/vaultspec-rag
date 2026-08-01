---
tags:
  - '#exec'
  - '#storage-conformance'
date: '2026-07-25'
modified: '2026-07-27'
body_hash: 'sha256:559cad5aeb2a27870da4b2b8d44a7d2d43410184a145972c39e4da5d41a8a326'
step_id: 'S14'
related:
  - "[[2026-07-25-storage-conformance-plan]]"
---

# Report the per-collection verdict and stamped identity in the storage survey payload

## Scope

- `src/vaultspec_rag/storage_survey.py`

## Description

Plan evidence: `2026-07-25-storage-conformance-plan` marks `P03.S14` closed for Report the per-collection verdict and stamped identity in the storage survey payload.

## Outcome

`NamespaceSurvey` gains a `models` map of collection name to stamped dense
model, populated from the manifest entry in `classify_namespaces` and carried
through the `/storage/survey` payload.

The field is defaulted rather than required. A second construction site surveys
a live server without a manifest read; defaulting lets it report nothing about
provenance instead of reporting a value it never looked up, and avoids editing a
file another team is concurrently changing.

An empty map means the namespace predates stamping. The survey has always been
able to say how much is stored; this is the first thing it can say about what
made it.

## Notes

Template evidence: intro_commit=2f3068c7d9236d0ef7c4a81177caabf640399f5b; template_commit=2f3068c7d9236d0ef7c4a81177caabf640399f5b:.vaultspec/templates/exec-step.md requires Description, Outcome, and Notes. This repair preserves the retained record text and adds no new implementation claim.

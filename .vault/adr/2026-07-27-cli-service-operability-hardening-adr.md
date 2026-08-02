---
tags:
  - '#adr'
  - '#cli-service-operability-hardening'
date: '2026-07-27'
modified: '2026-08-02'
body_hash: 'sha256:9f1a438a3f60de71ba7ca75455aec935bb45aba683cb3a77bb2a166f12a3f35d'
related:
  - '[[2026-06-11-cli-service-operability-hardening-code-review-audit]]'
  - '[[2026-07-27-cli-service-operability-hardening-grounding-research]]'
  - '[[2026-08-02-service-quiesce-paused-state-legibility-research]]'
---

# `cli-service-operability-hardening` adr: `Preserve CLI and service operability guarantees` | (**status:** `accepted`)

## Problem Statement

The completed hardening plan needs a governing decision record so the CLI and service operational guarantees remain explicit rather than surviving only in audits and execution history.

## Considerations

`2026-07-27-cli-service-operability-hardening-grounding-research` records the retained audit and plan grounding. The existing implementation and execution history must remain traceable without restating the audit evidence here.

## Considered options

Leave the feature governed only by audits and its plan: rejected because the vault check correctly identifies the missing decision. Record the established operability boundary in an ADR: accepted.

On forwarding structured service failures, an allowlist of known keys was rejected: it drops by default, so each field the service adds is discarded until a second author remembers to widen it, and the loss is silent at both ends. Forwarding what the service published, minus the keys the entry point owns, was accepted.

## Constraints

This ADR retrofits the decision record from retained feature evidence; it does not claim unrecorded rationale or alter the completed implementation.

A structured failure the service publishes reaches the caller intact. An entry point renders or reshapes such a payload; it does not decide which of the service's own fields the caller is allowed to see. Where an entry point must exclude a key it owns, it excludes that key by name and forwards the rest, so an unrecognised field survives rather than disappears.

## Implementation

Keep CLI feedback, service lifecycle behavior, and operational diagnostics governed by the completed plan and its execution records. Future changes to those guarantees must amend or supersede this ADR.

Structured error forwarding inverts from selection to exclusion. The JSON path carries the service's published fields through, less the entry point's own; the human path renders the fields it has a presentation for and is not the reason a field fails to reach a caller at all. Retryability is the case that proves the rule: a service that has said a condition is transient must not have that erased between the socket and the operator, because the caller's next move depends on it.

## Rationale

The audit-grounded feature already has a coherent implementation inventory. A concise ADR restores the missing decision layer and gives future work one governing record.

## Consequences

The feature is now structurally complete: research grounds, this ADR decides, the plan tracks, and the audits retain findings.

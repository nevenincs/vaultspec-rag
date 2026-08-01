---
tags:
  - '#audit'
  - '#service-job-control'
date: '2026-07-22'
modified: '2026-07-22'
body_hash: 'sha256:832ea1fbb5472520b38d63286df7fefe7f240062448ee55b2792c3b8790d82ce'
related:
  - "[[2026-07-21-service-job-control-adr]]"
  - "[[2026-07-21-service-job-control-plan]]"
---

# `service-job-control` audit: `s25 health rollups`

## Scope

Audited `W04.P12.S25`: bounded health aggregation, canonical and legacy record
deduplication, paused and transitional visibility, stall truthfulness, and
structured last-failure selection.

## Findings

### s25-health-rollups | medium | newest failure was source-order dependent

Resolved. The health rollup now selects the failed record with the greatest
canonical update timestamp after deduplication instead of preferring all
canonical records over newer legacy activity.

### s25-health-rollups | medium | focused test used shared persistence

Resolved. The focused health test binds the manager status directory to its
temporary test root and restores configuration after clearing the singleton.

## Recommendations

Accept S25 after the required corrections. Continue authenticated route
verification under S26.

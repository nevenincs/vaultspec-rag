---
tags:
  - '#audit'
  - '#generation-accounting'
date: '2026-09-01'
modified: '2026-09-01'
body_schema: 'body-v2'
body_hash: 'sha256:6fc929cad10c877fe766214f011b2f4700da0a15830c1cb318d5e0033a408afc'
related: []
---

# `generation-accounting` audit: `recovered branch review`

## Scope

Reviewed PR #437 against its main-branch diff, generation lifecycle invariants,
run-ledger finalization, storage deletion safety, and service-client timeout behavior.

## Findings

### clean-generation-drift | critical | Drift cleanup can mutate the served collection

Clean builds write to a generation collection, but `CodeDriftOwner` deletes stale point
IDs through the served collection before publication. A resumed clean generation can
therefore remove live search content and retain the stale points in its build target.

### resumed-skip-or-vanish | high | Retained upserts cannot converge to a skipped or vanished outcome

When a resumed path already has current-generation upsert evidence, converting its state
to `preprocess_skipped` or `extract_retryable` leaves storage evidence without an indexed
state. Finalization correctly refuses the contradiction, causing the run to fail.

### reindex-timeout | medium | The documented reindex timeout is not resolved at call time

The configuration setting is validated and documented, but `_try_http_reindex` passes an
import-time constant. Environment or configuration overrides never reach the HTTP call.

### resumed-empty-source | high | Retained upserts can still become an unresolved empty rejection

The empty-source handler replaces an indexed state with a policy rejection without retiring
current-generation storage evidence. The same storage-first retirement used for skipped and
vanished outcomes is required before finalization can accept the result.

### target-table-preparation | high | Targeted code writes can initialize the served collection

The code upsert and deletion paths resolve an explicit generation target but table
preparation previously used the implicit served collection. A clean build could therefore
create or reconcile the served collection before publication.

### pre-publication-route-reconciliation | critical | Generation reconciliation can purge served rows

Before publishing a clean code generation, route reconciliation scanned and deleted via
the implicit served code collection and could also remove cross-kind document origins.
Those mutations must occur only after the new generation becomes served; same-kind build
cleanup must explicitly address the generation collection.

### resumed-private-build-evidence | high | Missing clean-build storage can be mistaken for served evidence

When reopening an in-progress clean generation, evidence validation previously consulted
the implicit served collection before the lifecycle bound its build target. If the private
generation collection had been lost while the old served collection remained, the run could
reuse committed units and publish a partial replacement. Validation must derive and probe
the generation's deterministic private collection directly, invalidating it when absent.

### prefix-delete-eviction | high | Prefix deletion loses the root required to evict resident service state

Server-storage prefix deletion removes the manifest entry before service eviction looks up
the root from that manifest. The normal prefix form therefore cannot identify the torn-down
project and can leave resident collection pointers after deletion. Preserve the attributed
root through deletion and use it for eviction.

## Recommendations

- Define one active-collection ownership path for drift cleanup and retirement.
- Preserve the storage-first, ledger-second durability sequence when retiring resumed
  paths, with a regression covering both skip and vanished outcomes.
- Resolve the reindex timeout through the existing runtime settings helper and cover a
  live override at the HTTP-call boundary.
- Route retained empty-source outcomes through the existing retirement owner and add the
  same real ledger-and-storage regression coverage as the other resolved outcomes.
- Preserve explicit code collection ownership through table preparation and cover an
  absent-served-collection build.
- Separate pre-publication generation cleanup from post-publication cross-kind route
  reconciliation, then prove the served collections remain unchanged until publication.
- Validate resumed clean-generation evidence against its own private collection and prove
  a lost in-progress target invalidates instead of resuming it.
- Carry a prefix deletion's root identity into resident-service eviction and cover the
  prefix-addressed deletion path.

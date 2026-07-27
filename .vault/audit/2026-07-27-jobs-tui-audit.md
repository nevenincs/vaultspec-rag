---
tags:
  - '#audit'
  - '#jobs-tui'
date: '2026-07-27'
modified: '2026-07-27'
related:
  - "[[2026-07-27-jobs-tui-adr]]"
  - "[[2026-07-27-jobs-tui-plan]]"
  - "[[2026-07-27-jobs-tui-research]]"
---

# `jobs-tui` audit: `what shipped, and what blocks releasing it`

The plan closed every step, and closing them was not the same as delivering the
thing. Operating the interface against a live service found six defects the
suite had passed over, and two of them were not in the interface at all. This
records the divergence between what `2026-07-27-jobs-tui-adr` decided and what
the branch actually contains, and what stands between that branch and a release.

## Scope

The `feat/jobs-tui` branch, and `fix/job-delete-legacy-ring` alongside it.
Assessed by running the interface against a live daemon and by executing the
gates, not by reading the diff.

## Findings

### The tests passed while the feature did not work

Every defect below was live while the suite was green, because the fixtures
asserted the implementation's own assumptions back at it. The pattern was
uniform: a test proved a request had been SENT and never that the view
converged on what the service then held. A stateful fake - one whose reads
reflect its own mutations - finds all of them; a fixture cannot.

This is the same failure the operator-feedback record warned about, one level
up: that record established that a rendered artefact must be verified on
rendered bytes, and these tests did assert on rendered bytes. They asserted on
the rendered bytes of a state the service would never actually produce.

### The delete defect was service-domain, and the interface could not have fixed it

The service keeps two job registries - a durable canonical history and a
volatile in-memory ring - and serves their union. Delete removed only the
canonical half, so deleting a job that still had a ring shadow left the row
present and simultaneously unaddressable: listed by the collection, absent from
the detail route, and therefore refused by every control that resolves through
detail. One mechanism produced both "delete does nothing" and "the job id is
not found".

The ADR assumed the control endpoints were correct and only their presentation
was missing. That assumption was wrong, and no amount of interface work would
have reached it.

### Restarts, not eviction, destroy job history

The volatile ring does not survive a process boundary; only running jobs are
persisted, and terminal ring records have no restore path. Observed totals fell
239 -> 186 -> 179 across the session with a single delete issued. The bounded
ring was never full - both bounds are well above the observed counts - so the
capacity explanation was wrong. Each drop was a restart discarding the volatile
half, and the count landed exactly on the size of the persisted set.

Operationally this also means any session on the machine running a service stop
destroys job history for every other project sharing that daemon.

### Four defects were invisible until the interface was operated

Controls were destroyed before they were sent, because every request kind
shared one worker group and the periodic poll cancels its group. Long labels
wrapped and pushed each row's second line out, silently deleting the progress
bar, the job id and the initiator. A timeout or a server error rendered as
"zero jobs, refreshed just now", making a wedged daemon indistinguishable from
an idle one. The log toggle did nothing above the split width, because its
style rule existed only for the narrow layout.

None are subtle in operation. All were invisible in review and in the suite.

### The delivered scope exceeded the decision

The branch carries a service-status header - storage footprint, seat
occupancy, service health - that no plan step called for, and a durable
requested-state indication with a deletion tombstone that the ADR described
only as "renders as requested". The estimate was also split in two: a measured
rate is published for any advancing step, while a remaining time is published
only where there is a completion point to subtract from.

One asked-for field cannot be delivered: connected clients. The service
publishes no connection or client accounting anywhere. The header reads the key
a future payload would carry and renders absent until then, rather than
substituting a lease count that answers a different question.

### The estimate is unproven in production

It carries tests and no demonstration. Producing one requires a daemon running
this code, and the running daemon predates it, so the interface correctly
reports that the service does not estimate. Until a real indexing job is
observed carrying a non-null estimate, the feature is asserted rather than
shown.

### The repository is not currently releasable, independently of this work

Five module splits sit half-committed on the default branch: a consumer
committed, its module left untracked. The result imports on the authoring
machine's working tree and nowhere else, so a fresh checkout cannot import the
package, and three test modules cannot even be collected. One of the five has
since been committed; three remain.

No gate detects this. The linter has no rule for a shadowed duplicate
implementation, and the test job fails at collection rather than reporting a
cause. It is visible only by checking a tracked path against the import that
names it.

## Recommendations

- Treat a stateful fake service as the default for any view over a mutable
  resource. Assert convergence on the backend's state after an action, and
  assert the intermediate frame, not only the final one.
- Operate a live surface against a real service before calling it delivered.
  Every defect here was found that way and none were found by review.
- Land the delete fix ahead of the interface. It is smaller, self-contained,
  and corrects data behaviour rather than presentation.
- Merge with a conventional-commit subject. The release tooling reads those
  prefixes, and the interface would otherwise produce no changelog entry and no
  version bump.
- Remove the local scaffolding before release and re-verify. It exists only to
  make a broken default branch importable; the branch is releasable at the
  point it needs none.
- Add a gate that fails when a tracked import names an untracked module. That
  is the whole of the half-committed-split class, and nothing currently sees it.

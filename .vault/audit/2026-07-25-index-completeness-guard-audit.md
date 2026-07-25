---
tags:
  - '#audit'
  - '#index-completeness-guard'
date: '2026-07-25'
modified: '2026-07-25'
related:
  - "[[2026-07-25-index-completeness-guard-plan]]"
  - "[[2026-07-25-index-completeness-guard-adr]]"
---

# `index-completeness-guard` audit: `the latch is closed and the silence is broken; the truncation window remains`

## Scope

The landed change against the decision that authorised it: the published-breadth
claim, the quantitative evidence predicate, the search-time completeness signal,
and the guard tests behind all three. Also in scope, because the issue this work
answers named it as unestablished: whether the collapse mechanism can now be
stated.

## Findings

### mechanism | high | the collapse mechanism is established, and two of the issue's open hypotheses are settled

The reported failure - a code index answering normally from a fraction of its
corpus - is fully accounted for by five links, each verified in the source
rather than inferred:

A clean rebuild drops the collection and recreates it before repopulating it
incrementally, so the truncation window is real and deliberate. An *incremental*
run escalates itself to that clean path without any operator action, on either
embedding-input-format drift or content-shaping config drift; both call the
locked full-index implementation with the clean flag set. Metadata publication
is the final phase of the run, after chunking, embedding and stale purging, so a
failure anywhere earlier leaves the collection truncated and the previous
sidecar - still describing the whole corpus - untouched. The evidence predicate
that guards the incremental path asked only whether the collection existed, so a
present-but-short collection passed it. Every later incremental run then diffed
against the stale sidecar, classified every surviving file as unchanged, and
published success.

This settles two of the three things the issue explicitly declined to conclude.
The observation that no operator-run code index job preceded a collapse is
consistent rather than contradictory: the job existed and was automatic, reached
through a watcher-driven incremental run that escalated itself. And the question
of whether the collection was genuinely truncated or merely ranking badly is
answered by direct measurement rather than inference - a read-only scroll of the
affected collection found 302 points across 5 distinct paths against 421 files
claimed by the sidecar, with all 302 dense vectors distinct and none degenerate.
Retrieval was correct over one percent of the corpus.

The issue's suspicion that the plausible section count might be read from a
different source than the searched vectors is refuted: both resolve to the same
live collection, the count through the store's collection-count helper and the
search envelope's indexed count from that same call.

### cross-collection-interference | low | the issue's remaining hypothesis is neither confirmed nor refuted

The issue noted that a vault index job was active during at least one sighting
and suggested cross-collection interference. The mechanism above requires no
such interference, and nothing in this work produced evidence either way. It is
not ruled out; it is simply unnecessary as an explanation, and no attempt was
made to test it.

### truncation-window | medium | detection landed, prevention did not

What landed detects a truncated collection and heals it; it does not stop one
being created. The destructive drop at the head of a clean rebuild remains, so
the window between the drop and a successful publication still exists, and the
search-time signal rather than the window's absence is what protects a caller
during it. The decision recorded this as a deliberate deferral with reasons -
build-then-swap touches the storage layer and the per-root collection-prefix
scheme, and needs disk headroom for a duplicate collection - so this is
conformance with the decision, not a gap against it.

### breadth-fact | low | the file count the decision named was not persisted, on canonical-code grounds

The decision's implementation note and the plan's first Step both named a file
count alongside the point count. Only the point count landed. The predicate
compares points, and the claimed file count is already exactly the number of
non-reserved entries in the same sidecar, so a persisted copy would be a second
home for a fact that could only drift from the entries it counts. The Step was
corrected through the owning verb rather than left describing work that was
deliberately not done.

### guard-tests | low | every guard was proven able to fail, and two candidate proofs were rejected

Eleven guards across the predicate, the service emission and the CLI rendering
were each broken, observed failing on the assertion they name, restored, and
observed passing. Two candidate mutations were rejected as evidence rather than
recorded: one failed inside the production call with a type error instead of on
its assertion, which proves the branch raises rather than that the test watches
it; the other would have mutated a test's own stub service, which proves only
that the stub is wired up. Both rejections are recorded where the tests are.

A pre-existing proof claim in the chunk-parity test's docstring, asserting a
failure direction that had never been run, was executed rather than committed on
trust. It holds as written.

### adapter-discipline | low | the completeness fact is settled once and never recomputed

The fact is computed on the code search path from the count that path already
takes, so no store round trip was added, as the decision required. It travels as
a conclusion carrying its figures, so the CLI renders without comparing counts
and the MCP tool needed no change at all - its response model already permits
extra fields and names the index-state block as a carried diagnostic. The local
in-process path fills the same block from the count it had already taken, so it
too pays nothing extra.

## Recommendations

Land non-destructive clean publication - build into a shadow collection and swap
atomically - to remove the truncation window rather than detect it. The decision
already records this as the strictly better fix and defers it; a follow-on ADR
must decide how a shadow collection interacts with the per-root
collection-prefix scheme and what disk headroom is required before a swap is
attempted.

Check whether the vault and document indexers carry the same existence-only
predicate, and whether their search surfaces have any completeness signal. This
work covered the code domain only because that is where the failure was
observed; nothing suggests the other two are immune, and the research left the
question open.

Repair the two unit failures this work surfaced but does not own: a commit-gate
regression test asserting a hook configuration file that a later commit deleted,
and a daemon status test asserting an exact key set that a later commit widened.
Neither relates to index completeness, and both were left to their owners
rather than edited to make a suite green.

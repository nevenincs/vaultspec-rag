---
tags:
  - '#audit'
  - '#server-watch-observability'
date: '2026-07-30'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:63e362b383045e2990b20a9e4d0d1e5e7481ac88fbb6be149b3c03218d543ce4'
related:
  - "[[2026-07-29-server-watch-observability-plan]]"
---

# `server-watch-observability` audit: `server-watch-observability closeout review`

## Scope

The delivered dual-lane watch observability surface: the search-activity
ledger, its token-gated route, the service-client transport mapping, and the
console that renders both lanes. Reviewed as the closeout for the plan's final
step, which requires a formal review rather than a green test run.

## Findings

### search-outcome-tone-drift | high | the console marked fewer outcomes as failures than the service classifies

The display held its own copy of the failure-outcome set and had already
fallen behind the classifier. Two admission-side outcomes were missing, so a
registry refusing every search on the box rendered in the neutral tone, and
only the outcome word distinguished it from a completed search. A console
exists to make that condition visible at a glance. Fixed: the vocabulary now
lives beside the error kind it belongs with, in the domain both the route and
the in-process path already import from, and the guard is over the classifier
rather than the client, so an outcome added to the route that no surface can
classify fails whether or not anyone remembers the console exists.

### client-requires-query-field | medium | a supported service mode made the client declare the service broken

The console required query text on every record, while the ledger's
serializer deliberately omits it and publishes a redaction flag whenever it
is asked not to disclose. The whole lane rendered as an invalid response.
Fixed: exactly one of the two must be present, so a record that merely lost
the field is still rejected, and a redacted row says redacted rather than
unavailable.

### truncation-silence | medium | unfiltered counts were rendered beside a bounded row set

The title carried counts computed over every retained record while the table
held the bounded projection, with nothing to say the remainder existed. The
served figure was already validated and then discarded. Fixed.

### unbounded-default-projection | medium | an unfiltered read served whatever the ledger held

The route applied no cap when the caller named no limit, so a read could
serialize the full retention in one pass while every other route waited.
Fixed: bounded by default, widened on request.

### filterability-unreachable | medium | the route's filters ship programmatic-only

The route implements state, type, root, request-id and since filters, and the
transport maps all of them, but no console binding, CLI verb or tool reaches
them. An operator cannot ask for only the failed searches through any shipped
surface. Deliberately not fixed: this is scope the plan did not carry, and
inventing an operator surface at closeout is a larger decision than a defect
repair. Recorded here so the closeout is honest about what shipped.

### transport-param-allowlists | medium | four hand-copied query-parameter key sets

Each of the logs, jobs, search-activity and storage-survey mappings restates
the parameter names its route reads, with nothing linking the two sides; an
unknown parameter is dropped rather than rejected, so a filter added on one
side silently does nothing through the client. Deliberately not fixed: this
is the fourth instance and predates this work, so the fix is seam-wide.

### finite-retention | checked, clean

Verified by mutation rather than by reading: with the eviction removed, the
retention guard fails on the assertion its docstring names, and it further
asserts the evicted text is unreachable through every serialization and
through an identifier filter. The bound is enforced on every insertion path.

### query-privacy | checked, clean

Traced end to end. The text is held only in the process-local bounded ledger,
never serialized to disk; structured logs carry identifiers, counts and
timings but no query and no result body; the route is token-gated before
anything is read; and the console routes the text through a printable-only
filter, so terminal escapes in a query cannot reach the terminal.

## Recommendations

The filter surface and the parameter-allowlist seam are both architecturally
significant and neither belongs in a closeout patch.

A follow-on decision should settle where the route parameter contract lives,
so that a route and its client cannot disagree about which parameters exist.
The present arrangement drops an unrecognised parameter silently, which
presents as a filter that does not work rather than as an error.

A second decision should settle whether bounded activity review is an
operator-facing surface at all. If it is, it needs a binding that reaches the
filters already implemented; if it is not, the filters are a programmatic
contract and should be described as one.

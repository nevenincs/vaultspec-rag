---
tags:
  - '#adr'
  - '#citation-gate-coverage'
date: '2026-07-25'
modified: '2026-07-25'
related:
  - "[[2026-07-25-citation-gate-coverage-research]]"
---

# `citation-gate-coverage` adr: `a dated stem is a citation in any form, and tools is in scope` | (**status:** `accepted`)

## Problem Statement

The citation gate is the mechanical half of the no-dev-metadata rule, and it
reported clean on a live violation. A gate that returns clean on a real
violation is worse than no gate: it converts "nobody checked" into "the check
passed" and consumes the attention that would otherwise have gone looking. Its
coverage boundary needs deciding explicitly rather than inheriting whatever the
original patterns happened to reach.

## Considerations

- The reported cause - an unvisited module docstring - is not the actual escape;
  `2026-07-25-citation-gate-coverage-research` establishes both the real holes.
- Prose cites a document by its bare dated stem far more often than by its full
  filename, so a suffix requirement excludes the commonest forbidden shape.
- Tracked source that the walk never reaches is a hole no green run can reveal.
- The prose-only restriction is load-bearing in the other direction: vault-shaped
  fixture filenames are values the indexer is tested against, and a scan reaching
  string values would fail the whole test corpus.

## Considered options

- **Widen the walk to more AST surfaces.** Rejected: the walk already reaches
  every prose surface, so this changes nothing while looking like a fix.
- **Match any dated stem, with or without a type suffix.** Chosen. It is the
  shape the rule forbids, and no product vocabulary uses a dated kebab
  identifier.
- **Match a bare date.** Rejected: prose is allowed to say when something
  happened. Only a kebab feature tail turns a date into a document identifier,
  so the tail must contain a letter.
- **Leave the tooling surface citation-exempt.** Rejected: it is tracked source
  under the same rule, and a live citation was sitting in it.

## Constraints

- The gate's own source stays exempt from the citation scan: it spells every
  forbidden shape out as a pattern literal and again in prose to explain it, so
  scanning itself reports its own definitions as findings.
- Detection has to become provable. A gate whose scan can only run against the
  live checkout can be confirmed green but never shown able to go red, which is
  precisely the failure being corrected.

## Implementation

The dated-stem pattern drops the document-type suffix requirement and instead
requires the stem tail to contain a letter. The tooling surface is walked for
citations on the same terms as the package, with the gate's own file as the sole
exemption. The scan entry points take their repository and tooling roots as
parameters defaulting to the live checkout, so both the patterns and the walk can
be exercised against a throwaway tree.

## Rationale

The knockout point is that the reported symptom and the actual defect were
different. A fix aimed at the docstring walk would have shipped a green gate over
an unchanged hole - the same failure shape a second time, and harder to find
because the issue would have been closed. Widening the stem pattern addresses
what was genuinely escaping, and parameterising the roots is what converts the
gate from something observable only in its passing state into something whose red
direction is demonstrable.

## Consequences

- The gate now fails on the commonest citation shape, and on citations anywhere
  in the tooling surface.
- One live citation surfaced in a tool and was removed.
- The stem pattern is broader, so a legitimate dated kebab identifier in prose
  would need an anchored allowlist entry. None exists today.
- Prose in non-Python tracked files remains unscanned; the research names this as
  deliberately out of scope, and it stays open.

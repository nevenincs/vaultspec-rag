---
tags:
  - '#adr'
  - '#code-stands-alone-boundary'
date: '2026-07-23'
modified: '2026-07-23'
body_hash: 'sha256:bf626483d130de3044c4755bb7942fb4f0d3a3ed6294aaba1780f395eba3dafe'
related:
  - "[[2026-07-22-codebase-dedup-centralization-audit]]"
---

# `code-stands-alone-boundary` adr: `the one-way code-and-vault citation boundary` | (**status:** `accepted`)

## Problem Statement

Tracked source, test, and configuration files had accumulated citations to
development records in their docstrings and comments - dated vault stems, plan
and Step identifiers, decision-enumeration tokens, feature-named ADR references,
and `.vault/` document paths. Each such citation points a reader at where a
constraint was decided rather than stating the constraint, and it points into
`.vault/` and `.vaultspec/`, which are removable development scaffolding layered
over the codebase: the product ships and is vendored without them. The moment
that scaffolding is absent, every citation is a dangling reference to something
that no longer exists, and the reader is sent nowhere. A decision was needed on
the reference direction between code and the vault, and on whether to enforce
it mechanically.

## Considerations

- The `.vault/` corpus and `.vaultspec/` harness are removable scaffolding, not
  part of the codebase; a shipped wheel or a consumer's checkout carries neither.
- The constraint a citation stands in for is almost always already stated in the
  surrounding prose, leaving the citation a trailing provenance stamp that loses
  nothing when removed.
- The product's own domain vocabulary - indexing `.vault/` markdown, parsing
  `adr/` doc ids, advertising `type:adr`, and vault-shaped test-data values - is
  behaviour and data, not prose pointing at a record, and must survive any sweep.
- The `2026-07-22-codebase-dedup-centralization-audit` established that the
  codebase already holds a consistent single-owner discipline; an
  uncited-constraint rule is the documentation analogue of that same discipline.
- A mechanical gate can enforce "no citation token remains" but cannot enforce
  "the sentence still parses once the token is gone" - that stays a human read.

## Considered options

- Leave the citations in place (status quo). Rejected: they dangle the instant
  scaffolding is removed, and they send a reader to a document instead of
  teaching the rule.
- Convert each citation to a stable external identifier or link. Rejected: it
  still couples code to a record identity that outlives its usefulness, and the
  identifier is itself scaffolding.
- A one-way boundary: vault documents cite code by `path:line` locator, and code
  cites nothing in the vault - state the constraint in place, or name a codified
  rule a reader can act on, never the record. Chosen.

## Constraints

- The boundary is asymmetric by construction: it constrains only the
  code-to-vault direction; vault-to-code citation by locator is unchanged and
  still required.
- Enforcement depends on a citation-gate lint that walks docstring and comment
  tokens only - never string-literal values - so the product's `adr/` /
  `type:adr` domain vocabulary and synthetic vault-shaped test data are
  untouched; the grammar-integrity half depends on a diff read per removal.
- No parent-feature or frontier-technology risk: the change is
  documentation-and-lint discipline over already-shipped code.

## Implementation

Source, test, and configuration code states the constraint a former citation
carried directly, so a reader learns the rule rather than where it was decided.
Where the surrounding prose already states the rule the trailing citation is
deleted; where a citation is the grammatical head or object of its clause it is
delete-and-repaired, not clipped, so no stranded fragment remains. A codified
rule may be named in place of the decision that produced it, because a rule name
is a constraint a reader can act on without the vault open. The invariant is
enforced rather than asserted by a boundary check that fails when a tracked
source file names a development record, walking docstrings and comment tokens
while skipping string-literal values. Opt-in git commit trailers remain the one
sanctioned linkage channel from a commit back to a record.

## Rationale

The one-way boundary wins on a knockout criterion the alternatives cannot meet:
a citation into removable scaffolding is a guaranteed dangling reference in every
artifact that ships or is consumed without the vault, while the constraint stated
in place travels with the code and needs nothing external to be actionable.
Removing the provenance stamp loses nothing - the surrounding prose already
carries the rule in almost every case - and keeping it couples the code to a
document identity that outlives its usefulness. The choice mirrors the
single-owner discipline the `2026-07-22-codebase-dedup-centralization-audit`
found the codebase already holds: one home for a fact, referenced one way. A lint
gate makes the mechanical half enforceable rather than aspirational; the residual
grammar read is accepted as an irreducibly human check and called out so a
reviewer performs it on every removal.

## Consequences

Code reads as self-contained: the rule a constraint encodes is legible without
the `.vault/` corpus present, and a shipped or vendored copy carries no dangling
pointers. The lint gate catches any reintroduced citation token in CI and
pre-commit, so the boundary cannot silently erode. The cost is a standing
reviewer obligation the gate cannot automate - a blindly clipped citation that
strands its sentence produces zero test and zero lint signal, so each removal
needs a diff read for grammar. The boundary is one-way only: vault documents
still cite code by locator and must stay current against it, a separate
maintenance surface this decision does not address. The decision is codified as
the rule `code-cites-nothing-in-the-vault`, which is the operational form a
reader and the gate both act on.

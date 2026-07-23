---
name: code-cites-nothing-in-the-vault
---

# Code cites nothing in the vault

## Rule

Tracked source, test, and configuration code must not name a development record.
No dated vault stem, plan or step identifier, decision-enumeration token
(`D7`, `QR4`, `Q5`), feature-named ADR reference ("the `mcp-search-scope` ADR"),
`.vault/<type>/` document path, or codification-candidate name may appear in a
docstring or comment. State the constraint the record decided directly, so a
reader learns the rule rather than where it was decided.

The reference direction is one-way: vault documents cite code by `path:line`
locator, and code cites nothing in the vault. The `.vault/` corpus and the
`.vaultspec/` harness are removable scaffolding; a citation pointing into them is
a dangling reference the moment the scaffolding is gone.

The product's own domain vocabulary is not a citation and stays: indexing
`.vault/` markdown, parsing `adr/` doc ids, advertising `type:adr`, and naming a
codified rule are code and behaviour, not prose pointing at a record. Vault-shaped
test DATA - a synthetic `2026-01-01-x-adr.md` fixture filename, a real doc id in a
ranking rubric - is a value in an expression, not a citation, and also stays.

## Why

A comment that reads "per the `2026-06-01-module-split-adr`" tells a reader where
to go, not what to do, and the place it sends them is scaffolding that may not be
present. The constraint the record actually carried - "this module is one half of
a split; do not reintroduce the monolith" - is what the reader needs, and it is
almost always already stated in the surrounding prose, with the citation a
trailing provenance stamp. Removing the stamp loses nothing; keeping it couples
the code to a document's identity that outlives its usefulness.

The citation-gate lint check enforces the mechanical half of this. It walks
docstrings and comment tokens (never string-literal values, which is what keeps
the vault-shaped test data clean) and fails on any reintroduced citation token.
Run it with `just dev lint citations`.

## How

- **Good:** when a comment cites a record, recover the constraint and state it in
  place. Delete the trailing citation when the surrounding prose already states
  the rule; state the rule directly when it does not.
- **Good:** name a codified rule (`index-workers-stay-cpu-only`) instead of the
  decision that produced it - the rule name is a constraint a reader can act on
  without the vault open, not a document identifier.
- **The grammar-integrity check the gate cannot make.** The gate enforces "no
  citation token remains". It cannot enforce "the sentence still parses once the
  token is gone" - that is a human or model read. Before removing a citation, ask
  whether the token is the grammatical head or object of its clause. "See the
  `mcp-service-client` ADR" and "the false positive QR4 forbids" are built AROUND
  the citation: deleting it strands "See the" or "the false positive forbids".
  Those need delete-and-repair - drop the whole clause or restate it. A trailing
  "(QR2)." or "per the `...-adr`." is pure provenance: clean-delete. A reviewer
  must read the surrounding sentence on every removal, because a citation removal
  that breaks the grammar produces zero test signal and zero lint signal - only a
  line-by-line diff read catches it.
- **Bad:** "See the ADR for the decision", "(D7)", "per the
  `2026-06-13-provisioning-setup-adr`", "plan W04.P07.S25", or a Sphinx `:doc:`
  role into `.vault/` - all of which point a reader at removable scaffolding.
- **Bad:** deleting a citation token blindly and leaving "the calls for" or "See
  the a thin service client" - a grammatically broken fragment is worse than the
  citation, and the gate will not catch it.

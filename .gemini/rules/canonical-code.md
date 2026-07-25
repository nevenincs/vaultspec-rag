---
name: canonical-code
trigger: always_on
---

# Canonical code

## Rule

- One behaviour, one implementation. Delete the other.
- Never add a forwarding shim, a delegating wrapper, or a compatibility alias.
- Never keep a symbol alive for tests. If only tests reach it, delete it and
  repoint them at the production path.
- Never leave a re-export in the module a symbol moved out of.
- Never mirror logic that lives elsewhere. Import it.
- Search by meaning before writing anything. Prove no implementation exists.
- Collapse the duplicate when you find one. Never carry both across a seam.

## Why

- A second implementation drifts. The copy that never gets the fix is the one
  that ships the bug.
- A test-only path proves nothing about production. Parity asserted against code
  production no longer runs asserts nothing at all.
- A shim reads as an abstraction and is dead weight. It hides the real caller and
  survives every later refactor.
- Grep cannot find a function whose name you cannot guess. Semantic search can.

## How

- Search behaviour plus domain nouns before adding a helper, method or module.
- Read the candidates. Semantic search locates; it does not enumerate. A sampled
  negative is not a negative.
- Treat extraction as a dedup opportunity, not a move.
- Check callers before keeping anything. Zero production callers means delete.
- Repoint tests at the production entry point in the same change that removes
  the path they were exercising.
- Bad: a method whose body is one call into the module that now owns it.
- Bad: importing a name only to re-export it for callers that could import it
  directly.
- Bad: two functions that differ only by a constant or a label string.
- Bad: keeping the old path "until callers migrate". Migrate them now.

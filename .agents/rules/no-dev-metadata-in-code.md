---
name: no-dev-metadata-in-code
trigger: always_on
---

# No dev metadata in code

## Rule

- State the constraint. Never state where it was decided.
- Never write any of these in source, tests, config, comments or docstrings:
  - a dated vault stem
  - a wave, phase or step id
  - a feature name taken from the vault
  - a decision-enumeration token
  - a `.vault/` path
  - a codified rule name
- Vault documents cite code by `path:line`. Code cites nothing.

## Why

- The vault and the harness are removable. A pointer into them dangles once they
  are gone.
- A pointer says where to go. A constraint says what to do.

## How

- Delete the pointer when the prose already states the constraint.
- State the constraint first when it does not, then delete the pointer.
- Repair the sentence. A pointer is usually the object of its clause; deleting
  the token alone strands the sentence.
- Read every removal in the diff. No linter and no gate sees broken prose.
- Keep product vocabulary: indexing `.vault/` markdown, parsing `adr/` doc ids,
  advertising `type:adr`.
- Keep vault-shaped test data. A fixture filename is a value, not a citation.

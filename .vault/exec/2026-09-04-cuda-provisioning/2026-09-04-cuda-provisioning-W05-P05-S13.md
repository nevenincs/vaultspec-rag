---
tags:
  - '#exec'
  - '#cuda-provisioning'
date: '2026-09-04'
modified: '2026-09-04'
body_schema: 'body-v2'
body_hash: 'sha256:bbfb43a481873fa8ad6d4c6c8e3983c5ed874c954c59a73f84ba3fc85bb78535'
step_id: 'S13'
related:
  - "[[2026-09-04-cuda-provisioning-plan]]"
---

# Correct the installation account of what a blocked reinstall does, what a bad wheel URL returns, and how a repair is refused

## Scope

- `docs/installation.md and README.md`

## Changes

- `M docs/installation.md`
- `M README.md`

## Notes

Four corrections, each reproduced against real uv before being written down.
Only a blocked removal is destructive: a wheel that cannot be fetched, a tag
that matches nothing, an empty cache offline - all fail before uv replaces
anything and leave the environment and receipt untouched. The prose said a
forced reinstall "fails half-way" without saying which failures do that, which
teaches an operator to fear the wrong thing.

A holder is now described as two kinds rather than one. The executable inside
the tree is the obvious one; the working directory inside the tree is the one
operators miss, and it blocks removal even when the program has nothing to do
with this project.

The installer's behaviour changed under the earlier Steps and the docs still
described the old one. It refuses and hands over the command, naming holders by
pid with the remediation each needs, and `--no-tool-repair` is the opt-out -
not `--no-torch-config`, which governs only the pyproject step and was
previously misdescribed as covering this.

A control-plane-only install is documented as a supported state: install
completes, the service still refuses to start, and the remedy is choosing the
GPU extra rather than repairing anything.

No 404 copy existed to correct - the wheel host answers a missing wheel with
403, but no page promised otherwise.

On gates: `docs/installation.md` is outside the repository's markdown gate,
which covers the readme, the harness sources and the vault. The file does not
satisfy mdformat and carries one MD022 finding in HEAD, both predating this
change. Rather than reformatting a file the project does not gate, the change
was checked for not making it worse: the finding count is the same before and
after. `README.md` is gated and passes both tools.

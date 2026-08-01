---
tags:
  - '#exec'
  - '#code-document-index-boundary'
date: '2026-07-22'
modified: '2026-07-22'
body_hash: 'sha256:187cf0555ce8eca45dfd01ac0c5caccd17e1243680b1eb8ca34bf8478cd79259'
step_id: 'S134'
related:
  - "[[2026-07-22-code-document-index-boundary-plan]]"
---

# Reconcile CLI help-text metavar expectations with the current Typer rendering convention

## Scope

- `src/vaultspec_rag/tests/test_cli_watcher.py`
- `src/vaultspec_rag/tests/test_cli_mcp_control_parity.py`
- `src/vaultspec_rag/tests/test_cli_server.py`

## Description

- Retarget the watcher project-argument help expectation to the current
  required-positional rendering and add a negative assertion against the root
  spelling in that same form (`src/vaultspec_rag/tests/test_cli_watcher.py:222`).
- Retarget the projects-unload help expectation the same way
  (`src/vaultspec_rag/tests/test_cli_server.py:477`).

## Outcome

The new rendering is the intended convention, so the expectations were the stale
side, and they were retargeted in a way that preserves what they were actually
for.

The convention was confirmed at its source rather than inferred from the failure
text. The installed CLI framework overrides the underlying library's metavar
construction with a version whose own comment states it is modified to include
the argument name: a required positional renders as its lowercase name in
braces, an optional one in square brackets. The underlying library, by contrast,
still uppercases the parameter name - which is precisely the older rendering
these expectations were written against. Every argument behind these four
failures is a required string with no explicit metavar and no default, so braces
are the correct output for all of them. Nothing in the command definitions
changed; the rendering did.

The assertions were not merely relaxed to match. Their purpose is a naming
contract - that these arguments speak of a project and never of a root - and
that purpose survives the rendering change intact. Each now asserts the exact
braced form, which is more specific than the bare word would have been, and each
gained a negative assertion against the root spelling in the same braced form.
The original negative assertion only excluded the old uppercase spelling, so
after the rendering change it could no longer have caught a rename to a root
argument - the regression it exists to prevent. Asserting the exact metavar in
both directions restores that.

The four failures are three parametrizations of the watcher help test plus the
single projects-unload help test, which accounts for the count exactly.

## Notes

Both touched tests were run targeted by the author and passed. The full suite
and the static gates were not run by the author.

A third module was named in the Step assignment that does not exist in the tree.
A search for the old spelling across every test found it in exactly two modules,
and those two account for all four failures, so no work is believed missing.

The assertions are now coupled to a rendering convention owned by a third-party
dependency rather than by this project. That is a real if minor fragility: a
future upgrade that changes the convention again will surface here as the same
class of failure. It was accepted rather than worked around, because the
alternative - asserting only the bare lowercase word - would collide with the
ordinary prose of the arguments' own help text and stop distinguishing the
naming contract from an incidental substring match.

A name collision hid a second failure carrying this Step's apparent shape, and
the distinction matters enough to record. The Step's scope named a file that
does not exist in the tree; a test *function* of that same name lives inside the
watcher module. The metavar work fixed the watcher module's parametrized help
test and the server module's, which is why the count reconciled exactly, while
the identically-named function went untouched and unexamined. Two things shared
one name and only one was ever looked at.

That function is not this Step's drift and was deliberately left unmodified. It
asserts the exact set of tools the agent-facing surface exposes, and it fails
because that surface now carries twelve where it asserts five. The extra seven
arrived together in one commit dated the same day, an ancestor of the current
head, belonging to this feature's own adapter work rather than to any dormant or
pre-existing change.

The assertion was not updated, because doing so would have reconciled a real
divergence by editing the guard that detects it. An accepted decision record
narrowed that surface to search and index-refresh, removed lifecycle and
administration from it entirely, removed the status tool by name, and closed by
warning that administration tools would re-accrete the moment someone wanted an
agent-side shortcut. Three of the seven additions are exactly what it removed. A
document domain does need to be reachable, and the search and index-refresh
additions extend the permitted categories to the third domain, but the governing
decision for this feature does not list that surface among the contracts it
amends, and its only reference to it concerns parsing a closed source-type enum
rather than authorizing new tools.

So the failure is a decision-versus-code conflict rather than a stale
expectation, its resolution belongs in the surface or in a superseding decision
rather than in this test, and it was escalated for that call instead of being
closed here.

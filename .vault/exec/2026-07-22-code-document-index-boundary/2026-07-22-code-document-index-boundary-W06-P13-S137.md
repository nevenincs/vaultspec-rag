---
tags:
  - '#exec'
  - '#code-document-index-boundary'
date: '2026-07-22'
modified: '2026-07-22'
body_hash: 'sha256:891afbbc9aa24f214939693bcc7e35ca6f42d344424b9341ef0531e39d498951'
step_id: 'S137'
related:
  - "[[2026-07-22-code-document-index-boundary-plan]]"
---

# Reconcile the command reference with the shipped source-type vocabulary so the document kind and the combined alias appear wherever a type is accepted

## Scope

- `docs/cli.md`

## Description

- Correct the search source option to the four-value closed vocabulary and name
  all three aliases (`docs/cli.md:153`).
- Correct the index source option the same way, keeping its alias default
  (`docs/cli.md:100`).
- Correct the clean argument signature and its argument row
  (`docs/cli.md:118`, `docs/cli.md:126`).
- Correct the dry-run availability statement, which named one source type and
  excluded two that are supported (`docs/cli.md:102`).
- Correct the index exit-code list, which named a rejection code that no longer
  exists (`docs/cli.md:114`).
- Widen the index and search command summaries, which described two domains of
  three (`docs/cli.md:92`, `docs/cli.md:141`).

## Outcome

The command reference now states the same source-type vocabulary the commands
themselves already stated, and the two reference pages agree.

The most important fact about this Step is what it did not touch. Every option's
own help text was already correct before this change: the search option already
carried the four-value metavar and all three aliases, the index option already
read as the four values with aliases, and the clean argument already named the
fourth value. No enum, no help string, and no behaviour was altered. This was
the reference page catching up to shipped behaviour, not a behaviour question,
and the distinction is worth stating plainly because the failure mode it rules
out - a documented contract that the code never implemented - is the more
serious one and was specifically checked for.

That check was run deliberately rather than assumed. Each of the three commands
was read against the closed vocabulary before any edit, confirming the help text
and the enum agreed with each other in every case. Had they disagreed, the Step
would have stopped rather than proceeding, because a page can only be reconciled
against code that is itself self-consistent.

Three corrections beyond the three assigned were made, all in the same command
sections and all the same class of source-type drift. The dry-run description
said the flag was valid only for source code or the combined default; the
validation actually rejects only the vault selection and supports code,
document, and combined. The exit-code list named a rejection code that does not
appear anywhere in the source, the real one having been renamed when the
supported set widened. And both command summaries described two domains where
three now exist. Leaving those in place while correcting the lines beside them
would have produced a page that was accurate in its tables and wrong in its
prose, which is a worse outcome than either being uniformly stale.

The vocabulary and framing follow the search-and-index guide, which already
documented the four values and three aliases correctly, so a reader moving
between the two pages meets one description rather than two.

## Notes

The MCP reference page was left untouched by instruction. Its tool-count claim
is entangled with an accepted scope decision currently under separate research,
and editing it now would have pre-empted that reconciliation in exactly the way
this session already avoided once.

The three additional corrections are flagged rather than buried, because they
widen the Step beyond its written scope. Each was adjacent to an assigned line,
in the same table or the same command's prose, and each was a statement about
source types that the shipped vocabulary had falsified. A reviewer who disagrees
with that judgement can revert them independently; they are separable from the
three assigned lines.

No verification was run by the author beyond reading the source declarations
that each corrected line describes. This is a prose change to one reference page
with no executable assertions behind it, so the markdown gate is the only
relevant check and it belongs to the harness operator.

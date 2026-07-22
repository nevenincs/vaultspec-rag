---
tags:
  - '#audit'
  - '#mcp-search-scope'
date: '2026-07-22'
modified: '2026-07-22'
related:
  - "[[2026-06-30-mcp-search-scope-adr]]"
  - "[[2026-07-21-code-document-index-boundary-adr]]"
---

<!-- FRONTMATTER RULES:
     tags: one directory tag (hardcoded #audit) and one feature tag.
     Replace mcp-search-scope with a kebab-case feature tag, e.g. #foo-bar.
     Additional tags may be appended below the required pair.

     Related: use wiki-links as '[[yyyy-mm-dd-foo-bar]]'.

     modified: CLI-maintained last-modified stamp; set at scaffold time,
     refreshed by mutating CLI verbs and vault check fix; never hand-edit.

     DO NOT add fields beyond those scaffolded; metadata lives
     only in the frontmatter. -->

<!-- LINK RULES:
     - [[wiki-links]] are ONLY for .vault/ documents in the related: field above.
     - NEVER use [[wiki-links]] or markdown links in the document body.
     - NEVER reference file paths in the body. If you must name a source file,
       class, or function, use inline backtick code: `src/module.py`. -->

# `mcp-search-scope` audit: `live MCP surface has drifted beyond the accepted scope boundary`

## Scope

A single failing test, investigated rather than repaired. The failure was originally mis-grouped with a batch of unrelated help-text drift and assumed to be a stale expectation; pulling its actual assertion showed it is a guard enforcing an accepted decision, and that the code no longer honours that decision.

The test asserts the exact set of tools the server exposes, and its comment states the constraint and names the governing record. It is one of the few places where an architectural boundary is enforced executably rather than described in prose, which is why it caught this at all.

## Findings

### mcp-surface-exceeds-accepted-scope | high | The exposed tool surface is more than twice the size the accepted decision permits, and includes categories that decision explicitly removed

The governing record is accepted and has not been superseded. Its first decision names the in-scope surface exhaustively - two search verbs, two index-refresh verbs, and one search-adjacent read-only retrieval tool - and closes with the sentence that nothing else is a tool. Its second decision removes mutating and observability administration from the surface entirely, listing project eviction, watcher control, service-state inspection, storage survey, jobs, and logs, on the stated reasoning that an agent-facing search tool does not manage the daemon it depends on.

The live surface exposes twelve tools. Five match the decision. The remainder fall into three groups, and they are not equivalent in kind.

The first group is the document-kind siblings: document search, document index-refresh, and document cleaning. Two of these are arguably what the decision would have said had a third content kind existed when it was written - they are the same verbs the decision admits, applied to a kind introduced later by the indexing boundary work. That is a defensible extension, but it was never recorded as one.

The second group is aggregate convenience: an index-refresh-everything verb and a combined-search verb. These are not new kinds; they are unions over existing ones, and the decision's exhaustive phrasing does not admit them.

The third group is the one the decision explicitly prohibits: an index-status observability tool and cleaning verbs that mutate stored state. The second decision removed observability and mutating administration by name and by rationale, so these are not omissions from an enumeration - they are the categories that enumeration was written to exclude.

The drift is therefore not a single event. Some of it is plausible growth that outran its record, and some of it contradicts a decision that is still in force.

### executable-boundary-guard-was-failing-unnoticed | medium | The only executable enforcement of this boundary had been red long enough to be miscategorised

The guard did its job - it failed. But it sat inside a batch of failures attributed to unrelated help-text drift, and the attribution was made from the test's name and neighbours rather than from its assertion. It was only when the batch was reduced to a single remaining failure that anyone read the traceback.

The lesson is about triage rather than about this boundary: a guard enforcing an architectural decision is indistinguishable, in a summary line, from a brittle expectation about formatting. Grouping failures by apparent similarity without reading each one is how a decision violation gets filed as cosmetic drift.

## Recommendations

Do not resolve this by editing the test to match the code. The test is the enforcement mechanism for an accepted decision, and updating its expectation would convert a detected violation into a ratified one without anyone deciding anything.

The reconciliation needs a decision record, and the three groups should be settled separately rather than as one question.

The document-kind tools should almost certainly be admitted, by amending the accepted record to state its rule in terms of content kinds rather than by enumerating five names. The original decision's logic - search and index-refresh are in scope, administration is not - extends to a third kind without strain, and the record simply predates that kind existing. An enumeration that must be edited every time a kind is added is the wrong shape for the rule it is trying to express.

The aggregate verbs need an argument rather than an assumption. They are convenience unions, and the question is whether an agent-facing surface benefits from them or whether they invite exactly the broad, expensive calls the narrowing was meant to discourage.

The observability and mutating-cleanup tools should be removed or the second decision should be explicitly reversed with its reasoning addressed. That decision did not merely omit them; it named them and gave a reason. Leaving them in place while the record stands is the only part of this that is straightforwardly a violation rather than an undocumented extension.

Whichever way each group is settled, the guard test must be updated as the last step of that work and never as a way of making the suite green. If the surface is meant to be kind-parametric, the guard should assert that rule rather than a literal list, so it keeps enforcing the boundary as kinds are added.

---
tags:
  - '#audit'
  - '#mcp-search-scope'
date: '2026-07-22'
modified: '2026-07-22'
body_hash: 'sha256:179c7195f794412100cca9c881c21d4b43266a5dbaa3c48116f3afa1cf266e94'
related:
  - "[[2026-06-30-mcp-search-scope-adr]]"
  - "[[2026-07-21-code-document-index-boundary-adr]]"
---

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

### correction-the-expansion-was-authorised | high | The framing above is wrong: every added tool traces to a checked Step in an accepted plan, and the real failure is that two decision processes never met

Subsequent research overturns this audit's opening hypothesis and the correction is material enough to record rather than quietly amend. Nothing here was accretion or an agent-side shortcut. All seven tools arrive in a single commit, and each maps to an explicit Step scoped by path to the tools module - one Step for the two search tools, one for the two reindex tools, one for the two clean tools, one for the status tool. Those Steps execute an accepted decision record whose sixth decision names the protocol explicitly. There is an unbroken authorising chain from an accepted record to every tool.

What went wrong is a process failure between two accepted records rather than a violation by an implementer. The later record contains no reference to the earlier narrowing, does not list it among its related documents, does not supersede it, and nowhere acknowledges that an accepted decision had removed status and cleaning from this surface by name. The narrowing was not weighed and rejected; the evidence suggests it was never consulted. That distinction changes the remedy: authorised divergence between two records is reconciled by deciding which governs, whereas a shortcut is reverted.

The interpretive crux sits in one word of the later record. Its sixth decision requires the listed surfaces to parse a closed vocabulary exhaustively. Whether that is a requirement about EXHAUSTIVENESS - that whatever a surface exposes must handle all three kinds - or about EXPOSURE - that the surface must offer each kind's tools - is not settled by its text. The implementing Steps read it as exposure. The narrower reading would have extended search and reindex to the document kind and stopped there. Four of the seven tools turn entirely on that question.

### conformance-guard-amended-to-match-the-widening | high | One executable guard was rewritten in the same commit that widened the surface, while still citing the authority of the record it now contradicts

The conformance test was amended alongside the expansion: the status tool moved out of its removed set and into its expected set, and a clean-tool group was added. Its module docstring still states that it asserts the surface decided by the narrowing record. The guard therefore now claims the authority of a decision whose text forbids part of what the guard asserts.

A second, independent guard - the command-line parity test - was left untouched and still asserts the five original names. That is the test that has been failing. So the mechanical enforcement the narrowing record demanded did exist and did fire; it was simply carried inside a larger batch of unrelated failures and read as expectation drift rather than as a boundary breach.

The lesson is narrow and worth keeping: when a guard and the thing it guards are edited in the same change, the guard stops being independent evidence. A reviewer seeing both in one diff has to ask which one moved first.

### three-accepted-records-disagree-on-parity | high | An unresolved contradiction predates this expansion by seven weeks and was in force while it was designed

An accepted observability record mandates full parity between the command-line surface and the protocol surface for server state. An accepted scope record explicitly retires the parity framing and removes those same tools by name. A third accepted record supersedes five earlier protocol decisions but does not supersede the observability one. All three remain accepted.

So the corpus held two incompatible answers to the parity question before any of this session's work began, and it held them while the tools in question were being designed. Whatever is decided about the tools themselves, that contradiction has to be resolved, because leaving three accepted records in mutual disagreement guarantees the next implementer can cite an accepted decision for either outcome.

## Recommendations

Do not resolve this by editing the test to match the code. The test is the enforcement mechanism for an accepted decision, and updating its expectation would convert a detected violation into a ratified one without anyone deciding anything.

The reconciliation needs a decision record, and the three groups should be settled separately rather than as one question.

The document-kind tools should almost certainly be admitted, by amending the accepted record to state its rule in terms of content kinds rather than by enumerating five names. The original decision's logic - search and index-refresh are in scope, administration is not - extends to a third kind without strain, and the record simply predates that kind existing. An enumeration that must be edited every time a kind is added is the wrong shape for the rule it is trying to express.

The aggregate verbs need an argument rather than an assumption. They are convenience unions, and the question is whether an agent-facing surface benefits from them or whether they invite exactly the broad, expensive calls the narrowing was meant to discourage.

The observability and mutating-cleanup tools should be removed or the second decision should be explicitly reversed with its reasoning addressed. That decision did not merely omit them; it named them and gave a reason. Leaving them in place while the record stands is the only part of this that is straightforwardly a violation rather than an undocumented extension.

Whichever way each group is settled, the guard test must be updated as the last step of that work and never as a way of making the suite green. If the surface is meant to be kind-parametric, the guard should assert that rule rather than a literal list, so it keeps enforcing the boundary as kinds are added.

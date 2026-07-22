---
tags:
  - '#research'
  - '#mcp-search-scope'
date: '2026-07-22'
modified: '2026-07-22'
related:
  - "[[2026-06-30-mcp-search-scope-adr]]"
  - "[[2026-07-22-mcp-search-scope-surface-drift-audit]]"
---

<!-- FRONTMATTER RULES:
     tags: one directory tag (hardcoded #research) and one feature tag.
     Replace mcp-search-scope with a kebab-case feature tag, e.g. #foo-bar.
     Additional tags may be appended below the required pair.

     Related: use wiki-links as '[[yyyy-mm-dd-foo-bar]]'.

     modified: CLI-maintained last-modified stamp; set at scaffold time,
     refreshed by mutating CLI verbs and vault check fix; never hand-edit.

     DO NOT add fields beyond those scaffolded; metadata lives
     only in the frontmatter. -->

<!-- LINK RULES:
     - [[wiki-links]] are ONLY for .vault/ documents in the related: field above.
     - NEVER use [[wiki-links]] or markdown [label](path) links in the document body.
     - Cite external sources as bare URLs. Cite code, commits, packages, and
       standards as inline backtick locators: `src/module.py:42`, commit
       `abc1234`, `package@1.2.3`, RFC 9110. -->

<!-- DOCUMENT BOUNDARY:
     Research grounds; the ADR decides. Frame the option space with evidence
     and trade-offs; at most name the option the evidence favors and what
     the ADR must settle. Never record the decision here - a decision
     outside the ADR forks and goes stale when the ADR chooses otherwise. -->

# `mcp-search-scope` research: `reconciling the accepted surface boundary against the shipped tool set`

<!-- Lead: the question, why it matters to `mcp-search-scope`, and what was
     concluded - the evidence picture, not a decision. -->

The live Model Context Protocol surface exposes twelve tools where
`2026-06-30-mcp-search-scope-adr` permits five and says "Nothing else is an MCP
tool". The question was whether this is drift to be reverted or a decision the
corpus has not caught up with.

It is neither, exactly. Every one of the seven additional tools was authorised
by an explicit Step in an accepted plan, executing a later accepted ADR that
names the Model Context Protocol among the surfaces it governs. So the code did
not escape the process; it followed a second process that never engaged the
first. The two accepted decisions now contradict each other directly, one of
them by name on two specific points, and neither is marked superseded.

Underneath that sits an older unresolved conflict: an accepted ADR from
2026-06-01 mandates full parity between the command-line and Model Context
Protocol surfaces for server state, and the 2026-06-30 decision explicitly
retires the parity framing and removes those same tools. That conflict predates
the current drift by seven weeks and was never adjudicated, which means the
corpus has contained two incompatible answers to "should these surfaces mirror
each other" for the whole period in which the newer tools were designed.

## Findings

<!-- One ### subsection per line of inquiry. Claim first, evidence after.
     Anchor every non-obvious claim to a re-fetchable locator (URL,
     `file:line`, commit SHA, `package@version`, RFC number). Link, do not
     copy. Pin versions, dates, numbers. State each fact once: link what a
     related vault document already records; do not repeat what an earlier
     section establishes. Name alternatives and why kept or rejected. State
     what was not investigated. Cut anything that changes no decision. -->

### Every additional tool was authorised by an explicit Step, not accreted

This is the finding that most changes the shape of the problem, and it
contradicts the starting hypothesis that the surface accreted informally.

`git log -S` over the tool definitions in `src/vaultspec_rag/mcp/_tools.py`
dates all seven additions to a single commit, `f5c04db8`, on 2026-07-22, titled
"feat(adapters): expose document and combined domains". Each maps to a checked
Step in `2026-07-22-code-document-index-boundary-plan`, all four scoped to that
module by path:

- `W05.P10.S73` - document and combined search tools, producing `search_documents`
  and `search_combined`.
- `W05.P10.S117` - document and combined reindex tools, producing
  `reindex_documents` and `reindex_all`.
- `W05.P10.S125` - targeted document and combined clean tools, producing
  `clean_documents` and `clean_all`.
- `W05.P10.S126` - document count, policy, generation, and degraded-state status
  tools, producing `get_index_status`.

Those Steps execute `2026-07-21-code-document-index-boundary-adr`, whose D6
names the Model Context Protocol explicitly in the list of surfaces that must
parse a closed source-type enum and branch exhaustively. So there is an
authorising chain from an accepted ADR through an accepted plan to each tool.
No tool here lacks a record, and the "quick agent-side shortcut" the scope ADR
predicted in its own Consequences is not what happened.

### The authorising ADR never engaged the decision it contradicts

D6's sentence lists index, search, clean, status, jobs, HTTP, the Model Context
Protocol, storage schema, snapshot and migration, and readiness as surfaces that
must parse the closed enum exhaustively and return structured errors for unknown
values. It is a requirement about EXHAUSTIVENESS. Whether it is also a
requirement about EXPOSURE - that each named surface must offer each named
operation for every kind - is the interpretive crux, and the boundary ADR does
not say. The implementing Steps read it as exposure; a reading confined to
exhaustiveness would require only that whatever the Model Context Protocol
already exposes handles all three kinds, which for the five-tool surface would
have meant extending search and reindex to the document kind and nothing more.

Neither reading is established by the text. What is established is negative and
firm: `2026-07-21-code-document-index-boundary-adr` contains no reference to
`2026-06-30-mcp-search-scope-adr`, does not list it in `related:`, does not
supersede it, and nowhere acknowledges that a prior accepted decision had
removed status and clean from this surface by name. The narrowing was not
weighed and rejected; it appears not to have been consulted.

### The audit that reviewed this work could not have caught it

`2026-07-22-code-document-index-boundary-w05-public-surfaces-audit` reviewed the
implementation of the very Steps that added the tools, and its stated scope
covers "CLI and MCP adapters". A search of that document for the scope ADR, for
its decision identifiers, or for the word "narrow" returns nothing.

This is not an oversight by that reviewer so much as a consequence of framing:
the audit judged implementation against D6 and its Step list, which is what a
step-conformance review is for. Nothing in its remit asked whether D6 itself
conflicted with an earlier accepted decision. The drift therefore passed a
review that was working correctly within a frame that excluded the question.

### The executable guard was amended in the same commit that widened the surface

The scope ADR's Consequences require the boundary to be "enforced mechanically
(a test over the registered tool set), or admin tools will re-accrete". Two such
tests exist, and they diverged.

`src/vaultspec_rag/tests/test_mcp_conformance_surface.py` was edited by
`f5c04db8` itself. The diff moves `get_index_status` out of the removed set and
into the expected set, adds the six other tools, and introduces a clean-tool
group. Its module docstring still states that it asserts "the surface decided by
the `mcp-search-scope` ADR", so after the edit the guard cites the authority of
a decision whose text forbids part of what it now asserts. A future reader
consulting the test to learn the boundary is told the opposite of the record.

`src/vaultspec_rag/tests/test_cli_watcher.py::test_cli_mcp_control_parity` was
not edited. It still asserts the exact five-name list and carries a comment
attributing that list to the scope ADR, and it is currently failing. The
mechanical enforcement the ADR asked for did exist and did fire; the failure
was carried among a larger set of failures rather than read as a boundary
breach.

### The reinstated status tool is the same duplication the decision removed

SB3's objection to `get_index_status` was specific: it was "a second name for
the same service-state route" as the admin `get_service_state`. That objection
survives the reinstatement intact. The current tool at
`src/vaultspec_rag/mcp/_tools.py:467` delegates to `_try_http_admin` with the
literal operation name `get_service_state`. The duplication SB3 named is present
in the same form, under the same tool name, reaching the same route.

### The clean tools are honestly annotated and still outside the permitted scope

The annotations are not the problem. `_CLEAN` at `_tools.py:77` declares
`destructiveHint=True`, so the surface tells the truth about what these tools do,
which is what SB5 demanded of survivors.

SB6's objection was different: it removed the destructive drop-and-recreate path
from the Model Context Protocol so the refresh annotation would be "honestly
non-destructive rather than carrying a hidden destructive mode", and kept clean
as a command-line responsibility on the reasoning that the agent should not hold
a destructive verb at all. The current surface satisfies the honesty half and
contradicts the scope half. `clean_all` at `_tools.py:517` deletes vault, code,
and document content in one call.

### An older parity conflict predates the drift and is still unresolved

`2026-06-01-service-observability-adr` is `accepted` and its title states
"read-only HTTP + CLI/MCP parity". Its body requires "full CLI to MCP parity"
for the server-state surface and routes control through the Model Context
Protocol seam.

`2026-06-30-mcp-search-scope-adr` SB4 states that the surfaces "deliberately do
not mirror each other's verbs" and that the decision "retires the parity-matrix
framing", while SB2 removes service-state inspection, jobs, and logs by name -
the same tools the observability ADR added.

`2026-06-18-mcp-service-client-adr` supersedes five prior MCP ADRs by name; the
observability ADR is not among them. So both records remain accepted, neither
supersedes the other, and they give opposite answers on whether these two
surfaces should mirror each other. Chronologically the parity mandate was
overtaken twice - once by the thin-client reframing that changed the mechanism,
once by the scope narrowing that removed the tools - but it was never formally
retired.

### The governing rule is orthogonal in its normative text and stale in its example

`service-domain-owns-operability` requires that health, status, jobs, logs, and
search diagnostics be implemented as service-domain behaviour, and that
command-line and Model Context Protocol entry points "adapt to that shared
behavior rather than own or duplicate it". Read literally this is a rule about
WHERE LOGIC LIVES, not about which surface exposes which operation: it is
satisfied by a surface that exposes nothing, provided that whatever it does
expose delegates rather than reimplements. On that reading it is orthogonal to
the scope question and pulls neither way.

Its illustrative example pulls the other way, however. The rule's own "Good"
case describes passing the same query parameters through the command-line jobs
verb and "MCP `get_jobs`" - a tool SB2 removed. The example therefore presumes a
parity the scope ADR abolished, and is stale relative to the accepted corpus.
This matters because an implementer consulting the rule for guidance meets the
example before the distinction, and the example reads as endorsement of mirrored
surfaces.

### Whether the narrowing's reasoning still holds, per tool

The decision's rationale was that an agent-facing search tool should not manage
the daemon it depends on. That argument is not uniform across the seven tools,
and the evidence supports different answers.

**The two search tools and the two document-kind reindex tools sit inside the
original rationale rather than against it.** SB1 admits search verbs, and SB6
admits incremental refresh as "the one legitimate write an agent needs (freshen
the corpus it is about to search)". `search_documents` and `reindex_documents`
are the document-kind instances of categories the decision already permits.
`search_combined` and `reindex_all` are the same categories widened across
kinds. Nothing in the rationale distinguishes a document corpus from a vault or
code corpus for these purposes. If the ADR is amended, these four are the ones
whose admission requires the least new reasoning - though `reindex_all` and
`clean_all` share a naming pattern that invites treating them alike, and they
are not alike.

**The status tool has a genuine argument on each side.** For retention: an agent
that cannot tell whether an index is ready cannot interpret an empty result set,
and after the boundary work per-domain counts, generation state, and degraded
reasons are exactly the information needed to distinguish "nothing matched" from
"this domain is not indexed". The tool is read-only, honestly annotated, and
arguably search-adjacent in the same sense that admitted `get_code_file`.
Against retention: SB3's objection was duplication rather than uselessness, and
that objection is untouched - it remains a second name for the service-state
route. Further, the need it serves is already met in-band: the search route at
`src/vaultspec_rag/server/_routes.py:267` attaches an `index_state` structure
carrying `indexed_count` and target-match information to search responses, and
the empty-result path builds a message from it. An agent that searches an
unindexed domain is told so by the search response itself. The residual gap is
that this arrives reactively, on a result, rather than being available before
choosing to search - which is a real but narrower need than the retention
argument as usually stated.

**The clean tools have the weakest case for retention.** They mutate
destructively and irreversibly; `clean_all` spans all three domains. The
kind-exhaustiveness reading of D6 would be satisfied by the command-line clean
verb handling all three kinds, which it does, without any Model Context Protocol
exposure. The only argument found for their presence is symmetry with the
reindex family, which is an argument from naming rather than from need. No
evidence was found that an agent workflow requires them.

### What the reconciliation must settle

The terrain, stated without choosing:

First, which decision governs. Two accepted ADRs give incompatible answers about
this surface, and a third accepted ADR gives an incompatible answer about
parity. Any outcome that leaves all three accepted leaves the corpus
self-contradicting regardless of what the code does.

Second, whether D6 is a requirement about exhaustiveness or about exposure. The
implementing Steps assumed exposure; the text supports either. This is the
single interpretive question on which the status of four of the seven tools
turns.

Third, per-tool admission, on which the evidence differs sharply: four tools are
instances of already-permitted categories, one reinstates a duplication whose
specific objection still stands while serving a need partly met in-band, and two
are destructive verbs with no demonstrated agent need.

Fourth, what happens to the two executable guards, which now assert
contradictory surfaces while both citing the same ADR.

Fifth, whether the stale example in `service-domain-owns-operability` is
corrected, since it will otherwise keep suggesting a parity that the corpus may
have decided against.

Not investigated: whether any real agent configuration or workflow in this
project or its consumers actually calls the seven tools, which would bear on the
breaking-change cost of removing any of them; and whether the `2026-06-01`
parity mandate has any surviving consumer beyond the tools SB2 already removed.

## Sources

<!-- Each locator cited above, once: `path:line` backtick locators for code,
     bare URLs for external references. Flag unverified general-knowledge
     claims. -->

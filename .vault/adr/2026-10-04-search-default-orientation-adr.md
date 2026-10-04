---
tags:
  - '#adr'
  - '#search-default-orientation'
date: '2026-10-04'
modified: '2026-10-04'
body_schema: 'body-v2'
body_hash: 'sha256:5fb556890a51bdba772f92b980c94f598445b747965c2dc92963feaeae5fe244'
related:
  - "[[2026-06-24-vault-pipeline-search-research]]"
  - "[[2026-06-30-mcp-search-scope-adr]]"
  - "[[2026-07-21-code-document-index-boundary-adr]]"
  - "[[2026-09-08-search-readiness-contract-adr]]"
  - '[[2026-06-24-vault-pipeline-search-adr]]'
---

# `search-default-orientation` adr: `ADR and code orientation defaults` | (**status:** `accepted`)

## Problem Statement

A bare CLI search selects vault records and provides no code orientation. MCP combined search includes extracted documents and every vault type. The user requested relevant ADRs and code by default, with a short filter advisory on both interfaces.

## Considerations

The orientation findings in `2026-06-24-vault-pipeline-search-research` establish the value of decision records and explicit type selection. Existing combined retrieval already ranks domain candidates together. Current source inspection confirms the CLI default at `src/vaultspec_rag/cli/_search.py:1079`, the MCP union at `src/vaultspec_rag/mcp/_tools.py:525`, and the domain-owned combined facade at `src/vaultspec_rag/_public_search.py:459`.

## Considered options

- Keep vault-only defaults: misses the implementation context requested by the user.
- Default to all three domains: retains document and non-decision noise during orientation.
- Default to ADRs plus code, with an explicit full union: chosen; reuses retrieval and ranking while making orientation useful.

## Constraints

Preserve explicit vault, code, document, and full-union selections. Preserve relevance scoring and top-k selection. Readiness and partial failures describe only requested domains. Explicit vault-type filters override the ADR default. No storage or indexing changes.

This refines the union convenience in `2026-06-30-mcp-search-scope-adr`: the MCP tool still provides the full union explicitly but starts with orientation. The all-domain search requirement in `2026-07-21-code-document-index-boundary-adr` remains binding for explicit all/combined CLI requests and MCP include_documents=true. The canonical readiness contract remains unchanged.

## Implementation

A bare CLI search requests combined retrieval excluding extracted documents; an explicit --type combined/all requests the full union. MCP search_combined defaults include_documents to false; true restores full-union retrieval. The shared combined facade defaults its vault filter to adr only when documents are excluded and no explicit doc_type or inline type token was supplied.

Each CLI and MCP search response carries one advisory with actual interface syntax and tells callers how to inspect result type metadata. CLI JSON remains a single envelope. Omitted document domains are neither queried nor represented as successful or failed in readiness.

Direct implementation covers the shared facade and outcomes, HTTP transport and readiness selection, CLI/MCP adapters, focused documentation, and regression verification. No separate plan is needed. Authorization: the user's 2026-10-04 request expressly changes the defaults to ADRs and code and delegates advisory syntax selection.

## Rationale

Selecting the intended candidate types addresses orientation without inventing new ranking weights, a new index kind, or an additional MCP tool. Explicit full-union selection preserves access to every existing corpus.

## Consequences

Bare CLI and default MCP combined searches change their candidate sets. Callers needing extracted documents or all vault records must select them explicitly. The advisory adds a small response field in structured output and one line in human output. Acceptance authorizes the change, not a claim that verification has finished.

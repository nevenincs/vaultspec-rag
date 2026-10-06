---
tags:
  - '#adr'
  - '#code-file-admission'
date: '2026-10-04'
modified: '2026-10-04'
body_schema: 'body-v2'
body_hash: 'sha256:ceef092dc12335f760c735e7d1799f8e5232108c820f157d6600e2e26b56629d'
related:
  - "[[2026-04-04-security-hardening-research]]"
  - "[[2026-04-04-security-hardening-adr]]"
  - "[[2026-07-21-code-document-index-boundary-adr]]"
  - '[[2026-06-30-mcp-search-scope-adr]]'
---

# `code-file-admission` adr: `Admit code-file retrieval through the index's source policy` | (**status:** `accepted`)

## Problem Statement

The code-file route reads with the service's filesystem authority on behalf of any caller holding the service token, and it returned every path contained in an enrolled root except names on a short list. A reported finding showed that `.npmrc`, `.pypirc`, `.netrc` and files under `.ssh`, `.aws` and `.kube` match no entry on that list, so a caller with less filesystem authority than the service could retrieve registry, cloud, SSH and cluster credentials. A list of secret names cannot be completed. The route needs a rule for what it returns, not a longer list of what it withholds.

## Considerations

- `2026-04-04-security-hardening-adr` D2 chose a deny-list for this tool on maintainability grounds, while noting the tool is a direct read that bypasses ignore handling. `2026-04-04-security-hardening-research` grounds that choice.
- `2026-07-21-code-document-index-boundary-adr` requires source admission to be implemented once in the index domain; adapters consume its disposition and must not reproduce its rules.
- `2026-06-30-mcp-search-scope-adr` retains the tool as search-adjacent retrieval. Its purpose is reading in full a file that code search returned.
- The service token is a monitoring gate on a loopback service, not a statement of the caller's filesystem authority.
- The index already reads source through a reader that refuses links and non-regular files and binds the read to the opened object, at `src/vaultspec_rag/indexer/_source_file.py:78`.

## Considered options

- Extend the deny-list with the reported names: rejected. The next unlisted location reopens the same finding.
- Deny hidden paths only: rejected as the sole control. Visible non-source content such as data dumps, configuration and unconventionally named key material stays readable.
- Admit through the index policy only: rejected as the sole control. The policy admits source under hidden directories, and a broad caller-authored route can admit any name.
- Admit document-kind content as well as code: rejected. Documents have their own search domain, and a document's raw source is often not text.
- Admit through the index policy, and additionally refuse hidden components and sensitive names: chosen.

## Constraints

Authorization: the user's 2026-10-04 request to fix the reported finding authorizes its stated remediation, namely an affirmative source-file policy shared with content discovery, default denial of hidden credential and configuration locations, a regular-file requirement, and descriptor-bound reads that follow no link. This ruling replaces D2 of `2026-04-04-security-hardening-adr`; D1, D3 and D4 of that record continue to apply. It consumes the classifier of `2026-07-21-code-document-index-boundary-adr` unchanged.

These are obligations:

- A file is returned only when its canonical root-relative path is admitted as code by the root's resolved index policy. The route consumes that policy and carries no classifier of its own.
- A dot-prefixed component in the requested or the canonical path is refused whatever the policy says. No route or profile re-admits a hidden path.
- A filename matching a sensitive pattern is refused whatever the policy says, without regard to letter case.
- Authorization is evaluated on the canonical path, so an alias receives the verdict of the object it resolves to.
- The read is bound to a regular file and follows no link. A failure of that binding is a denial, never a fallback to a plain read.
- A refusal on any of these grounds is one undifferentiated response, and it does not depend on whether the refused object exists.
- Token authentication, workspace containment and the read-size bound are unchanged.

These are implementation hypotheses that may change within the obligations: the policy is resolved per request rather than cached, and the contents of the sensitive-pattern list.

## Implementation

We will return a file from the code-file route only when the index would admit it as code, and refuse hidden and sensitively named paths on top of that admission.

The route's reader, at `src/vaultspec_rag/server/_routes.py:946`, canonicalizes the requested path, checks containment, and asks one admission function at `src/vaultspec_rag/server/_routes.py:926` before it opens anything. Admission applies the name rules to both spellings at `src/vaultspec_rag/server/_routes.py:939` and classifies the canonical path through the resolved index policy at `src/vaultspec_rag/server/_routes.py:942`. An admitted path is read through the index's bound source reader at `src/vaultspec_rag/server/_routes.py:968`. The name rules live at `src/vaultspec_rag/server/_utils.py:152`: every dot-prefixed component is hidden, and the remaining patterns at `src/vaultspec_rag/server/_state.py:125` cover visible key and credential names. The former hidden entries on that list are removed because the component rule subsumes them.

## Rationale

An affirmative rule is complete where a deny-list cannot be: a credential file is refused because it is not source, with no need to have anticipated its name. Sharing the index's policy gives the tool the meaning its place on the surface already implied, the full text of something code search could have returned, and honours the single-classifier constraint. The two refusals layered on top cover what admission alone leaves open: source the index admits from hidden tool directories, and a caller-authored route broad enough to admit anything. Reusing the index's reader closes the window between authorizing a name and opening it without a second implementation of that binding.

## Consequences

- Credential and tool-configuration files are refused by construction, including under names nobody listed.
- The tool narrows. Visible non-source files such as `README.md` and `pyproject.toml`, and anything a project's ignore files exclude, are no longer returned. A project that needs an unconventional source format returned routes it as code, which also indexes it.
- Hidden source such as scripts under `.github` stays indexed and searchable but is not returned in full.
- Each request resolves the index policy, which reads the root's ignore files. On this repository that measured about 0.05 seconds. A root where it is slow is the condition for caching the resolved policy.
- A need to retrieve document-kind content in full would be a new decision, not a widening of this one.

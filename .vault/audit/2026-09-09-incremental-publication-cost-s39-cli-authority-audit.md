---
tags:
  - '#audit'
  - '#incremental-publication-cost'
date: '2026-09-09'
modified: '2026-09-09'
body_schema: 'body-v2'
body_hash: 'sha256:75da6bf8a6ffe52879f11f9c1e367f0978f95204792a48b97052c0375a719a95'
related:
  - "[[2026-09-08-incremental-publication-cost-adr]]"
  - "[[2026-09-08-incremental-publication-cost-plan]]"
  - "[[2026-09-08-incremental-publication-cost-W03-P08-S39]]"
---

# `incremental-publication-cost` audit: `s39 cli authority`

## Scope

Audited the CLI publication and rebuild boundary against the accepted authority
decisions and the follow-on audit-verification boundary. The review traced CLI and
borrowed-local requests through the reindex transport, strict server validation,
canonical job creation, server-owned combined-domain fan-out, MCP publication, and
automatic integrity remediation. It also covered the complete diff from `HEAD`, every
direct transport and raw-route caller, mutation evidence, focused tests, and static
gates.

## Findings

### raw-reindex-alias | medium | Benchmark reindex used a route-rejected source alias

The initial diff added authority to the concurrency benchmark while leaving its raw
`/reindex` source as `codebase`. The strict server route rejects aliases before job
admission, so the benchmark could not start its requested concurrent publication. The
caller now sends canonical `code`, and its focused guard was demonstrated failing on
the alias and passing after restoration. Resolved during review.

### development-metadata | low | Execution identifiers entered a test docstring

The initial audit-authority guard described its ownership using Step identifiers in
test source. The docstring now states only the product constraint, and the final
modified-source census contains no development-record identifier. Resolved during
review.

No open findings. **Verdict: APPROVED.** Publication and rebuild authority are concrete
before either CLI execution path is selected, required by the transport without a
default, and validated against the exact incremental or rebuild mode before server
fan-out. Missing, mismatched, and audit authority fail closed. Publication authority
cannot select full work; audit verification has no CLI or MCP activation in this Step;
combined requests remain one client request expanded by the server; and the final diff
adds no fallback, compatibility shim, migration, or raw-wire alias.

The guard families were each demonstrated red and restored green: CLI wire mapping,
route authority validation, local and service audit refusal, integrity-remediation
publication authority, and the canonical benchmark payload. The stable focused
regression ran 201 tests, the remediation suite ran 9 tests, and formatting, lint,
`ty`, `basedpyright`, caller census, and diff hygiene passed. The broader unit run
reported 4,626 passes, 3 skips, and 6 failures whose reported causes do not intersect
the S39 diff. The GPU-marked service source-type module could not collect without the
required machine service lease; its authority contract is covered by the executed CPU
boundaries and repository-wide static checks.

## Recommendations

No blocking recommendation. Keep audit verification on its separately authorized,
non-seeding implementation path. Address the six unrelated repository-wide unit-gate
failures in their owning scopes and rerun the GPU-marked service source-type module when
a compatible service lease is available.

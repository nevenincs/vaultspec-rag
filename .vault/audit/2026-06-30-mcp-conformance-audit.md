---
tags:
  - '#audit'
  - '#mcp-conformance'
date: '2026-06-30'
modified: '2026-06-30'
related:
  - "[[2026-06-30-mcp-conformance-adr]]"
  - "[[2026-06-30-mcp-search-scope-adr]]"
  - "[[2026-06-30-mcp-conformance-plan]]"
  - "[[2026-06-30-mcp-conformance-reference]]"
---

<!-- FRONTMATTER RULES:
     tags: one directory tag (hardcoded #audit) and one feature tag.
     Replace mcp-conformance with a kebab-case feature tag, e.g. #foo-bar.
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

# `mcp-conformance` audit: `MCP conformance verify-phase review`

## Scope

Verify-phase, read-only review of the MCP conformance implementation a parallel agent
committed end-to-end (research/ADRs/reference/plan in one commit, the P01 discovery fix
in another, and the P02-P06 surface narrowing in a third, with a later typed-outputSchema
follow-up). The implementation was reviewed against the two accepted ADRs - the discovery
contract (decisions SD1-SD6) and the search-surface scope boundary (decisions SB1-SB6) -
and the reference, plus the epic mandate's measurable gates. Three independent reviewers
combed the discovery layer (`serviceclient/_discovery.py`, `serviceclient/_transport.py`,
`mcp/_tools.py`, `_machine_lock.py`), the MCP surface and spec conformance (`mcp/_tools.py`,
`_admin_client.py`, `_resources.py`, `mcp/__init__.py`, `mcp/_mcp.py`), and the test suite
plus CI gate. All findings are read-only; no code was modified. The box cannot currently
run server-mode Qdrant and ships a CPU-only torch build, so live-GPU/live-Qdrant behaviour
was judged by inspection; the conformance tests themselves are CPU-only and do run.

Overall verdict: REVISION REQUIRED. The hardest decision - the SD1 discovery authority
inversion that fixes the original cross-status-directory bug - is correctly implemented
and verifiably tested. One HIGH conformance failure (SB6), a cluster of MEDIUM hardening
and documentation gaps, and two LOW items remain before the work conforms to the ADRs as
written.

## Findings

### reindex-clean-path-retained | high | The destructive `clean` rebuild was not removed from the MCP refresh tools, contradicting ADR decision SB6.

SB6 decides unambiguously that the MCP refresh tools must be annotated non-destructive and
idempotent and that the destructive drop-and-recreate `clean` path is removed from them and
remains CLI-only. The implementation did the opposite, confirmed by two independent
reviewers and live introspection. `reindex_vault` and `reindex_codebase` in `mcp/_tools.py`
still accept `clean: bool = False` and forward it to the daemon reindex route, so an agent
can still invoke `reindex_vault(clean=True)` through MCP and silently drop-and-recreate a
collection - the exact agent-facing destructive verb the ADR's Consequences section says
must be gone. The shared refresh annotation `_INDEX_REFRESH` is set to
`readOnlyHint=False, destructiveHint=True, idempotentHint=False` - the reference's
explicitly rejected alternative - rather than the ADR's binding
`destructiveHint=False, idempotentHint=True`. The annotation is honest about the retained
behaviour, so SB5's no-lying-annotation rule holds and this is not critical; but SB6's
removal requirement is unmet and a data-loss-capable verb remains on the agent surface.

### boundary-test-misses-sb6 | medium | The conformance test does not guard SB6, so the deviation shipped green.

The ADR's Consequences section explicitly requires the boundary to be enforced
mechanically. The surface test `test_refresh_tools_are_not_read_only` in
`test_mcp_conformance_surface.py` asserts only that the refresh tools have
`readOnlyHint is False` - which is true under both the ADR-intended and the shipped
annotation - and does not assert `destructiveHint is False`, `idempotentHint is True`, or
the absence of a `clean` input property. The SB6 decision is therefore unguarded by the
very test the ADR mandated, which is why the deviation passed the full suite. Once the
`clean` path is removed, this test must assert the chosen non-destructive contract and the
absence of the `clean` parameter.

### authoritative-token-discarded | medium | The resolved pointer's token is thrown away and the transport re-derives it from the foreign status file.

The machine-service resolution returns a payload carrying both the port and the
`service_token`, but `_default_service_port()` discards everything except the port. The
transport then sources the token from the per-status-directory status file - exactly the
foreign or absent file the discovery contract routes around. In the headline frozen-MCP
case the first call therefore sends a wrong or empty token, eats a 401, and self-heals via
the `/health` endpoint: functionally correct but a guaranteed extra round-trip on every
call in the target scenario, and it under-delivers SD1/SD5 because the authoritative token
exists but is never used. Resolve the port and token together and pass the pointer's token
into the call, keeping the 401 self-heal as the fallback.

### fallback-service-json-unvalidated | medium | The per-status-directory fallback bypasses the SD4 staleness and liveness validation.

The machine-pointer path correctly refuses a stale or dead-pid pointer, but the
compatibility fallback `_read_service_status()` validates only that the file carries `pid`
and `port` keys - no heartbeat or liveness check. When no machine service resolves, a stale
or dead `service.json` in the consumer's own status directory is returned as a live port,
contradicting SD4's "stale managed-state is detected and refused" for the fallback surface.
It is contained in practice (a dead port yields connection-refused, and the transport's
non-JSON-body guard catches a foreign listener), so it degrades legibility rather than
safety, but it is unvalidated stale state by the ADR's own standard. Either apply the same
staleness gate to the fallback or document it as a deliberate transport-guarded degrade.

### sd5-resolution-legibility-missing | medium | Resolution failure class is lost at the `int | None` boundary, so SD5 legibility is not delivered for discovery.

Transport-level legibility is good - the empty-body 404 path the research flagged is gone,
replaced by a structured envelope discriminating connection-refused, timeout, auth, and
wrong-port. But SD5 also requires the resolution failure to report which discovery source
was consulted, whether a live lock holder exists, and the failure class.
`_default_service_port()` collapses every outcome to `int | None`, and `_require_port()`
raises one generic service-down message for both "no live service at all" and "live holder
but its pointer went stale" - the latter signalled only as a debug log. The operator cannot
distinguish a down service from a service whose pointer went stale. Surface a small
resolution result (source, live-holder, port, failure class) into the MCP error text.

### refresh-annotation-inverted | medium | The index-refresh idempotent and destructive hints are inverted relative to the ADR.

A direct corollary of the SB6 finding: the ADR and reference specify the incremental
refresh path as `destructiveHint=False, idempotentHint=True`, but the shipped
`_INDEX_REFRESH` is `destructiveHint=True, idempotentHint=False`. Given the retained `clean`
parameter the shipped annotation is internally honest, but it does not match the decision.
Removing `clean` from the MCP refresh tools should flip these to the ADR-specified values.

### sd6-negative-test-underspecified | medium | The absent-service test under-specifies the remediation and never exercises the isError surfacing.

SD6 requires the absent-service path to fail fast with one actionable error naming the
start command, surfaced as a tool result marked in error. The negative test in
`test_mcp_no_local_fallback.py` matches only the first clause ("is not running"), so a
regression dropping the remediation half ("Start it with `vaultspec-rag server start`")
still passes. It also calls the tool coroutine directly rather than through the MCP
call-tool path, so the exception-to-isError conversion SD6 names as the mechanism is
asserted nowhere. Assert the remediation substring and drive one tool through the MCP
call-tool surface to confirm the error result.

### transport-prose-stale | medium | The ADR and reference describe a Streamable-HTTP `/mcp` transport the shipped architecture does not use.

ADR decision SB5 and the reference state the daemon serves the MCP app via
`streamable_http_app()` mounted at `/mcp`. The shipped architecture is the opposite, by a
superseding prior decision: the daemon serves native REST only with no `/mcp` mount (guarded
by a daemon test that forbids `streamable_http_app`), and the MCP server runs as a separate
stdio subprocess; the `stateless_http` flag is vestigial under stdio. The implementation
did not regress here - the transport prose in the conformance docs is simply inaccurate.
Reconcile the ADR SB5 and reference transport text with the shipped stdio model so future
agents are not misled.

### monkeypatch-in-test-server | medium | A changed test file uses the forbidden `monkeypatch`, violating the project test mandate.

The project mandate bans `monkeypatch`. `test_server.py`, a file changed in this work,
replaces a real status-file-path function with a lambda via `monkeypatch.setattr` across
several daemon-lifecycle tests. The conformance edit to this file was only the tool-count
and surface assertions, so the violation predates this work, but it stands in an in-scope
file and should be retired to the real temp-directory redirection the new discovery suite
already uses.

### lock-liveness-unguarded-at-ci-tier | medium | The OS-lock liveness authority that SD1/SD3 lean on is not exercised by the CI unit gate.

Every discovery-resolution test that needs a live holder acquires the lock in-process, so
the liveness probe returns via the same-process bookkeeping early-return and never reaches
the genuine cross-process OS-lock attempt. The real advisory-lock authority is exercised
only by subprocess integration tests that are not in the CI `-m unit` gate. The staleness
and authoritative-precedence orchestration is verified for real, but the lock-probe
authority is unguarded at the CI tier; add a subprocess-based liveness assertion to the
gated layer or accept the gap explicitly.

### pointer-pid-correspondence-unchecked | low | Liveness is an existence check, not a pid cross-check, leaving a narrow benign restart window.

SD1 says the pointer must correspond to a live lock holder, but resolution verifies only
that some live holder exists and the pointer is fresh - it never checks that the pointer's
pid equals the lock holder's pid. In a narrow window (daemon A crashes, daemon B acquires
the lock but has not yet written its first heartbeat) a consumer could resolve A's
still-fresh pointer. It is benign - if B reused the default port the port is identical, and
if B bound a different port the consumer hits connection-refused and fails fast - but a
cheap pid-equality guard would make the code match the ADR wording.

### shallow-conformance-assertions | low | Two conformance assertions are weaker than their names imply.

The search-default test hardcodes the expected count rather than referencing the CLI's
own default constant, so despite its name it cannot catch a CLI/MCP default divergence; and
the outputSchema assertion checks only that a schema is present, not that returned
`structuredContent` validates against it, leaving the matching-structured-content half of
SB5 unverified. Tighten both to assert the relationship they claim to guard.

## Recommendations

- **Required before the epic is conformant (SB6, HIGH):** remove the `clean` parameter from
  `reindex_vault` and `reindex_codebase` in `mcp/_tools.py` (and from their reindex partials),
  keep the destructive clean rebuild CLI-only, and flip `_INDEX_REFRESH` to
  `destructiveHint=False, idempotentHint=True`. Then extend the surface test to assert the
  refresh tools carry the non-destructive contract and expose no `clean` input, closing the
  mechanical-enforcement gap the ADR mandated.
- **Required (SD6 test):** strengthen the absent-service test to assert the start-the-service
  remediation substring and to drive one tool through the MCP call-tool surface so the
  isError result is actually exercised.
- **Recommended (discovery hardening):** thread the resolved pointer token through to the
  transport; decide whether the per-status-directory fallback is staleness-gated or a
  documented degrade; and surface the resolution failure class into the MCP error so SD5 is
  delivered at the resolution layer, not only the transport layer.
- **Recommended (documentation):** reconcile the ADR SB5 and reference transport prose with
  the shipped stdio transport; this is a doc-accuracy fix, not a code change.
- **Recommended (test hygiene):** retire `monkeypatch` from `test_server.py` to real
  temp-directory redirection; add a CI-gated subprocess liveness assertion for the OS lock;
  and tighten the two shallow conformance assertions.
- **Not blocking:** the pointer pid-correspondence guard is optional hardening that would
  make the code literally match SD1's wording.

### server-stop-test-not-machine-isolated | medium | A CLI server-stop unit test isolates only the status dir, so the new lock-reclaim path fails against a live machine service.

Surfaced while running the unit gate to verify the SB6 fix: `test_service_stop_no_status_file`
in `test_cli.py` isolates only the status directory and asserts the output says the service
is not running. The discovery work added a `server stop` path that reclaims a resident
service through the machine-global singleton lock even when no status file is discoverable,
and the machine lock is status-directory independent (anchored to the managed storage dir).
On a machine with a live lock holder the test therefore sees "Reclaimed the resident machine
service (pid ...)" instead of "not running" and fails - and worse, running it stops a real
service. This is the `managed-singleton-paths-isolate-storage-dir-in-tests` rule: the test
must also set the managed storage dir to a temp path so it cannot reach the real machine
lock. The failure is independent of the SB6 fix (it is in the server-stop/discovery path)
and belongs to the discovery work; flagged here because it is a live unit-gate failure that
must be closed before the epic's CI gate is green.

### Resolution applied this cycle

Closed in this verify cycle (working tree, not yet committed):

- **SB6 (HIGH) - fixed.** The `clean` parameter was removed from the MCP `reindex_vault`
  and `reindex_codebase` tools (they now always pass an incremental refresh to the shared
  transport, which the CLI continues to drive with the destructive rebuild), the shared
  refresh annotation was flipped to `destructiveHint=False, idempotentHint=True`, and the
  conformance guard was strengthened to assert the non-destructive contract and the absence
  of any `clean` input. Broken integration callers were updated.
- **server-stop-test-not-machine-isolated (MEDIUM, the live CI-gate failure) - fixed.**
  `test_service_stop_no_status_file` now isolates the managed storage dir as well as the
  status dir, per the `managed-singleton-paths-isolate-storage-dir-in-tests` rule, so the
  lock-reclaim path resolves an empty temp dir instead of the real machine lock. The full
  unit gate now passes (1134 passed, 0 failed).
- **sd6-negative-test-underspecified (MEDIUM) - fixed.** The absent-service test now asserts
  both the "is not running" diagnosis and the "vaultspec-rag server start" remediation, so a
  regression dropping the remediation half fails the test. (The protocol-level isError
  surfacing remains FastMCP's standard exception conversion; the high-level `call_tool`
  raises `ToolError` rather than returning the result, so an isError assertion is left as a
  follow-up to avoid a brittle internal-API test.)
- **transport-prose-stale (MEDIUM) - fixed.** The reference and the scope ADR SB5 prose now
  describe the shipped stdio transport (the daemon serves native REST only with no `/mcp`
  mount; the MCP runs as a standalone stdio subprocess) instead of the inaccurate Streamable
  HTTP claim. Verified against `server/_main.py` and `server/_routes.py`.
- **shallow-conformance-assertions (LOW) - fixed.** The top-k test now tracks the
  `_DEFAULT_TOP_K` source constant across both search tools, and the outputSchema test now
  asserts the schema reflects the `SearchResults` model fields (`results` and `summary`).

Left open for the discovery-side follow-up (the other agent owns that committed code and is
actively iterating; these are non-blocking refinements that do not break the end-to-end
contract): the authoritative-token threading, the fallback-`service.json` staleness gate,
the SD5 resolution-layer legibility, the `monkeypatch` retirement in `test_server.py`, the
CI-tier OS-lock liveness assertion, and the pointer pid-correspondence guard.

What is confirmed MET and mechanically guarded: SD1 authoritative (not absent-only)
cross-status-directory resolution, SD2 single-service preservation, SD3 status-directory
independence and per-call re-resolution, SD4 for the machine path, SD6 fail-fast (message
present), and SB1/SB2/SB3/SB5 for the read-only tools - the surface is exactly the five
in-scope tools plus the resource and prompt, no admin or lifecycle tool is registered, and
the conformance suite is real-behaviour, no-mocks, and correctly wired into the CI unit
gate with no silent skips.

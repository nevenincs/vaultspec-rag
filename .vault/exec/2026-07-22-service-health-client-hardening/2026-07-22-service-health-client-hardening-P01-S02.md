---
tags:
  - '#exec'
  - '#service-health-client-hardening'
date: '2026-07-22'
modified: '2026-07-22'
step_id: 'S02'
related:
  - "[[2026-07-22-service-health-client-hardening-plan]]"
---

<!-- FRONTMATTER RULES:
     tags: one directory tag (hardcoded #exec) and one feature tag.
     Replace service-health-client-hardening with a kebab-case feature tag, e.g. #foo-bar.
     Additional tags may be appended below the required pair.

     modified: CLI-maintained last-modified stamp; set at scaffold time,
     refreshed by mutating CLI verbs and vault check fix; never hand-edit.

     step_id is the originating Step's canonical identifier, e.g. S01.
     The S02 and 2026-07-22-service-health-client-hardening-plan placeholders are machine-filled by
     `vaultspec-core vault add exec`; do not fill them by hand.

     Related: use wiki-links as '[[yyyy-mm-dd-foo-bar-plan]]' and link the
     parent plan.

     DO NOT add fields beyond those scaffolded; metadata lives
     only in the frontmatter. -->

<!-- LINK RULES:
     - [[wiki-links]] are ONLY for .vault/ documents in the related: field above.
     - NEVER use [[wiki-links]] or markdown links in the document body.
     - NEVER reference file paths in the body. If you must name a source file,
       class, or function, use inline backtick code: `src/module.py`. -->

<!-- STEP RECORD:
     This file represents one Step from the originating plan. Identified
     by its canonical leaf identifier (S##) and ancestor display path.
     The Assert a redirect answered on the health path is refused rather than followed and ## Scope

- `src/vaultspec_rag/tests/test_http_admin_errors.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Assert a redirect answered on the health path is refused rather than followed

## Scope

- `src/vaultspec_rag/tests/test_http_admin_errors.py`

## Description

<!-- Succinct line-by-line list of steps executed. Use imperative language, mirroring git commit summary lines. -->

- Add a real loopback server that answers every request with a redirect to a
  second server, and a sink server that records what reaches it, in
  `src/vaultspec_rag/tests/test_http_admin_errors.py`.
- Assert the health-token fetch against the redirecting server obtains no token
  and leaves the sink untouched.

## Outcome

The health path is now covered by a test that serves a genuine redirect rather
than simulating one. Both servers are real and listen on loopback, in keeping
with the module's existing no-mocks stance; the redirect is a real 302 with a
real location header naming the second server.

The assertion has two halves, and the second is what gives it force. The first
is that no token is obtained, which shows the redirect was not followed to a
successful read. The second is that the sink recorded no request at all, which
distinguishes "followed the redirect and failed to parse the result" from "never
made the second request". Only the latter is refusal, and only the sink's
emptiness can tell them apart.

The sink deliberately answers with a body containing a plausible-looking service
token. If a regression ever causes the redirect to be followed, the test fails on
the value returned as well as on the recorded request, so the failure names the
real problem rather than surfacing as an unexplained empty result.

## Notes

<!-- Incidents. Data loss. Difficulties; persistent failures. Skipped work. Scaffolds left in code. Failures. -->

Not executed by the author; verification is handed to a harness operator. The
test is written against the transport's real wire path and the module's existing
server-fixture helper, but it has not been run, so its passing is expected rather
than observed.

No mock, stub, patch, fake, skip, or expected-failure marker was used. The two
handlers are real request handlers on real sockets, and the shared
server-starting helper already present in the module is reused rather than
duplicated.

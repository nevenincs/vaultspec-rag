---
tags:
  - '#audit'
  - '#service-quiesce'
date: '2026-07-30'
modified: '2026-07-30'
body_schema: 'body-v1'
related:
  - "[[2026-07-24-service-quiesce-adr]]"
  - "[[2026-07-24-service-quiesce-plan]]"
---

<!-- FRONTMATTER RULES:
     tags: one directory tag (hardcoded #audit) and one feature tag.
     Replace service-quiesce with a kebab-case feature tag, e.g. #foo-bar.
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

# `service-quiesce` audit: `S29 borrower capability architectural acceptance`

## Scope

Architectural acceptance review of S29 commit `cb37d33d` against the accepted borrower-capability contract. The review covered capability secrecy and lease lifetime, separation from the service identity lock, pause binding and matching resume, heartbeat loss recovery, lifecycle-envelope failures, unchanged public quiesce projection, and CPU-only evidence. The focused real-process route suite passed four tests without a daemon lifespan, Qdrant, model, or GPU allocation.

## Findings

### unavailable-lease-verification | high | Heartbeat treats an unavailable lock mechanism as proof the borrower died

`borrower_lease_status` converts an `claim_anchor` fault into `NOT_HELD`. `resume_lost_borrower_lease` treats that same result as proof that the bound lease was released and rebuilds GPU residency. A transient anchor open or lock failure can therefore resume the service while the borrower may still retain the OS lock, violating the fail-closed borrower boundary. The route preflight also reports the condition as ordinary absence rather than an unavailable coordination mechanism. The focused suite proves contention, crash release, matching capabilities, and recovery after real release, but contains no real unavailable-anchor case.

## Recommendations

- For `unavailable-lease-verification`, preserve an unavailable verification result separately from `NOT_HELD`. Borrower pause and post-pause binding must fail closed with the canonical lifecycle envelope, and heartbeat recovery must leave the bound quiescence closed when verification is unavailable. Add a real filesystem permission or unsupported-lock proof that the recovery path does not resume under that condition. The implementation must choose and document whether this condition reuses an existing stable borrower error or introduces a separately named stable error before S29 can be accepted.

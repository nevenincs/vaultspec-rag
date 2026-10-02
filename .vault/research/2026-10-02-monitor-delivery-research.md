---
tags:
  - '#research'
  - '#monitor-delivery'
date: '2026-10-02'
modified: '2026-10-02'
body_schema: 'body-v2'
body_hash: 'sha256:69cfdf1e7edfd383800da1c14bac66e211c0b3e16f953bea10b96cd088b6f751'
related:
  - "[[2026-10-02-monitor-delivery-reference]]"
  - "[[2026-09-11-binary-release-bundles-adr]]"
---

# `monitor-delivery` research: `Bun packaging choices and delivery proof`

Can the React monitor become a runnable, self-contained frontend while retaining its current Vite build and RAG service ownership? Official Bun documentation and the code review in `2026-10-02-monitor-delivery-reference` favor a Bun-compiled server that embeds the existing Vite output. The frontend can be independent of a JS installation and checkout; service lifecycle and persisted inventory still require the separately delivered RAG owner. Documentation establishes a supported technique, not a successful build of this application.

## Findings

### bunx is package execution; Bun compilation creates the deliverable

`bunx` resolves/runs package executables and requires a Bun installation; it does not turn this private root package into a native deliverable. `bun build --compile` includes the Bun runtime and server dependencies. Bun also documents full-stack executables with embedded frontend assets. Sources checked 2026-10-02: https://bun.com/docs/pm/bunx and https://bun.com/docs/bundler/executables .

A direct executable meets the requested self-contained frontend property. A separate bunx wrapper would add package publication, executable selection and another acquisition contract; it is unnecessary unless explicitly requested. The review uses Bun compilation as the interpretation of the user's target.

### Vite output can be embedded without replacing the frontend compiler

Bun's executable documentation supports importing files with `with { type: "file" }` and reading their embedded paths through Bun.file or Node filesystem APIs. A generated build-time module can import each file in the Vite output and map its original URL to embedded bytes, including CSS, IBM Plex fonts and other static assets. This is an implementation inference from the documented file embedding facility: https://bun.com/docs/bundler/executables . It requires a real build spike to establish asset closure, MIME/cache behavior and browser rendering for this application.

Directly compiling the original HTML with Bun could also embed server/client assets, but would introduce a second frontend compiler path for the existing Vite/Carbon SCSS application. Keeping the verified Vite output and using Bun only to package/server it has fewer migration assumptions. Packaging Vite preview instead carries development dependencies and contradicts Vite's documented production-server guidance: https://vite.dev/guide/static-deploy.html . A static ZIP or standalone HTML would still need the local server bridge identified by `2026-10-02-monitor-delivery-reference`.

### Native target builds fit the current release fleet

Bun documents Windows x64, Linux x64/ARM64 and Darwin ARM64 compilation, matching the four current RAG release targets. Native compilation on each target avoids an unreviewed automatic cross-target runtime download and allows native smoke tests before bundle upload. Windows metadata features need Windows APIs when compiling; macOS signing/JIT support and byte-changing finalization need their own native checks. Source: https://bun.com/docs/bundler/executables .

Bun's current installation documentation lists glibc 2.17, Windows 10 version 1809 and macOS 13 requirements, plus SSE4.2 on x64. These are documentation claims about the current runtime, not measured floors of a selected compiler pin or this output. The reviewed repository's Linux bundle floor remains 2.39; every binary must be measured against its declared floor. Source: https://bun.com/docs/installation . The exact Bun version and per-target archive/executable digests must be selected and committed before implementation executes a provisioned compiler.

### Frontend independence and backend bootstrap are separate properties

The compiled monitor can serve its embedded shell with network access disabled and no Node, npm, Bun, uv, Python, node_modules or checkout. Actual monitoring needs a responding local RAG service; lifecycle and stopped-service inventory need the canonical RAG command. The managed lifecycle owner's initialized Python environment or a sibling RAG executable supplies that owner without requiring a system Python, but its existing PyApp bootstrap may download the accelerator runtime. The current backend behavior and portable-launch gap are grounded in `2026-10-02-monitor-delivery-reference` and `2026-09-11-binary-release-bundles-adr`.

Serving the shell must not start the daemon or trigger that bootstrap. Native shell smoke tests and real backend-control integration tests therefore prove different claims. A package with three stable executables shares versioning, channel installation and discovery. A separate monitor package can ship independently, but introduces cross-version compatibility and a second release asset unit; the evidence favors using the current RAG bundle unless the user chooses independent distribution.

### Acquisition must test the delivered executable and retain independent trust

Loader-only checks cannot prove frontend asset closure or startup, as the reviewed acquisition and browser harness demonstrate in `2026-10-02-monitor-delivery-reference`. A useful acquisition probe starts the monitor from a temporary directory with development tools unavailable, reads its version/readiness endpoint, fetches every local asset and observes a bounded backend-unavailable response. A browser check must also render that executable's HTTP output, rather than recreate Vite. The same probe can run on locally finalized artifacts before publication and public downloads after publication.

The repository requires committed reviewed SHA256 pins for provisioned native binaries before extraction and again before execution (`.codex/rules/pinned-binaries-verify-before-execute.md:10`). This applies to downloaded Bun toolchains and downloaded monitor bytes. Live SHA256SUMS alone does not meet that rule. A committed release pin catalog can bind tag, producer SHA, archive digest and monitor digest independently; a newly published tag without reviewed pins must fail closed. This introduces a reviewed pin handoff before the public launch probe, while preserving the existing publication order. No release digest or compiler digest was invented or acquired in this review.

### Remaining validation is bounded

No compiler or monitor executable was run during this design review. Application-specific compilation, Windows resources, macOS finalization, deployed browser rendering and portable Python-owner commands remain implementation validation. Neither byte-for-byte executable reproducibility nor a complete offline GPU backend has been established. The ADR must settle release membership, ownership, trust and proof obligations; compiler patch choice and concrete embedding API are implementation details within those commitments.

## Sources

- `2026-10-02-monitor-delivery-reference`.
- `2026-09-11-binary-release-bundles-adr`.
- `.codex/rules/pinned-binaries-verify-before-execute.md:10`.
- https://bun.com/docs/pm/bunx
- https://bun.com/docs/bundler/executables
- https://bun.com/docs/installation
- https://vite.dev/guide/static-deploy.html

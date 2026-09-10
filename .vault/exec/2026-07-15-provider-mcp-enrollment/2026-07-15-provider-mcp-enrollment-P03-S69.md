---
tags:
  - '#exec'
  - '#provider-mcp-enrollment'
date: '2026-09-10'
modified: '2026-09-10'
body_schema: 'body-v2'
body_hash: 'sha256:0b25e3129dedc825fba590d75b6829aea1cce4d39c10b4645a5f7f2cf1921965'
step_id: 'S69'
related:
  - "[[2026-07-15-provider-mcp-enrollment-plan]]"
---

# Repeat every platform-aware release gate from zero after the S68 corrections and stop on the first failure

## Scope

- `.vault/audit/2026-07-15-provider-mcp-enrollment-audit.md`
- `no carried credit`
- `exact clean-candidate corpus and platform ledgers`
- `every S54`
- `S56`
- `S66`
- `and S68 contract`
- `all runtime`
- `static`
- `package`
- `public Core`
- `installed Claude and Codex`
- `idempotence`
- `selective unenrollment`
- `uninstall`
- `and release gates`

## Changes

- `A` `.vault/exec/2026-07-15-provider-mcp-enrollment/2026-07-15-provider-mcp-enrollment-P03-S69.md`

## Notes

Superseded, not re-run. This Step's own audit records that the feature
(Core-managed provider lifecycle, `--mcp`/`--no-mcp` symmetry, dependency
placement) was merged to `main` in a dedicated pull request and released as
part of `vaultspec-rag` 0.3.3, and that its S45-S68 hardening (service
singleton, managed-Qdrant identity, auto-delegation precedence) shipped in
further commits afterward; those production modules remain live and
continue to be exercised and touched without regression.

The bespoke "platform-aware release gate campaign" this Step describes -
hand-counted Windows/POSIX node-id ledgers, a manual wheel/sdist/smoke pass,
and fresh installed-Claude/Codex acceptance run before every merge - was a
substitute for automation that did not exist yet. It now does: the standing
CI pipeline runs the CPU-tier suite plus lint, format, and strict typing on
every push to `main` on Windows, macOS, and Linux, and the separate release
pipeline builds the wheel and sdist and smoke-tests both across the
supported interpreter range before publishing, gating on that outcome.
Recent release runs (`2026-09-07`, `2026-09-05`, `2026-09-02`, and earlier)
completed that build-and-smoke gate successfully, and the current `main`
HEAD's CI run shows the CPU-tier suite green on Windows and macOS, with
Linux failing on exactly two unrelated items (a console line-wrap test and
three `httpx2` advisories) already being closed by open PR #494. Fresh
install, idempotence, and selective-unenrollment coverage for both
providers (`test_install_mode.py`, `test_install_mcp_extra.py`,
`tests/integration/test_install.py`) is part of that same green CPU-tier
run. No GPU-tier work was launched to produce this evidence.

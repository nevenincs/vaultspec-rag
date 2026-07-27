---
tags:
  - '#adr'
  - '#mcp-project-root-contract'
date: '2026-07-25'
modified: '2026-07-27'
related:
  - "[[2026-07-25-mcp-project-root-contract-research]]"
---

# `mcp-project-root-contract` adr: `the mcp surface resolves the root the daemon must never guess` | (**status:** `accepted`)

## Problem Statement

The MCP tool schema advertises `project_root` as optional and the daemon route
requires it, so a caller following the documented default always receives a 400.
A schema that says optional and a route that says required is a broken contract
on one side or the other, and the two must stop disagreeing. Which side yields
determines whether a wrong root fails loudly or resolves silently against the
wrong index.

## Considerations

Evidence gap: the retained ADR body has no separately labelled Considerations section.

## Considered options

- **Loosen the route to accept a blank root.** Rejected.
  `2026-07-25-mcp-project-root-contract-research` establishes that the daemon is
  machine-global and multi-root with no project of its own, so any default it
  invents is a guess whose failure mode is silent - the wrong codebase answering
  a query that looks fine.
- **Advertise the argument as required on every tool.** Rejected: it makes every
  caller restate on every call a value the MCP process already holds exactly,
  and it does nothing the resolved default does not do better.
- **Resolve the root on the MCP side from the process working directory.**
  Chosen. The stdio server is launched per project by its host, so its working
  directory is that project's root - the one place in the chain where the
  default is knowable rather than guessable.

## Constraints

- The MCP layer is a thin service client. The resolution may not introduce
  torch, locks, or any service-domain behaviour into it; it is an adapter
  filling in an argument, not a second implementation of root resolution.
- Health, status, jobs and search diagnostics stay service-domain behaviour. The
  route keeps its strict stance; nothing about the required-ness moves.
- An explicit caller-supplied root must continue to win. A default that
  overrides an argument is worse than no default.

## Implementation

One resolution seam on the MCP adapter returns the concrete root to send:
the caller's value when it is present and non-blank, the resolved process
working directory otherwise. Every delegation site forwards through it in place
of the previous empty-string fallback, including the vault document resource,
whose URI carries no root at all and so can never supply one itself. The server
route is untouched.

## Rationale

The knockout is asymmetry of failure. The daemon guessing wrong is silent and
returns plausible results from another root's index; the MCP process resolving
its own working directory is exact, because the host's per-project launch is
what puts it there. Placing the fill at a single adapter seam rather than in
each tool body also keeps the surface honest: there is one definition of what an
omitted root means, so the schema's claim of optionality is true everywhere at
once instead of tool by tool.

## Consequences

- An omitting caller now succeeds, and the advertised optionality is reachable
  for the first time.
- The daemon's required stance is preserved, so cross-root bleed remains
  impossible by construction.
- A host that launches the stdio server outside the project root would resolve
  the wrong default. The explicit argument still takes precedence, so such a
  host retains a correct path, but the research records that this case has not
  been measured.
- The resolution reads the working directory per call rather than at startup, so
  a process that changed directory mid-life would follow it. Nothing in this
  surface does.

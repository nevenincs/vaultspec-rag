---
tags:
  - '#exec'
  - '#service-release-compat'
date: '2026-07-25'
modified: '2026-07-25'
step_id: 'S04'
related:
  - "[[2026-07-25-service-release-compat-plan]]"
---

# Adapt the start and status verbs to render the shared verdict without gating, keeping the attach path a zero-exit success

## Scope

- `src/vaultspec_rag/cli/_service_start.py`

## Description

- Widen the attach-detection helper to carry the daemon's published release alongside the
  pid, port, and health status it already returned.
- Add the two render helpers that turn the shared verdict into one structured envelope
  field and one human warning line, so the envelope can never claim a different pairing
  than the text printed beside it.
- Emit the field on both already-running outcomes and on the freshly-started outcome, and
  print the warning line only when the pairing is not a confirmed match.
- Render the same verdict on the status detail view, beside the environment line that
  already identifies the daemon's install.

## Outcome

The attach path is where the defect was operator-visible: identity is confirmed by token
and executable name, both of which a foreign build of the same tool satisfies, so an
operator who had just installed a new client was told the service was already running by a
daemon from the install they had replaced. That path now names both releases.

Both already-running outcomes remain zero-exit successes carrying the already-done status.
An already-satisfied request is a success, and the release verdict travels with the
outcome rather than changing it - a client that refused to attach could not stop the
daemon it was complaining about either.

The structured field is emitted on every start outcome that reaches a daemon, matched or
not, so a broker reads the pairing from a field that is always present instead of
inferring it from the absence of a warning. The human line is conditional, because a
matched pairing is not news.

The freshly-started path carries the verdict too: the daemon runs in the interpreter the
CLI selected for it, which is not necessarily the CLI's own install, so a just-started
daemon can still be a different release than the client that started it.

## Notes

The MCP surface was left unchanged. It reads no health payload today and reaches the
daemon through the shared port resolution, so it inherits the discriminator refusal from
the preceding step without a second implementation; surfacing the release verdict through
an MCP tool would mean adding a status surface that does not currently exist, which is
outside this decision.

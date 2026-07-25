---
tags:
  - '#exec'
  - '#service-release-compat'
date: '2026-07-25'
modified: '2026-07-25'
step_id: 'S02'
related:
  - "[[2026-07-25-service-release-compat-plan]]"
---

# Enforce the discovery discriminator at both readers, refusing an unrecognised shape and resolving a live holder's foreign pointer as degraded

## Scope

- `src/vaultspec_rag/serviceclient/_discovery.py`

## Description

- Add the predicate that decides whether this build understands a discovery payload's
  declared shape, beside the constants it pins on.
- Accept a payload declaring neither half of the pair as the pre-discriminator case, and
  refuse a payload declaring one half without the other or declaring the pair with values
  this build does not recognise.
- Wire the predicate into the status-file reader, which now returns nothing for a shape it
  cannot claim to understand.
- Wire it into the machine-singleton resolver, before any field of the payload is read,
  adding a refusal reason distinct from the existing invalid-pointer reason.

## Outcome

The published instruction to pin on the pair and refuse a file you do not understand is
now behaviour rather than prose. Before this, both writers stamped the pair and no reader
compared it; the only comparisons anywhere in the tree were in test fixtures.

The pre-discriminator tolerance is load-bearing in both directions. Accepting a payload
that declares neither half keeps an ordinary in-place upgrade from reading as a foreign
build, since the next daemon heartbeat rewrites the file with the pair. Refusing a payload
that declares only one half catches a partial or truncated write, a shape this build
equally cannot vouch for.

The resolver reports the refusal as degraded rather than absent because a live holder does
own the machine singleton either way, and reporting it as stopped would invite a caller to
start a second daemon that must then lose the race. None of the foreign payload's fields
are carried onto the resolution, since this build cannot say what they mean.

## Notes

The integer check is an exact type test rather than an instance check, because a boolean
would otherwise satisfy a version-one pin. This mirrors the rejection idiom already used
by the watcher retry state reader, which was the only strict "refuse a schema I do not
understand" reader in the tree before this change.

The refusal is deliberately not extended to the release field. A shape this build cannot
parse has a safe refusal; a differently-released daemon does not, because the client that
would refuse it is also the only thing that can stop it.

---
tags:
  - '#exec'
  - '#service-release-compat'
date: '2026-07-25'
modified: '2026-07-25'
step_id: 'S03'
related:
  - "[[2026-07-25-service-release-compat-plan]]"
---

# Publish the package release on the health route, the readiness report, the daemon discovery snapshot, and the launcher status write

## Scope

- `src/vaultspec_rag/server/_lifespan.py`

## Description

- Stamp the release onto the health route's payload, beside the storage-schema version
  and the environment fields that already identify the daemon.
- Stamp it onto the readiness report, beside the storage-schema descriptor.
- Stamp it onto the daemon's discovery snapshot, beside the interpreter version and the
  environment paths.
- Stamp it onto the launcher's status write, so the field is present from the moment the
  file exists rather than only after the first heartbeat.

## Outcome

The release now crosses the process boundary on every surface that already identifies the
serving process. Before this the package version was referenced nowhere outside the
package's own module init, so no client had a datum to compare - the gap was the absent
value, not an absent check.

Publishing on the health route specifically is what makes the signal usable before
authentication: that route is ungated while the readiness route requires a token, so it is
the only surface a client can consult to learn which build it is about to drive before it
holds credentials.

The launcher and the daemon both write the field, and they can legitimately disagree for
the length of a cold start: the launcher writes its own release, and the daemon overwrites
it with the serving build's on the first heartbeat. Until then the launcher's value is the
only release the file can honestly report.

## Notes

Additive only. The discovery schema version is deliberately not bumped: the published
contract states additive fields do not bump it, and bumping it here would make every
existing file unreadable by the gate added in the preceding step.

The interpreter version was already published in the discovery snapshot and read by
nothing. The release field sits beside it and is read by the adapters, so this does not
repeat that pattern; a test asserts the two carry different values so they cannot be
conflated.

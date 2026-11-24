---
tags:
  - '#adr'
  - '#service-model-residency'
date: '2026-11-24'
modified: '2026-11-24'
body_schema: 'body-v2'
body_hash: 'sha256:0470283866c151fd44c3a537ffaedab738f5dbf5be7d45a0ac516b2568353a70'
related:
  - "[[2026-04-02-service-graph-adr]]"
  - "[[2026-07-24-service-quiesce-adr]]"
  - "[[2026-05-30-service-lifecycle-adr]]"
  - '[[2026-11-24-service-model-residency-research]]'
---
# `service-model-residency` adr: `Optional prewarm and idle model release` | (**status:** `accepted`)

## Problem Statement

A service start always loads the full model set before it accepts a connection (`src/vaultspec_rag/server/_lifespan.py:520`), and the models then stay resident for the life of the process. Two costs follow. Every test whose subject is the service itself (start, stop, restart, eviction, discovery) pays a model load and needs the card, so the accelerator lane measured 97 minutes on the last complete run, about 20 of them in starts that assert nothing about a model. And a service nobody has queried for hours still holds about 3 GB of VRAM on a workstation whose card other work is waiting for.

## Considerations

- The accepted start-up rule is that models load eagerly so consumers never hit a cold model load (`2026-04-02-service-graph-adr`, D5). That stays the right default for an operator.
- The service already releases its models and warms them again around a GPU borrow (`2026-07-24-service-quiesce-adr`). Releasing on idleness is the same release, triggered by a clock.
- A switch that exists only for tests is forbidden; whatever the tests use must be an operator feature in its own right.
- Health already reports whether models are loaded (`src/vaultspec_rag/server/_health.py:589`); a service without resident models must read as ready, not as degraded.
- A reload costs 13 to 27 seconds on the reference card, measured in the test daemon's start-up.

## Considered options

- **Optional prewarm, on by default, plus idle release after a configurable interval (chosen).** Keeps today's behaviour for every operator who changes nothing, gives a fast start to those who ask for it, and returns VRAM a quiet service is not using.
- **Keep eager loading only, and reduce the number of starts in the tests.** Cannot reach one model-loaded service per run, because a restart test must start a service, and leaves an idle service holding the card. Rejected.
- **A test-only environment switch that skips loading.** A symbol kept alive for tests, proving nothing about what ships. Rejected.
- **Always load on demand.** Moves the cold load onto the first search of every service life, which the default exists to prevent. Rejected.

## Constraints

- Prewarm is the default. A start that does not ask otherwise loads the model set before it reports ready, exactly as before.
- A start may decline prewarm through one start option and its environment setting. Such a service reports ready without resident models, and loads them on the first search or index work that needs them, through the one centralised loader and under the same device admission as a prewarmed start.
- A service without resident models is healthy. Health, status and the monitor report that state by name; none of them reports a degradation for it.
- A service releases its resident models after a configurable interval with no search and no index work, 30 minutes by default; an interval of zero disables the release. Any search or index work resets the interval. An index job in flight is never interrupted by it.
- The idle release uses the release the quiesce protocol already owns. There is one way to release models and one way to warm them.
- The first request after a release, or after a start without prewarm, waits for the load and then answers; it is not refused.
- This record amends the start-up paragraph of `2026-04-02-service-graph-adr` D5 only in that eager loading becomes the default and stops being unconditional. Everything else in that record stands.

## Implementation

We will add a prewarm setting to the service configuration, on by default, exposed as a start option and an environment variable, and make the lifespan's model load conditional on it. Work that needs a model obtains it through the registry's loader, which loads on first use when nothing is resident. We will add an idle clock to the registry, reset by search and index admission, that triggers the existing model release when the interval elapses. The interval is a setting. Whether the clock is a timer task or is evaluated on the heartbeat is an implementation hypothesis and may change.

Service tests whose subject is the service and not a model start their services without prewarm, and one prewarmed service serves every test that needs models.

## Rationale

The default protects what the earlier decision protected, so no operator sees a change they did not ask for. The option is a real operator feature (a service that is up in seconds and pays for models only when used), which is what lets the lifecycle tests use it honestly. The idle release adds no second mechanism, because the release and the warm-up already exist and are already exercised by every borrow.

## Consequences

- The accelerator lane keeps one model-loaded service; lifecycle tests no longer need the card.
- A long-quiet service gives its VRAM back, and its next request is slower by one load.
- Operators and front ends see a new healthy state, ready without resident models, and must not treat it as a fault.
- If the measured reload time grows well past half a minute, or operators report the first-request delay as a problem, the default interval should be reconsidered.

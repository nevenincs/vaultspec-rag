---
tags:
  - '#reference'
  - '#gpu-admission-unreadable'
date: '2026-08-14'
modified: '2026-08-14'
body_schema: 'body-v1'
body_hash: 'sha256:9ce857e465b26bc487186a18d470d057b7a12eb790f0a9a792f483aad583f248'
related:
  - "[[2026-07-29-gpu-admission-gate-adr]]"
---

# `gpu-admission-unreadable` reference: `degraded-device evidence behind the admission refusal`

What the host actually did while the device was failing, and what it does now
that the device is gone. Gathered on the workstation across the incident and
the day after, when the card was absent from the machine entirely - a condition
worth spending, because a GPU-less host exercises paths that a working one
never reaches.

## Summary

### The incident, from the service log

The device was lost at the driver level mid-run. `nvidia-smi` reported the GPU
as lost and needing a reboot to recover, while Windows still listed the device
as healthy with a PnP status of OK. Nothing was logged by the display driver,
WHEA, PCI, or Kernel-PnP at any level in the preceding 24 hours: a silent
handle loss, not a reported fault.

The driver fault itself is not this project's to fix. What is this project's is
what followed. Between 06:55:02 and 08:04:20 the service emitted:

- **79** admission warnings reading `device free memory is unreadable;
  admitting the load on presence alone`.
- **112** job failures reading `CUDA error: unknown error`.

The run ended when an operator terminated the daemon by hand. No internal
condition would have stopped it: the admission check held no memory, so the
seventy-ninth unreadable reading was answered exactly as the first.

The two safeguards the fail-open was written to lean on did not apply. The
per-job CUDA ceiling and the allocator's backoff both assume a device that
answers a query; against one raising on every call, neither is ever consulted.

### What a reading looks like in each degraded state

The distinction the gate turns on is not visible from the count of absent
figures - both states report no free memory - but from the presence flag:

- **Device failing, driver still claiming it.** Presence true, free figure
  absent. This is the incident state and the one the gate had no answer for.
- **Device gone.** Presence false. Observed directly on the host the day after,
  where the project's own probe reported torch present, CUDA absent, and every
  figure absent. The gate already refuses this correctly, under a reason
  naming the absent device.

Total memory and free memory are read through different calls, so a driver can
answer one and refuse the other. A reading that is empty in every dimension is
therefore a weaker fixture than one that reports a size and refuses only the
free figure.

### How the operator surfaces behave with no device

Exercised on the GPU-less host rather than reasoned about:

- `server preflight --json` emits one envelope, reports `ok: false` with a
  named error, and exits 1. The service-surface contract holds.
- A search with no running service refuses rather than silently opening the
  local index, names three next actions, and exits 1.
- The fast test lane passes whole - 4240 passed, 2 skipped, exit 0 - which is
  also evidence about the lane itself: it is genuinely CPU-only, since it ran
  green on a host with no device at all.

The degradation defect is therefore confined to admission. Nothing else
surveyed on this host mistakes an absent device for a working one.

### Reading the exit code, not the output

One methodological note that cost time twice. Several of these surfaces print a
payload that reads as success while exiting non-zero, and a command whose
output is piped reports the pipe's status rather than its own. An observation
about any of these paths is only worth what its exit code says, captured
directly.

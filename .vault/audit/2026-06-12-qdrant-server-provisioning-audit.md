---
tags:
  - '#audit'
  - '#qdrant-server-provisioning'
date: '2026-06-12'
related:
  - "[[2026-06-12-qdrant-server-provisioning-adr]]"
  - "[[2026-06-12-qdrant-server-provisioning-plan]]"
---

# `qdrant-server-provisioning` Code Review

One reviewer pass against the feature ADR, focused on the download/exec security
boundary and the supervision lifecycle. Verdict: PASS - no CRITICAL or HIGH
findings. The pinned SHA256 table was independently verified byte-for-byte against
the live upstream release. Three MEDIUM findings were fixed in-branch the same day;
the remainder are LOW observations kept for the record.

## SEC-04 | MEDIUM | Redirect handler did not re-check the HTTPS scheme

The cross-host redirect guard rejected off-host redirects but a downgrade to http
on an allowed host would have stripped TLS while passing the host check. FIXED: the
redirect handler now rejects any non-HTTPS redirect target as firmly as a
cross-host one, matching the initial-URL guard.

## LIFE-02 | MEDIUM | Published QDRANT_URL env was never restored on shutdown

The lifespan published the in-process server URL into the process environment for
the daemon's lifetime but never cleared it on shutdown, so an embedded
lifespan-then-continue caller would keep reading server mode against a dead port.
FIXED: shutdown pops the env var, guarded so an operator-supplied remote URL is
left untouched.

## TEST-01 | MEDIUM | Security boundary shipped without direct test coverage

The host/scheme refusal, the redirect-downgrade rejection, the archive
path-traversal flattening, and the pre-execution digest-mismatch refusal - the
load-bearing security logic - had no direct tests. FIXED: added real negative
tests for each (non-HTTPS URL refused, cross-host URL refused, redirect downgrade
and cross-host rejected, a traversal archive member flattened into the
destination, and a tampered provisioned binary refused before spawn).

## SEC-01 | LOW | Download had no upper size bound

A host-pinned-but-defective response could fill the disk before the checksum check
rejected it. FIXED (defense in depth): the stream is capped at 256 MB - far above
the ~30 MB assets - and aborts past the cap.

## SUP-01 | LOW | Windows Job-Object handle lifetime was undocumented

The kill-on-close orphan guard depends on the job handle being held for the
supervisor's whole lifetime and never explicitly closed. FIXED (documentation): a
comment now records that the deliberate handle hold IS the guarantee and that a
supervisor must never be dropped-and-recreated while its child runs.

## SEC-02 | LOW (clean) | Archive extraction discards embedded paths

The extractor matches the binary member by basename and writes only to the
destination dir; archive-embedded paths are discarded, so traversal is structurally
impossible. Now covered by an explicit negative test (TEST-01).

## SEC-03 | LOW (clean) | Verify-before-execute is sound

Verification precedes extraction and a second pre-execution re-hash precedes spawn;
checksum mismatch deletes the partial and raises. The covering codification
candidate is warranted.

## STORE-01 | LOW (clean) | Namespacing and backend-aware locking are consistent

The per-root blake2b-6 prefix is case-normalised and resolution-correct; the
per-collection lock dict is keyed by the namespaced names in server mode and the
bare names in local mode; server mode takes no point-operation locks - matching the
storage-locks-are-backend-aware rule. Proven by the two-root integration test.

## SUP-02 | LOW | Disk-full surfaces opaquely but never hangs

Every supervision wait is monotonic-deadline-bounded and short-circuits on child
death, so a wedged server cannot hang the caller. A disk-full failure during
readiness shows only the generic timeout-plus-log-path message; acceptable.

## SUP-03 | LOW | A failed restart still consumes the one-shot restart budget

The restart counter increments before the spawn attempt, so a transient spawn
failure permanently exhausts the bounded restart budget and the service degrades
until manual intervention. The degraded-state surfacing is correct; recorded.

## Verdict

PASS. The download/exec security boundary is sound (genuine pinned digests,
verify-before-extract, second pre-exec re-hash, host+scheme pin, traversal-proof
extraction, no silent provisioning) and the supervision lifecycle is crash-free and
non-hanging (bounded waits, child-death short-circuit, Job-Object kill-on-close,
bounded restart, qdrant stopped last among data components). The three MEDIUM items
were fixed and re-tested in-branch the same day; the integration suite passes
end-to-end against the real binary when the disk has space.

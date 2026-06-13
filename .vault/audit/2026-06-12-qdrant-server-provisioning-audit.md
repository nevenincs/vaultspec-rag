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

## QUALITY-01 | validation | Server-mode search result quality verified against ground truth

After the 469k-chunk A/B proved the latency win (qdrant phase 70.9s -> 0.03s), an
adversarial result-quality audit confirmed the speedup does NOT sacrifice
correctness. Findings: ground-truth verification of ~25 inspected top hits against
the real source files showed ~100% valid path + accurate line range + verbatim
snippet; a purely conceptual query ("four year window IVA compensation expiry
enforcement") ranked the exact implementing function #1 at 0.966; duplicate-
definition discovery surfaced a genuine 8-way near-duplicate helper pattern;
filters constrain correctly (a no-match filter returns empty, not everything); 36
concurrent mixed searches at concurrency 10 all succeeded with the qdrant phase
holding 0.013-0.043s and zero cross-request contamination; and 16 adversarial
probes (empty, 5000-char, regex/SQL metacharacters, unicode, nonsense, top_k
extremes, invalid root) all degraded gracefully - a nonsense query scored 0.0008
(no fabricated confidence), an invalid root returned a clean HTTP 400, top_k was
bounded to [1,100]. The qdrant child logged 0 restarts across the audit. Verdict:
server-mode retrieval is correct, relevant, robust under load, and graceful under
adversarial input.

## QUALITY-02 | LOW | Pre-existing envelope/metadata nuances (not server-mode regressions)

The quality audit surfaced three minor, pre-existing observations independent of
server mode: (1) vault result `path` omits the `.vault/` prefix (stored relative to
the docs dir, as doc IDs always have been) - files still resolve; (2) a chunk that
spans a class tail into an adjacent module-level def attaches both `class_name` and
`function_name` even though they are not a method-of-class relationship (an AST
chunker artifact; both names are truthfully within the chunk) - consumers must not
assume `function_name` is a method of `class_name`; (3) empty/whitespace queries are
accepted and scored rather than rejected. None affect retrieval trustworthiness;
logged as backlog for a future search-envelope cleanup.

## Verdict

PASS. The download/exec security boundary is sound (genuine pinned digests,
verify-before-extract, second pre-exec re-hash, host+scheme pin, traversal-proof
extraction, no silent provisioning) and the supervision lifecycle is crash-free and
non-hanging (bounded waits, child-death short-circuit, Job-Object kill-on-close,
bounded restart, qdrant stopped last among data components). The three MEDIUM items
were fixed and re-tested in-branch the same day; the integration suite passes
end-to-end against the real binary when the disk has space.

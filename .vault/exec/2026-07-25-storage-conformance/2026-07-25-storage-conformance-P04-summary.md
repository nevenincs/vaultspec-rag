---
tags:
  - '#exec'
  - '#storage-conformance'
date: '2026-07-25'
modified: '2026-07-25'
related:
  - "[[2026-07-25-storage-conformance-plan]]"
---

# `storage-conformance` `P04` summary

## Description

Closes the propagation holes that let a namespace present conformance it never
established, and settles one Step whose behaviour was already in place.

A migrate now carries its source's identity onto the remapped target name. The
hole was not a false stamp, as the Step row supposed: nothing stamps a migrate
destination at all, because the stamp fires only inside a genuine create and the
copy builds its target through the raw client. The manifest re-key appeared to
cover this and did not - it carries the identity map under source collection
names, which a remap makes unlookupable. Only an applied copy is carried, and an
unstamped source carries nothing rather than inheriting current values.

An archive snapshot now records what produced each collection it preserves,
written as an explicit null when nothing was recorded. This is load-bearing for
reclamation: the drop that follows a successful data-tier archive destroys the
manifest entry the identity lived in, so the archive is the only copy a restore
could be judged against.

The reclamation exclusion was already satisfied and needed no change; the
evaluator considers reachable-root orphans only, asserted by a test predating
this feature. The plan's verification criterion for it is stronger and wrong -
honouring it literally would exempt every pre-upgrade namespace from reclamation
forever, since an orphan's root is gone and can never be rebuilt into a stamp.
The invariant is now stated at the site and locked in both directions, and the
divergence is recorded rather than quietly resolved.

Nine guards, ten mutation proofs, each observed failing on the assertion it
names and restored green in one uninterrupted sequence. Two proofs were rejected
on first pass and the tests tightened to assert presence before reading, so a
lost record fails as an assertion rather than a `KeyError`.

One gate regression was found and fixed. The cognitive-complexity gate had been
failing since this feature's first commit, where identity parsing was added
inline to the manifest loader; the closing gate run recorded all gates clean
without it. The per-record parse is now extracted and the gate is green.

- Modified: `src/vaultspec_rag/storage_ops.py`
- Modified: `src/vaultspec_rag/storage_manifest.py`
- Modified: `src/vaultspec_rag/cli/_service_storage.py`
- Modified: `src/vaultspec_rag/tests/test_storage_ops.py`
- Modified: `src/vaultspec_rag/tests/test_storage_manifest.py`
- Modified: `src/vaultspec_rag/tests/integration/test_storage_ops_integration.py`

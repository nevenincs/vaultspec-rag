---
tags:
  - '#exec'
  - '#index-drift-hardening'
date: '2026-07-13'
modified: '2026-07-13'
body_hash: 'sha256:85c2067c3d6b680f08a150bbd9ee2fbac2ac30c085939ab56d4d7d200fdb577b'
step_id: 'S06'
related:
  - "[[2026-07-13-index-drift-hardening-plan]]"
---

# Create the TOFU trust store: preprocess-trust.json sidecar under the managed status dir keyed by root collection prefix, canonical-JSON blake2b of the resolved rule set, atomic tmp-plus-replace writes under a lock, degrade-on-corrupt to untrusted, read/write/remove/hash helpers

## Scope

- `src/vaultspec_rag/indexer/_preprocess_trust.py`

## Description

- Create the TOFU trust store module, mirroring the storage-manifest sidecar pattern: a `preprocess-trust.json` under the managed status dir, keyed by root collection prefix, never inside the repo.
- Add a frozen `TrustRecord` dataclass (prefix, root, rule-set hash, trusted-at ISO stamp).
- Implement `hash_rule_set` over the resolved ordered rule set: canonical JSON (`sort_keys`) of per-rule pattern, command/entry_point, on_error, priority, resolved timeout, options, and order, blake2b-hashed.
- Implement `load_trust_store`, `read_trust`, `is_trusted`, `record_trust`, `remove_trust`, `remove_prefix`, and `trust_store_path` helpers.
- Write atomically via a tmp sibling plus `os.replace` under an RLock; degrade a corrupt or unreadable store to empty (untrusted) with a warning, never raising.

## Outcome

The store persists per-root trust decisions durably and safely. `is_trusted` matches only when a record exists and its stored hash equals the freshly-computed hash, so a changed rule set reverts to untrusted with no TOCTOU. Reuse of `root_collection_prefix` keys records to the same one-way hash the server-mode namespace uses. The module is stdlib-only (`hashlib`/`json`/`pathlib`/`threading`) and imports the store's prefix helper at module scope but is itself imported only function-locally from the loader, so the CPU-only spawn worker import chain stays torch-free. Ruff, basedpyright clean.

## Notes

`hash_rule_set` accepts an iterable of rules and imports the rule type only under `TYPE_CHECKING`, so the trust module carries no runtime dependency on the preprocess-config module and the two do not form an import cycle. Options tables can carry non-JSON-native values (e.g. TOML datetimes); the serialiser uses `default=str` so hashing never raises on an exotic option value.

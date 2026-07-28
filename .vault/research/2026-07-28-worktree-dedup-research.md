---
tags:
  - '#research'
  - '#worktree-dedup'
date: '2026-07-28'
modified: '2026-07-28'
body_schema: 'body-v1'
related: []
---

# `worktree-dedup` research: `Duplicate corpora across worktree clones`

This machine runs many git worktrees of the same repositories, and the working
assumption behind opening `worktree-dedup` was that each one indexes its own
copy of the same content into its own collections, so the same corpus is
encoded and stored N times against one GPU, one disk, and one Qdrant. The
question this document answers is how much of that is true on the machine as it
stands, and what is left to decide after the accepted encode-seam reuse record
(`2026-07-24-worktree-index-reuse-adr`) took the compute half.

The evidence does not support the premise as stated. Six live worktrees of this
repository exist and exactly one of them holds a stored namespace: the indexer
excludes nested agent worktrees from traversal outright, and the domain
classifier demotes anything on a worktree path to noise. Across the whole
managed backend - 5.3 GB, 15 collections, 7 manifest roots spanning three
distinct repositories and three harness temp directories - cross-worktree
duplication accounts for exactly one namespace pair, 967 MB or 18%, and that
namespace is already an orphan the existing reclamation lifecycle is built to
reclaim. Two larger terms sit beside it that are not worktree duplication at
all: superseded index generations within a single root (20%) and fixed
per-collection preallocation, which `2026-07-21-storage-prealloc-reclaim-adr`
measured at roughly 84% of a backend's footprint and already decided how to
converge. The option space that remains is narrow, and it is the same
storage-dedup option the encode-seam record priced and decoupled rather than a
new one.

## Findings

### A root becomes a namespace by path hash, one prefix to one root

A root is identified by its resolved, case-normalised path, hashed to a short
prefix of the form `r{12-hex}_` (`src/vaultspec_rag/_store_models.py:170`).
Windows extended-length prefixes are stripped before resolution because
`Path.resolve()` does not reliably collapse them, and an aliased spelling of an
already-registered root would otherwise mint a duplicate namespace for the same
project. Resolution failure falls back to lexical normalisation, so a root that
is unreachable rather than absent keeps the namespace it had.

The prefix concatenates with three fixed collection names - vault, codebase,
document - to produce that root's collections
(`src/vaultspec_rag/store_schema.py:117`). Nothing in the naming consults
content. Two roots holding byte-identical trees therefore land in two disjoint
sets of collections by construction, and the 1:1 prefix-to-root relation is the
invariant the entire storage lifecycle surface is built on: the survey groups
live collections by prefix and joins each to the persisted prefix-to-root
manifest to classify it (`src/vaultspec_rag/storage_survey.py:149`), and every
destructive verb acts on that verdict.

Worktrees are not invisible to the system, but the handling is exclusion rather
than sharing. The codebase indexer's fixed ignore patterns drop
`.claude/worktrees/` from traversal before any file is read, with the stated
reason that clone trees duplicate the real source verbatim and indexing them
floods results with identical-score duplicates
(`src/vaultspec_rag/indexer/_ignore_specs.py:57`). Independently, the domain
classifier labels any path under a `.claude/worktrees` or `.git/worktrees`
segment pair as the `worktree` domain, and gives that label first precedence so
an inner `src/` inside a clone still classifies as `worktree` rather than
`prod` (`src/vaultspec_rag/_domain.py:127`, `src/vaultspec_rag/_domain.py:188`).
Search hides the domain from production-biased results by default. The net
effect is that a worktree nested inside an indexed root contributes nothing to
that root's corpus, and can only become duplicate storage by being indexed as a
root in its own right.

### Content identity is already established, and already consumed by the compute path

Three mechanisms already answer "is this the same content", at three different
granularities, and all three are read-only and shipped.

Per point: point ids are deterministic and content-addressed, and a donor
point's stored payload content is compared byte-for-byte against the expected
chunk before its vector is adopted. The read path itself is
`retrieve_donor_points` (`src/vaultspec_rag/store_donors.py:57`), which hashes
plain string ids through the same stable point-id scheme the store writes with,
pages in bounded batches, takes the donor collection's own lock in local mode
and no lock at all in server mode, and treats every form of absence - missing
collection, missing point, missing dense vector - as a silent miss rather than
an error.

Per collection: an identity stamp records what produced a collection's vectors -
models, width, distance, vector names - written once at creation and read back
through one accessor with two backend-specific homes, the manifest entry in
server mode and a per-root sidecar in local mode
(`src/vaultspec_rag/storage_identity.py:84`,
`src/vaultspec_rag/storage_identity.py:127`). Absent evidence is deliberately
rendered `unverifiable` rather than treated as a match; the module's own note is
that scoring absent evidence as passing is the silent failure the mechanism
exists to remove.

Per root and kind: a content-epoch sentinel plus an embedding-schema marker are
read from the donor root's own metadata sidecar
(`src/vaultspec_rag/indexer/_donor_candidates.py:263`), and donor eligibility
requires same collection kind, identical dense dimensionality and named-vector
layout, identical recorded model identity, and epoch equality - with any gate
that cannot be evaluated failing closed
(`src/vaultspec_rag/indexer/_donor_candidates.py:468`).

Worktree kinship is detected, but only as a ranking hint. `_git_common_dir`
resolves a linked worktree's `.git` file to the shared repository dir by
filesystem inspection with no subprocess
(`src/vaultspec_rag/indexer/_donor_candidates.py:303`), and `_family_rank`
ranks a donor sharing that common dir first, a donor sharing a parent directory
second (`src/vaultspec_rag/indexer/_donor_candidates.py:337`). Both are
explicitly documented as carrying no correctness weight; candidates are capped
at three (`src/vaultspec_rag/indexer/_donor_candidates.py:97`). The system
therefore already knows which stored namespaces are sibling worktrees of the
root it is indexing. It uses that knowledge to skip encoding, never to skip
storing.

### Reclamation of a duplicated corpus already exists, with the full safety stack

A namespace whose root is gone is exactly the shape a stale worktree corpus
takes, and the destructive path for it is complete.

Classification distinguishes three verdicts and never conflates absence with
unreachability: `live` when the root exists, `orphaned` only when the root is
definitively absent AND its drive or share anchor is itself reachable, and
`unverifiable` on any OSError or an absent anchor - so a disconnected share or
unplugged drive is reported but never pruned
(`src/vaultspec_rag/storage_manifest.py:576`). A prefix with no manifest entry
at all is `unknown` and is likewise reported and never auto-pruned, because
deleting an unattributable namespace could destroy live data
(`src/vaultspec_rag/storage_survey.py:8`).

The grace window is persisted and measures continuous orphan-hood. A newly
observed orphan is stamped once and an existing stamp is preserved across daemon
restarts; any other observation - `live` or `unverifiable` - clears the stamp,
so a reappearing or merely unreachable root restarts its window from zero
(`src/vaultspec_rag/storage_manifest.py:619`). The concurrency race is
delete-safe by construction: a stamp lost to a competing writer restarts the
window, so protection can only be extended, never shortened.

Windows are tiered by whether the namespace holds points: 24 h for an empty
namespace, 168 h for a point-bearing one, with a hard per-cycle cap and empty
namespaces ordered first so the riskless tier reclaims first under a tight cap
(`src/vaultspec_rag/storage_reclamation.py:66`,
`src/vaultspec_rag/storage_reclamation.py:304`,
`src/vaultspec_rag/storage_reclamation.py:239`). Only `orphaned` entries ever
appear in the output; a missing or unparsable stamp means the window has just
started.

Immediately before acting, three further gates run in order: an active-index
liveness probe defers the namespace outright, points are re-counted because the
survey reading can be minutes stale, and any movement since the survey defers
(`src/vaultspec_rag/storage_reclamation.py:729`). A point-bearing namespace is
archived before it is destroyed, and if the point count moved during the archive -
meaning the snapshot is torn - the delete is skipped and the archive is
reported anyway (`src/vaultspec_rag/storage_reclamation.py:661`,
`src/vaultspec_rag/storage_reclamation.py:379`). Path containment is proven by
full resolution of both target and base before any filesystem removal, closing
parent-traversal and symlink escape (`src/vaultspec_rag/storage_safety.py:30`).

Two adjacent tiers exist for shapes that are not orphans. Live but temp-rooted
namespaces - the shared-backend leak signature, a harness temp dir that still
exists but is never indexed again - reclaim on an idle TTL against the persisted
`last_indexed` stamp, defaulting to 72 h and still flowing through the unchanged
empty/data tiers (`src/vaultspec_rag/storage_survey.py:46`,
`src/vaultspec_rag/storage_reclamation.py:162`). Superseded index generations
within a live root have their own unreferenced-hours grace and drop path
(`src/vaultspec_rag/storage_reclamation.py:1054`).

### Measured: the duplication factor for this repository is 1.0, not N

Six worktrees of this repository exist - `main` plus five `agent-*` trees under
`.claude/worktrees/`. The persisted manifest at
`C:\Users\hello\.vaultspec-rag\storage-manifest.json` (schema version 2) records
seven roots, and none of the five live agent worktrees is among them. The only
namespace attributable to this repository's live tree is the one for `main`.

The manifest's seven roots, checked for existence read-only at the time of
writing:

| Prefix           | Root                                  | Verdict           | Collections | Footprint |
| ---------------- | ------------------------------------- | ----------------- | ----------- | --------- |
| `r01fa8eefb788_` | a second project's main tree          | live              | 4           | 2,087 MB  |
| `rea7120f40662_` | this repository's main tree           | live              | 4           | 1,237 MB  |
| `r181a619b05b0_` | a deleted worktree of this repository | orphaned          | 3           | 967 MB    |
| `raba11d8547a9_` | a third project's main tree           | live              | 2           | 583 MB    |
| `ra79c89ada258_` | harness temp directory                | live, temp-rooted | 1           | 255 MB    |
| `rb922ad924764_` | harness temp directory                | live, temp-rooted | 1           | 255 MB    |
| `rb1d848af2c20_` | harness temp directory                | live, temp-rooted | 0           | 0         |

Fifteen collections, 5.3 GB total measured on the collections tree. Verdicts are
this document's own application of the classification rules above to observed
filesystem state, not a reading taken from the running service, which was not
contacted.

Cross-worktree duplication in the entire backend is one pair: the live namespace
for this repository's main tree and the orphaned namespace for its deleted
`convergence-cost` worktree, 967 MB, 18% of the backend. Every other pair of
namespaces holds a different repository or a different temp directory. The
orphan's manifest entry carries an empty `first_seen_orphaned` field, so its
grace clock has not started; why it has not is not established here and would
require inspecting the running service.

### The footprint is not mostly duplicated content

Decomposing the measured 5.3 GB:

- Live primary namespaces of three distinct repositories: 2,847 MB, 52%.
- Superseded index generations inside two live roots - collections suffixed
  `_g{token}` sitting beside their declared name: 1,060 MB, 20%. This is
  intra-root, produced by non-destructive publication, and governed by the
  generation reclaim path, not by anything worktree-shaped.
- The one cross-worktree duplicate namespace: 967 MB, 18%.
- Harness temp namespaces: 510 MB, 10%, owned by the ephemeral idle tier.

Underneath all four terms sits a fixed floor. The smallest namespace observed -
a single vault collection over a throwaway temp directory - measures 255 MB, and
every collection in the backend is at or above that figure regardless of how
much content it holds; fifteen collections at that floor would be 3.8 GB of the
5.3 GB. This is consistent with `2026-07-21-storage-prealloc-reclaim-adr`, which
measured roughly 84% of a 38.0 GB backend as fixed preallocation rather than
data, with zero-point collections occupying 1.22 GB each, and decided in-place
geometry reconcile as the convergence mechanism. Deduplicating content attacks
the smaller term of the two, and does so only where duplication actually exists.

### The remaining option space, and why it is not new

The encode-seam record enumerated the storage-dedup option under its own name
and did not reject it: payload-partitioned shared collections with the root as a
payload tenant, which it deliberately decoupled to a separate future record
rather than bundling behind the GPU fix, and whose costs it priced as
falsifying the 1:1 prefix-to-root invariant, inverting grace semantics to
membership refcounts, degrading local mode, and re-concentrating writes against
the lock-split lesson. Its consequences section states plainly that per-root
storage duplication remains and that storage dedup stays a separate future
decision. That is the open slot `worktree-dedup` would fill, and the evidence
here bears on whether filling it is worth the invariant.

Two nearby options are not genuinely available. Reclaiming a duplicate corpus by
detecting that its content matches another root's is the corpus-level similarity
judgment the encode-seam record rejected outright on correctness grounds, and it
would have to either bypass or re-implement the classification, persisted-grace,
liveness, re-count, and archive gates catalogued above. Aliasing sibling
worktrees onto one namespace falsifies the same 1:1 invariant as the tenant
option while achieving, for nested agent worktrees, only what traversal
exclusion already achieves.

What the follow-on record must settle is therefore narrow: whether to open the
deferred storage-dedup decision now on this measurement, and if not, what
observable condition should reopen it.

### Not investigated

Point counts and any live survey verdict, because contacting the running service
was out of scope - a repair session held it at the time of writing. The
local-mode backend, which has no manifest entries by construction and stores
per-root under each root's own directory. Why the orphaned namespace's grace
stamp is unset. GPU cost of duplicate indexing, which the encode-seam record
already measured directly (311 s baseline against 28.7 s with full reuse) and
which is not re-derived here. Whether other machines running this project show a
different worktree-indexing pattern; every figure above is one machine at one
moment.

## Sources

In-repo, verified in the working tree at time of writing:

- `src/vaultspec_rag/_store_models.py:170` - `root_collection_prefix`, the
  resolved-path hash that names a namespace
- `src/vaultspec_rag/store_schema.py:117` - `collection_names`, prefix to the
  three declared collections
- `src/vaultspec_rag/storage_survey.py:8` - live/orphaned/unknown contract;
  `:46` `is_temp_rooted`; `:149` `classify_namespaces`
- `src/vaultspec_rag/storage_manifest.py:576` - `classify_root`, including the
  `unverifiable` verdict; `:619` `update_orphan_stamps`, continuous-orphan
  clock and its reset rule
- `src/vaultspec_rag/storage_reclamation.py:66` - tiered grace defaults;
  `:162` ephemeral idle tier; `:239` `evaluate_reclaim`; `:304` `_decide_orphan`;
  `:379` `archive_prefix`; `:661` `_apply_reclaim` archive-before-destroy and
  torn-snapshot deferral; `:729` `_pre_drop_reclaim_gate`; `:1054`
  `reclaim_superseded_generations`
- `src/vaultspec_rag/storage_safety.py:30` - `resolve_within` path containment
- `src/vaultspec_rag/storage_identity.py:84` - `load_identity` and the
  absent-evidence-is-unverifiable rule; `:127` `record_identity`
- `src/vaultspec_rag/store_donors.py:42` - `supports_donor_reads` backend
  capability; `:57` `retrieve_donor_points`
- `src/vaultspec_rag/indexer/_donor_candidates.py:97` - donor candidate cap;
  `:263` donor recorded content epoch and schema marker; `:303`
  `_git_common_dir`; `:337` `_family_rank`; `:468` `evaluate_donor_eligibility`
- `src/vaultspec_rag/indexer/_ignore_specs.py:57` - `.claude/worktrees/`
  excluded from codebase traversal
- `src/vaultspec_rag/_domain.py:127` - worktree segment-pair detection; `:188`
  worktree-first domain precedence

Observed machine state, read-only, at time of writing:

- `C:\Users\hello\.vaultspec-rag\storage-manifest.json` - 7 roots, schema
  version 2, one entry with an absent root and an empty `first_seen_orphaned`
- `C:\Users\hello\.vaultspec-rag\qdrant-server\storage\collections` - 15
  collection directories, 5.3 GB total; per-directory sizes as tabulated
- `git worktree list` in this repository - 6 worktrees, 5 of them `agent-*`
  trees under `.claude/worktrees/`

Vault grounding:

- `2026-07-24-worktree-index-reuse-adr` - the accepted encode-seam decision, its
  decoupled storage-dedup option, and its measured GPU figures
- `2026-07-21-storage-prealloc-reclaim-adr` - preallocation as the dominant
  footprint term and in-place geometry reconcile as its remedy
- `2026-07-28-pressure-management-research` - why aggregate machine load from
  duplicate corpora matters, and its statement that the encode-seam decision is
  the higher-leverage fix for that load source

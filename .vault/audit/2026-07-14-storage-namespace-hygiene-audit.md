---
tags:
  - '#audit'
  - '#storage-namespace-hygiene'
date: '2026-07-14'
modified: '2026-07-14'
related:
  - "[[2026-07-14-storage-namespace-hygiene-plan]]"
---

<!-- FRONTMATTER RULES:
     tags: one directory tag (hardcoded #audit) and one feature tag.
     Replace storage-namespace-hygiene with a kebab-case feature tag, e.g. #foo-bar.
     Additional tags may be appended below the required pair.

     Related: use wiki-links as '[[yyyy-mm-dd-foo-bar]]'.

     modified: CLI-maintained last-modified stamp; set at scaffold time,
     refreshed by mutating CLI verbs and vault check fix; never hand-edit.

     DO NOT add fields beyond those scaffolded; metadata lives
     only in the frontmatter. -->

<!-- LINK RULES:
     - [[wiki-links]] are ONLY for .vault/ documents in the related: field above.
     - NEVER use [[wiki-links]] or markdown links in the document body.
     - NEVER reference file paths in the body. If you must name a source file,
       class, or function, use inline backtick code: `src/module.py`. -->

# `storage-namespace-hygiene` audit: `survey snapshot cache and delete --root review`

## Scope

Reviews commit 7ae79ca (branch feat/storage-namespace-hygiene): the daemon-held survey snapshot (state slot, maintenance publish, startup warmer, snapshot-first route with fresh recompute, CLI/transport --fresh) and the root-addressed idempotent `server storage delete --root`, against the accepted ADR, the lifecycle-inertness and time-confirmed-danglingness rules, the broker envelope contract, and concurrency/staleness correctness. Reviewer: vaultspec-code-reviewer persona (read-only).

## Findings

### delete-envelope-remap-scope | medium | `already_absent` remap also changes the prefix-form delete envelope

`src/vaultspec_rag/cli/_service_storage.py` remaps any `skipped`/`no_such_namespace` outcome to `already_absent` regardless of addressing form, so the pre-existing `server storage delete <prefix> --json` envelope for an absent namespace changes from `status: skipped` to `status: already_absent`. Exit codes are unchanged. Resolution: accepted as a deliberate consistency win and documented in `docs/cli.md` (both addressing forms are idempotent); no released consumer exists - the entire delete verb shipped after 0.2.28 and is unreleased, so there is no real-world break. Both forms now satisfy the broker already-satisfied-is-success contract uniformly.

### snapshot-computed-at-not-monotonic | low | a slow fresh compute can overwrite a newer maintenance publish

The fresh path publishes last-writer-wins, so `computed_at` can step backwards by up to one walk duration if a maintenance cycle publishes mid-walk. Within the ADR's eventual-consistency contract (atomic swap + honest `computed_at`; monotonicity was never promised). No action unless a consumer treats `computed_at` as monotonic; noted for the dashboard reply.

### plan-traceability-drift | low | step scope named the wrong test module

`P02.S09` scoped `test_storage_safety.py` but the tests belong in the destructive-verb guard module `test_storage_adversarial.py`. Resolution: plan step scope corrected via the plan CLI; `P01.S07` stays open pending the GPU-gated integration run and is closed with it.

### cli-direct-survey-lacks-freshness-fields | low | the CLI-direct fallback envelope omits `computed_at`/`source`

`_emit_survey_json` diverges from the daemon envelope by omitting the freshness fields. Accepted: the ADR explicitly leaves CLI-direct survey unchanged, and CLI-direct output is always live by construction. Revisit only if a consumer requires the fields on every survey envelope.

### Clean areas

Reviewer explicitly confirmed clean: data-destruction safety (no new destruction path; `delete --root` flows through the unchanged `delete_prefix` gates; HTTP stays read-only), lifecycle-inertness (no `vaultspec_rag.cli` reachable from maintenance; regression test still guards), snapshot thread-safety (immutable value, single atomic assignment, off-loop walks), stale-snapshot correctness (just-reclaimed prefixes dropped before publish), envelope back-compat aside from the medium above, and test quality (no tautologies, no skips, no mocks of the subject under test).

## Recommendations

- Document the idempotent `already_absent` outcome for both addressing forms (done in `docs/cli.md`).
- Reconcile plan traceability (done; S07 closes with the integration run).
- Mention non-monotonic `computed_at` in the dashboard reply so they don't build on a monotonicity assumption.

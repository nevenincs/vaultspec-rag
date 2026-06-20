---
generated: true
tags:
  - '#index'
  - '#storage-lifecycle'
date: '2026-06-19'
related:
  - '[[2026-06-18-storage-lifecycle-W02-P02-S06]]'
  - '[[2026-06-18-storage-lifecycle-W02-P02-S07]]'
  - '[[2026-06-18-storage-lifecycle-W02-P02-S08]]'
  - '[[2026-06-18-storage-lifecycle-W02-P03-S11]]'
  - '[[2026-06-18-storage-lifecycle-W02-P03-S12]]'
  - '[[2026-06-18-storage-lifecycle-W02-P03-S14]]'
  - '[[2026-06-18-storage-lifecycle-W02-P03-S19]]'
  - '[[2026-06-18-storage-lifecycle-W03-P04-S20]]'
  - '[[2026-06-18-storage-lifecycle-W03-P04-S21]]'
  - '[[2026-06-18-storage-lifecycle-W03-P04-S23]]'
  - '[[2026-06-18-storage-lifecycle-W03-P04-S25]]'
  - '[[2026-06-18-storage-lifecycle-W03-P04-S26]]'
  - '[[2026-06-18-storage-lifecycle-W03-P05-S27]]'
  - '[[2026-06-18-storage-lifecycle-W03-P05-S29]]'
  - '[[2026-06-18-storage-lifecycle-W03-P05-S31]]'
  - '[[2026-06-18-storage-lifecycle-W04-P06-S32]]'
  - '[[2026-06-18-storage-lifecycle-W04-P06-S33]]'
  - '[[2026-06-18-storage-lifecycle-W04-P06-S34]]'
  - '[[2026-06-18-storage-lifecycle-W04-P06-S37]]'
  - '[[2026-06-18-storage-lifecycle-W05-P07-S38]]'
  - '[[2026-06-18-storage-lifecycle-W05-P08-S39]]'
  - '[[2026-06-18-storage-lifecycle-W05-P08-S42]]'
  - '[[2026-06-18-storage-lifecycle-W05-P08-S45]]'
  - '[[2026-06-18-storage-lifecycle-adr]]'
  - '[[2026-06-18-storage-lifecycle-plan]]'
  - '[[2026-06-18-storage-lifecycle-reference]]'
  - '[[2026-06-18-storage-lifecycle-research]]'
  - '[[2026-06-19-storage-lifecycle-audit]]'
---

# `storage-lifecycle` feature index

Auto-generated index of all documents tagged with `#storage-lifecycle`.

## Documents

### adr

- `2026-06-18-storage-lifecycle-adr` - `storage-lifecycle` adr: `server-authoritative storage lifecycle surface` | (**status:** `accepted`)

### audit

- `2026-06-19-storage-lifecycle-audit` - `storage-lifecycle` audit: `PR #196 code review`

### exec

- `2026-06-18-storage-lifecycle-W02-P02-S06` - Define the prefix-to-root manifest schema and its on-disk location under the managed service directory
- `2026-06-18-storage-lifecycle-W02-P02-S07` - Write and update the manifest entry whenever a root is indexed
- `2026-06-18-storage-lifecycle-W02-P02-S08` - Add a manifest read and reverse-map helper resolving a collection prefix to its root
- `2026-06-18-storage-lifecycle-W02-P03-S11` - Implement a service-domain survey function that enumerates namespaces, joins the manifest, and classifies live, orphaned, and unknown
- `2026-06-18-storage-lifecycle-W02-P03-S12` - Compute daemon-side byte footprint for each namespace from the server storage tree
- `2026-06-18-storage-lifecycle-W02-P03-S14` - Create the storage CLI group and a survey command with bounded filters and json output
- `2026-06-18-storage-lifecycle-W02-P03-S19` - Add real-backend survey tests for server and local classifying live, orphaned, and unknown
- `2026-06-18-storage-lifecycle-W03-P04-S20` - Implement a service-domain delete that releases the in-memory slot before dropping data and returns busy when the root is in use
- `2026-06-18-storage-lifecycle-W03-P04-S21` - Drop the root namespaced collections in server mode and remove the local store tree only when the store is confirmed closed
- `2026-06-18-storage-lifecycle-W03-P04-S23` - Add a storage delete CLI command with a required explicit target, dry-run preview, confirmation, and json
- `2026-06-18-storage-lifecycle-W03-P04-S25` - Drop the manifest entry on delete
- `2026-06-18-storage-lifecycle-W03-P04-S26` - Add real-backend delete tests for server and local including the busy-root path
- `2026-06-18-storage-lifecycle-W03-P05-S27` - Implement a service-domain prune that selects orphaned namespaces from the manifest and never targets unknown namespaces
- `2026-06-18-storage-lifecycle-W03-P05-S29` - Add a storage prune CLI command with a dry-run preview of exact targets, confirmation, and json
- `2026-06-18-storage-lifecycle-W03-P05-S31` - Add a real-backend prune test that creates an orphaned namespace and asserts it is reclaimed while unknown namespaces are untouched
- `2026-06-18-storage-lifecycle-W04-P06-S32` - Enforce that every destructive op operates only on the resolved root namespaces or managed storage tree and rejects roots outside the allowed base
- `2026-06-18-storage-lifecycle-W04-P06-S33` - Reject path traversal and symlink escape in any path the surface deletes
- `2026-06-18-storage-lifecycle-W04-P06-S34` - Guarantee prune and delete never remove unattributable unknown namespaces without an explicit separate gate
- `2026-06-18-storage-lifecycle-W04-P06-S37` - Add an adversarial test suite covering out-of-scope deletion, traversal and symlink payloads, unknown-namespace, busy-root, and json-without-confirmation
- `2026-06-18-storage-lifecycle-W05-P07-S38` - Research and select the most capable C-backed Python tooling for ultrafast bulk vector and payload movement and record a reference document
- `2026-06-18-storage-lifecycle-W05-P08-S39` - Implement a service-domain migrate that relocates and converts a root index between local and server backends using the selected tooling
- `2026-06-18-storage-lifecycle-W05-P08-S42` - Add a storage migrate CLI command with dry-run, confirmation, and json
- `2026-06-18-storage-lifecycle-W05-P08-S45` - Add a real-backend migrate round-trip test between local and server with an integrity check

### plan

- `2026-06-18-storage-lifecycle-plan` - `storage-lifecycle` plan

### reference

- `2026-06-18-storage-lifecycle-reference` - `storage-lifecycle` reference: `migrate fast-tooling spike`

### research

- `2026-06-18-storage-lifecycle-research` - `storage-lifecycle` research: `service storage lifecycle management`

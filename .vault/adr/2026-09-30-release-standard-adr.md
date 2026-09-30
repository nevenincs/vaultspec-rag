---
tags:
  - '#adr'
  - '#release-standard'
date: '2026-09-30'
modified: '2026-09-30'
body_schema: 'body-v2'
body_hash: 'sha256:2ba049af082084949e346620c234a84ee1f03b1ee865bc80dd2a4ae97885e22e'
related:
  - '[[2026-09-30-release-standard-reference]]'
---

# `release-standard` adr: `vaultspec-rag adopts the vaultspec release standard` | (**status:** `accepted`)

## Problem Statement

RAG published its GitHub Release before the artifacts that justify it existed,
and then walked that release back. release-please created a full release, the
cut immediately marked it a prerelease so it could not answer as `latest`, the
binary lane demoted an incomplete one and promoted a repaired one, and PyPI
followed that promotion. Every lane therefore edited the state of a live
release, and everything that advertises a release - the Scoop and Homebrew
pointers, the acquisition check - ran while the hold was still on. The
maintainer authorized the vaultspec release standard on 2026-09-30, which
settles this order for every product under the account; vaultspec-core's
`2026-09-30-release-standard-adr` leads and this record adopts it for RAG.

## Considerations

- A published release cannot be filled in afterwards once releases are
  immutable, so the release object must not exist publicly before it is
  complete.
- A prerelease hold is a live release with a flag, so it depends on something
  later removing the flag. A recovery path that must run is a recovery path
  that can fail to run.
- A Scoop manifest and a Homebrew formula address assets by release download
  URL, and the acquisition check downloads the way a user does. Neither can see
  or serve an unpublished release.
- PyPI cannot be withdrawn. A GitHub release can be left unpublished.
- The demote-and-promote machinery was written because a release was already
  live; it has no domain left once nothing is live until it is complete. See
  `2026-09-11-binary-release-bundles-adr` for the completeness contract it
  enforced.

## Considered options

- **Create the release as a draft and publish it last - chosen.** A draft is
  invisible to `latest` by construction, so completeness is enforced by not
  publishing rather than by editing a live release.
- **Keep the prerelease hold and the promotion - rejected.** It works only
  while every promotion runs; the hold is visible, and a lane that never runs
  leaves a release held forever or, worse, a partial one promoted.
- **Publish immediately and rely on the verifier to demote - rejected.** This
  is the state that shipped an empty release as `latest`: the guard lived in a
  workflow that was never dispatched, so it could not fire.
- **Publish the release before PyPI - rejected.** Both acts are one-way, and a
  release published first advertises a version the index may not carry.

## Constraints

- release-please creates the release unpublished and forces its tag. A draft
  creates no git tag of its own, and every lane builds from the tag.
- No lane edits a release's prerelease flag to hold, demote, or promote it. The
  flag is set once, at publication, for a tag naming a prerelease.
- Exactly one step publishes the release, as the last act of the chain, after
  the index upload and in a job that holds no trusted-publishing token.
- The completeness gate judges the draft and edits nothing. An incomplete set
  fails and the release stays a draft.
- PyPI is dispatched only by the gate that found the draft complete, and only
  on its success.
- Nothing that advertises a release runs before publication: the channel
  pointers and the acquisition check are dispatched afterwards, and the channel
  lane refuses a draft rather than trusting its caller.
- The channel deploy key never sits in a job holding `id-token: write`; that
  grant is not scoped to one audience.
- No lane starts on a pushed tag or on a release event. A release event is
  inert for a release the automatic token creates, and a tag push races the
  dispatch the cut already makes.

## Implementation

We will create the GitHub Release as a draft and publish it once, at the end of
the chain. The cut forces the tag, proves it points at the commit the gate
proved, and dispatches the publication lane's release stage, which attaches the
wheel, the source distribution, and the merged checksum manifest to that draft.
The binary lane attaches every declared target archive to the same draft; its
release-proven gate re-derives the expected targets, verifies the digests, and
on success - and only on success - dispatches the package-index stage. That
stage uploads the release's own checksum-verified packages to the index, and a
separate job without a trusted-publishing token then takes the release out of
draft, marking it a prerelease when the tag names one. That job dispatches the
channel-pointer lane and the acquisition check, both of which need public
download URLs.

The Scoop and Homebrew generation moves out of the binary lane into its own
dispatch-only lane that reads the checksum manifest back from the published
release, refuses a draft, and holds the channel deploy key alone. The
acquisition check keeps its weekly schedule and is otherwise dispatched after
publication. Whether the package-index stage should also re-derive the target
completeness rather than trust the gate that dispatched it is an implementation
hypothesis, not a commitment.

## Rationale

The draft removes a state machine instead of repairing it. Under the hold, an
incomplete release existed publicly and depended on a later run to demote it,
and a repaired one depended on another to promote it; both failures are silent,
and RAG has shipped an empty release as `latest` for exactly that reason. A
draft makes the same guarantee structurally: a release that exists is a release
that finished. It also resolves the ordering the hold could not, because a lane
that advertises a release now runs after the release is real rather than while
it is hidden, and the one irreversible act - the index upload - is the last
thing to happen while the safe state is still recoverable.

## Consequences

A failed release advertises nothing, and every repair is a re-dispatch of the
failed lane for the same tag. A release listed on the releases page is one the
whole chain accepted. Drafts are invisible to the releases list by default, so
an operator inspecting a stalled release reads it by tag. The channel pointers
and the acquisition check now lag publication by one dispatch, and a failure in
either does not retract the release. A published release can no longer be
repaired by re-running a lane: publication is last, so a broken published
release means fixing forward with a new version. A future move to immutable
releases requires no further change, which is the condition this record was
written against.

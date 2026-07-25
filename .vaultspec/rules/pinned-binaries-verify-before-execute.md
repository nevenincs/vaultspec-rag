---
name: pinned-binaries-verify-before-execute
---

# Pinned binaries verify before execute

## Rule

- Verify every provisioned native binary against a committed SHA256 pin before
  extraction, and again before execution.
- Never extract or run an unverified artifact.
- Take the digest from a reviewed code constant, never from live release
  metadata.
- Download over HTTPS with a pinned host, and re-check the scheme across
  redirects.
- Discard archive-embedded paths on extraction.

## Why

- Download-then-execute is the load-bearing security boundary.
- A digest read from the same source as the artifact proves nothing.
- Archive-embedded paths enable traversal outside the destination.

## How

- Good: hash the archive and compare to the constant before extracting; flatten
  members by basename; re-hash the extracted binary immediately before spawning.
- Good: resolve an operator-supplied binary through the same supervised path;
  treat a mismatch as a hard failure and delete the partial artifact.
- Bad: extracting before verifying.
- Bad: an extract-all honouring archive-embedded paths.

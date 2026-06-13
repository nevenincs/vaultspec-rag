---
name: pinned-binaries-verify-before-execute
---

# Pinned binaries verify before execute

## Rule

Any native binary the project provisions must be SHA256-verified against a committed
pin before extraction, and re-verified before execution; never extract or run an
unverified or operator-untrusted artifact.

## Why

The `2026-06-12-qdrant-server-provisioning-adr` introduced first-use provisioning of
the Qdrant server binary, and its code review made download-then-execute the load-
bearing security boundary: a tampered archive or a corrupted managed binary must be
refused before it can run. The pinned digests live as reviewed code constants (not
trusted live from the release metadata), the download is HTTPS host-pinned with the
scheme re-checked across redirects, and extraction discards archive-embedded paths
so a malicious member cannot escape the destination.

## How

- Good: download host-pinned over HTTPS, hash the archive and compare to the
  committed constant before extracting, flatten the member by basename into the
  managed dir, then re-hash the extracted binary against its manifest digest
  immediately before spawning it.
- Good: an operator-supplied binary (air-gapped escape hatch) bypasses the download
  but is still resolved through the same supervised path; a checksum mismatch is a
  hard failure that deletes the partial artifact.
- Bad: extracting an archive before verifying its digest, trusting the digest
  embedded in live release metadata instead of a committed pin, or calling
  `extractall` (which honours archive-embedded paths and enables traversal).

---
tags:
  - '#research'
  - '#qdrant-provisioning-trust'
date: '2026-10-05'
modified: '2026-10-05'
body_schema: 'body-v2'
body_hash: 'sha256:66732cc39b4935d64cca3d2059401589b306bc510be216b9e236f72ae45f1309'
related:
  - "[[2026-10-05-qdrant-provisioning-trust-adr]]"
  - "[[2026-06-12-qdrant-server-provisioning-research]]"
---

# `qdrant-provisioning-trust` research: `official qdrant release channels and their dependability as an automatic download source`

## Findings

The question is whether GitHub Releases is the official, dependable source for an automatic first-run download of the Qdrant server, and what override shape mirrors need. GitHub Releases on `qdrant/qdrant` is the only first-party channel that yields a standalone native executable on Windows, macOS, and Linux. It is not immutable and carries no checksum files, signatures, or attestations, so a committed SHA256 is the only integrity control. The Linux x64 gnu build needs glibc 2.38 or newer at v1.19.0. All observations were made on 2026-10-05.

Not investigated: macOS notarization, x64 emulation on Windows ARM64, gnu versus musl performance, GitHub behaviour when it throttles asset downloads, live Artifactory, Nexus, or GHES instances, and whether the model hub client verifies hashes.

### Official channels

- GitHub Releases is first-party and the only cross-platform native source. The release workflow builds on `release: published` (https://raw.githubusercontent.com/qdrant/qdrant/v1.19.0/.github/workflows/release-artifacts.yml lines 5-7) and `github-actions[bot]` uploaded every asset on the 40 releases checked (https://api.github.com/repos/qdrant/qdrant/releases?per_page=40). Each archive holds one `qdrant` or `qdrant.exe` member.
- The `.deb` is first-party, amd64 and Linux only, and is built from the x86_64 musl target (same workflow, lines 47-61).
- The AppImage is first-party, x86_64 only, and bundles the web UI (lines 109-167).
- Container images are first-party, cover linux/amd64 and linux/arm64, and are not a native child process on Windows or macOS (https://raw.githubusercontent.com/qdrant/qdrant/v1.19.0/.github/workflows/docker-image.yml lines 47-61).
- The installation page lists the cloud service, Kubernetes, Docker, and building from source, and names no download page, CDN, or package manager (https://qdrant.tech/documentation/installation/).
- No package-manager channel exists: the crates.io `qdrant` crate is a placeholder (https://crates.io/api/v1/crates/qdrant), and the Homebrew formula and winget manifest lookups return 404 (https://formulae.brew.sh/api/formula/qdrant.json, https://api.github.com/repos/microsoft/winget-pkgs/contents/manifests/q/Qdrant).

### Per-platform artifact

- Windows x64 has `qdrant-x86_64-pc-windows-msvc.zip`; the executable carries no Authenticode signature.
- Windows ARM64 has no asset: the Windows job builds the host triple only (release workflow lines 88-107).
- macOS has arm64 and x64 tarballs.
- Linux x64 has gnu and musl builds; Linux arm64 has musl only.
- Upstream gives no gnu versus musl guidance; neither the installation page nor the README mentions either.
- The gnu build is dynamically linked and its glibc floor moves with the build runner: the highest symbol version is GLIBC_2.38 at v1.19.0 and was GLIBC_2.34 at v1.12.4 (ELF inspection of the two release assets).
- Both musl builds are static with no interpreter. All three Linux builds use jemalloc (https://raw.githubusercontent.com/qdrant/qdrant/v1.19.0/Cargo.toml line 159), so the musl allocator is not in play.
- The resolver sends Linux x64 to gnu at `src/vaultspec_rag/qdrant_runtime/_resolve.py:186`. On a host with glibc below 2.38, or a musl distribution, the verified install succeeds and the spawn then fails. The x64 musl digest is already pinned at `src/vaultspec_rag/qdrant_runtime/_constants.py:109`. Which distribution releases fall below 2.38 was not verified.

### Dependability of GitHub Releases

- Releases are not immutable: the `immutable` field is false on all 40 releases from v1.11.0 to v1.19.1.
- Assets can be replaced in place: uploads run after publication with overwrite enabled (https://raw.githubusercontent.com/taiki-e/upload-rust-binary-action/v1.30.2/main.sh line 637; release workflow lines 60 and 166). A workflow re-run would replace a same-name asset and fail a committed pin until it is re-derived.
- Assets arrive late and sometimes not at all: v1.19.0 assets appeared 22 to 34 minutes after publication, v1.15.3 musl and deb assets 23 hours later, and v1.15.0 has no musl or deb assets.
- Names are stable: the six archive names are identical from v1.8.0 to v1.19.1.
- No checksums, signatures, or provenance are published for the binaries. The attestation endpoint returns 404 for the gnu and Windows digests (https://api.github.com/repos/qdrant/qdrant/attestations/sha256:e4405091f67d02f96fb941695ef8a6974e677632507ff7b04a3fcbb332ad9c19). The release API `digest` field exists from v1.15.0.
- The download path is two hosts: `github.com` redirects to `release-assets.githubusercontent.com`, which serves a short-lived signed URL. `api.github.com` is not on the path. The platform's published host list also names `objects.githubusercontent.com` and `github-releases.githubusercontent.com` (https://api.github.com/meta).
- Rate limits for asset downloads are undocumented; the documented unauthenticated limit applies to the REST API (https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api). The downloader at `src/vaultspec_rag/qdrant_runtime/_provision.py:220` has no retry.

### Mirror and override shape

- Common generic mirrors preserve the upstream path suffix, so `{base}/v{version}/{asset}` works when the base accepts any host, port, and path prefix (third-party description: https://sam.gleske.net/blog/engineering/2023/10/06/nexus-proxy-github-releases.html). Version-control-style remotes use a different layout and do not fit (https://docs.jfrog.com/artifactory/docs/vcs-repositories).
- A base override alone fails today because the initial host is checked against the same set as redirect targets at `src/vaultspec_rag/qdrant_runtime/_provision.py:241`.
- Two facts argue for a configurable host set: a mirror may redirect to its own storage host, and the upstream platform has already moved asset downloads between hosts once.
- Mirrors may also need credentials, a private certificate authority, and proxy support; none was tested.

### Model hub analog

- The hub endpoint defaults to `https://huggingface.co` and is replaced by `HF_ENDPOINT`, read when the client library is imported (https://raw.githubusercontent.com/huggingface/huggingface_hub/main/src/huggingface_hub/constants.py lines 67-70). The override swaps the host and keeps the path, the same shape as a release base URL.
- A hub revision can be a commit hash, which identifies content. The project pins a revision only for the sparse model (`src/vaultspec_rag/_sparse_profile.py:4`). A release tag plus asset name does not identify content, so the SHA256 pin plays that role for the binary.
- No project source references `HF_ENDPOINT`; it passes through the environment.

### Options the evidence frames

- Source: keep GitHub Releases as the sole default, or add a project-controlled secondary source, which removes the replacement and late-asset exposure and reopens redistribution obligations.
- Linux x64 asset: keep gnu and accept a moving glibc floor; switch to musl, which is static, already pinned, and what the upstream package ships, with unmeasured performance; or probe glibc and choose, at the cost of two paths. The evidence favours musl.
- Windows ARM64: report unsupported with the operator-binary route, or run the x64 build under emulation, which is untested.
- Override: one base-URL setting with the host set derived from it, a separately configurable host set, or no host pin when overridden.
- Replacement risk: fail closed and re-derive the pin on mismatch; bounded retry for transient failures either way.

## Sources

- https://api.github.com/repos/qdrant/qdrant/releases?per_page=40
- https://api.github.com/repos/qdrant/qdrant/attestations/sha256:e4405091f67d02f96fb941695ef8a6974e677632507ff7b04a3fcbb332ad9c19
- https://api.github.com/meta
- https://raw.githubusercontent.com/qdrant/qdrant/v1.19.0/.github/workflows/release-artifacts.yml
- https://raw.githubusercontent.com/qdrant/qdrant/v1.19.0/.github/workflows/docker-image.yml
- https://raw.githubusercontent.com/qdrant/qdrant/v1.19.0/Cargo.toml
- https://raw.githubusercontent.com/taiki-e/upload-rust-binary-action/v1.30.2/main.sh
- https://github.com/qdrant/qdrant/releases/download/v1.19.0/qdrant-x86_64-unknown-linux-gnu.tar.gz
- https://github.com/qdrant/qdrant/releases/download/v1.19.0/qdrant-x86_64-unknown-linux-musl.tar.gz
- https://github.com/qdrant/qdrant/releases/download/v1.12.4/qdrant-x86_64-unknown-linux-gnu.tar.gz
- https://qdrant.tech/documentation/installation/
- https://crates.io/api/v1/crates/qdrant
- https://formulae.brew.sh/api/formula/qdrant.json
- https://api.github.com/repos/microsoft/winget-pkgs/contents/manifests/q/Qdrant
- https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api
- https://docs.jfrog.com/artifactory/docs/vcs-repositories
- https://sam.gleske.net/blog/engineering/2023/10/06/nexus-proxy-github-releases.html (third-party)
- https://raw.githubusercontent.com/huggingface/huggingface_hub/main/src/huggingface_hub/constants.py
- `src/vaultspec_rag/qdrant_runtime/_resolve.py:186`
- `src/vaultspec_rag/qdrant_runtime/_constants.py:109`
- `src/vaultspec_rag/qdrant_runtime/_provision.py:220`
- `src/vaultspec_rag/qdrant_runtime/_provision.py:241`
- `src/vaultspec_rag/_sparse_profile.py:4`
- Unverified general knowledge: which Linux distribution releases ship a glibc below 2.38.

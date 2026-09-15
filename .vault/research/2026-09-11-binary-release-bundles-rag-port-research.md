---
tags:
  - '#research'
  - '#binary-release-bundles'
date: '2026-09-11'
modified: '2026-09-11'
body_schema: 'body-v2'
body_hash: 'sha256:dff0b8f378272588f34599a284c37a9315a84c55463666c9e3ef1ba447ceb4e0'
related: []
---

# `binary-release-bundles` research: `RAG binary release bundle port`

RAG needs one public boundary for standalone downloads and package channels. Reading Core's accepted bundle contract and mapping it to RAG shows that target archives with stable inner commands are the leading shape, but RAG must carry its GPU and first-launch network requirements, its Windows plus two Linux targets, and its split `publish.yml` and `binaries.yml` release paths. The ADR must settle the exact archive members, descriptive metadata, complete-target gate, and coordination with Python distribution publication.

## Findings

### RAG currently exposes raw target-qualified executables

The builder produces `vaultspec-rag` and `vaultspec-search-mcp`, names each output with its Rust target, stamps the Windows icon, checks the Linux platform floor, and writes an individual checksum sidecar. `tools/binaries/build_pyapp.py:66-203` and `tools/binaries/build_pyapp.py:316-409` establish that finalization boundary. The binary workflow uploads each target directory and its release job aggregates sidecars before uploading the raw files in `.github/workflows/binaries.yml:350-499`. Direct downloads therefore expose matrix names rather than stable extracted command names, and there is no archive-local description of the shipped contents.

### RAG's binary has a different runtime contract from Core's offline bundle

The two RAG executables install the published distribution with both `gpu` and `mcp` extras, and `tools/binaries/torch_channel.py:1-130` supplies the target-specific accelerated torch wheel because the default bootstrap source is not the project's resolved CUDA channel. The package metadata confirms the separate optional extras and the `3.13` to `<3.15` interpreter range in `pyproject.toml:1-76`. A bundle README and manifest must describe first-launch PyPI/network access, NVIDIA CUDA requirements, the torch pin, and the absence of macOS support; Core's wording that every dependency is already offline would be false for RAG.

### Product and channel code repeats raw asset identity at the public edge

`tools/packaging/products.py:18-152` owns the target sets, executable list, tag scheme, and RAG support exclusion for Darwin, but `Product.asset_name` still represents a public release filename. Scoop maps two raw Windows assets in `tools/packaging/scoop.py:34-75`; Homebrew maps one raw asset per executable and renames target-suffixed files in `tools/packaging/homebrew.py:39-245`; and `tools/packaging/generate.py:40-156` considers a target available only when every raw executable has a digest. `tools/packaging/validate.py:70-200` derives buildable targets from `binaries.yml` but validates pointers against raw executable names. The Core reference centralizes private staging names, stable inner names, archive suffixes, and one bundle name in the product model; the same boundary removes RAG's duplicate naming assumptions.

### The two release workflows can publish incomplete checksum views

`publish.yml` publishes the wheel and sdist and merges its `SHA256SUMS` with any existing release copy in `.github/workflows/publish.yml:132-200`. `binaries.yml` performs an analogous merge for binary sidecars in `.github/workflows/binaries.yml:444-499`. Since both workflows attach to the same GitHub Release independently, each must continue merging rather than replacing the aggregate, and the bundle change must ensure every archive and its final checksum enter that shared view. The current asset guard in `.github/workflows/binaries.yml:599-729` checks for target strings after the release job; the ADR must decide whether completeness means every declared matrix target and whether a missing target demotes `latest`.

### Finalized files are the correct metadata and checksum inputs

The Core evidence set establishes that descriptive metadata must be generated after executable finalization and that an archive must not contain its own enclosing archive digest. RAG already places icon stamping and platform-floor checking before `write_checksum` in `tools/binaries/build_pyapp.py:341-409`; the bundle layer should preserve that order, hash the stable archive members in `manifest.json`, and hash completed top-level archives in `SHA256SUMS`. The manifest can record product, version, release tag, target, archive format, member roles, sizes, hashes, source revision, embedded Python series, PyApp version, and the applicable glibc floor without inventing a separate archive-hash field.

### Windows branding has an existing owner but no authored version resource

`tools/binaries/windows_icon.py:1-263` owns the standard-library Win32 icon replacement and exact verification path, and `tools/binaries/tests/test_windows_icon.py:1-100` proves the real-PE path where available. The current builder calls `stamp_icon` before hashing but does not author PE file or product version fields. The Core implementation adds version-resource stamping from product and executable metadata while retaining icon verification; RAG should evaluate that same metadata seam rather than put branding logic in the bundle builder. The RAG product author and name are available in `pyproject.toml:1-45`, but exact display and copyright strings remain an ADR implementation detail.

### Target archives are better aligned than raw files or one universal archive

Keeping raw files minimizes workflow changes but preserves target-qualified direct-download names, duplicated channel inference, and no archive-local usage contract. Publishing raw files plus archives creates two public contracts and two validation paths. One universal archive hides the target identity that the RAG matrix and CUDA wheel mapping require. The Core research and accepted ADR therefore favor one versioned archive per target, using ZIP for Windows and TAR.GZ for Unix, with stable inner executable names and generated metadata. RAG's supported set remains the matrix's Windows x86_64, Linux x86_64, and Linux aarch64 entries; no macOS archive should be added merely because Homebrew can name one.

### Remaining questions are narrow and implementation-relevant

The source evidence does not settle whether RAG's public archive should carry only `LICENSE`, `README.txt`, `manifest.json`, and the two executables, or also a product-specific usage document; whether the complete-target gate must block every stable release while Linux ARM64 remains operationally fragile; or whether legacy raw URLs receive a compatibility window. It also does not provide a separately pinned CPython patch release for RAG, so the port must report the `PYTHON_VERSION` series and `PYAPP_VERSION` that exist in RAG rather than invent a Core-only runtime field. These are the choices for the RAG ADR, not decisions to hide in this research.

## Sources

- Core research: `Y:/code/vaultspec-core-worktrees/artefacts/.vault/research/2026-09-11-binary-release-bundles-bundle-contract-research.md`
- Core current-pipeline reference: `Y:/code/vaultspec-core-worktrees/artefacts/.vault/reference/2026-09-11-binary-release-bundles-current-pipeline-reference.md`
- Core accepted decision: `Y:/code/vaultspec-core-worktrees/artefacts/.vault/adr/2026-09-11-binary-release-bundles-adr.md`
- `tools/binaries/build_pyapp.py:66-203`
- `tools/binaries/build_pyapp.py:316-409`
- `tools/binaries/torch_channel.py:1-130`
- `tools/binaries/windows_icon.py:1-263`
- `tools/binaries/tests/test_windows_icon.py:1-100`
- `tools/packaging/products.py:18-152`
- `tools/packaging/scoop.py:34-75`
- `tools/packaging/homebrew.py:39-245`
- `tools/packaging/generate.py:40-156`
- `tools/packaging/validate.py:70-200`
- `.github/workflows/binaries.yml:350-499`
- `.github/workflows/binaries.yml:599-729`
- `.github/workflows/publish.yml:132-200`
- `pyproject.toml:1-76`

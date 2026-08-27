# Scoop bucket

This directory makes the repository its own Scoop bucket. Scoop resolves app
manifests from a `bucket/` subdirectory when one is present, so no separate bucket
repository exists or needs to be created. The same layout is repeated in every
product under this account, which is what keeps the count of distribution
repositories at zero per product.

Once the first binaries release has published, install with:

```powershell
scoop bucket add vaultspec-rag https://github.com/nevenincs/vaultspec-rag
scoop install vaultspec-rag
```

## No manifest is committed yet

`vaultspec-rag.json` is generated from the release cohort and pushed here by
`.github/workflows/binaries.yml` at release time. It is **absent until the first
binaries release publishes**, and that absence is deliberate: a manifest names a
version and pins a SHA-256, so a placeholder is a claim a user can act on and fail
against.

vaultspec-core learned this the expensive way. Its bucket carried a committed
skeleton whose hashes were never filled, the release job's digest lookup silently
found nothing, and `vaultspec-core-v0.1.60` shipped a manifest with the right URLs
beside `"hash": ["", ""]` out of a green run. The generator in `tools/packaging`
now refuses every step of that path - and this bucket stays empty until there is a
real release to point at.

## GPU caveat

The Scoop binaries bootstrap a **CPU** build of torch on first launch. PyApp
resolves the pinned distribution from default PyPI, so the `pytorch-cu130` index
this project configures for development is not consulted, and baking a CUDA index
into the binary would be wrong anyway: CUDA availability is a property of the
user's machine, not of the Rust target the binary was built for.

For GPU acceleration, install with uv instead:

```powershell
uv tool install vaultspec-rag
```

The generated manifest carries this caveat in its `notes`, so it reaches whoever
runs `scoop install` rather than living only here.

## Maintenance

The manifest is generated, never hand-authored. Structural changes belong in
`tools/packaging/scoop.py`. The Homebrew half of the same release lives in
`../Formula/`, generated from the same aggregate in the same step so the two
channels cannot disagree about which release is current.

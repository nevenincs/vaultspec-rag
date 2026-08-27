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

## GPU requirement

vaultspec-rag is CUDA-only - `embeddings.py`, `search/_searcher.py` and
`server/_lifespan.py` each raise when `torch.cuda.is_available()` is false. The Scoop
binaries therefore bootstrap the **accelerated** torch build, pinned from `uv.lock` by
`tools/binaries/torch_channel.py`, not whatever default PyPI resolves.

That pin is the whole point. PyPI's Windows torch wheel declares no CUDA dependency at
all, and `tool.uv.sources` does not survive into an install of the published wheel, so
without it a Scoop install would place a binary whose service refuses to start. First
launch downloads roughly 1.8 GB.

## Maintenance

The manifest is generated, never hand-authored. Structural changes belong in
`tools/packaging/scoop.py`. The Homebrew half of the same release lives in
`../Formula/`, generated from the same aggregate in the same step so the two
channels cannot disagree about which release is current.

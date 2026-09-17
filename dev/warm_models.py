"""Download every model the configured stack loads into the Hugging Face cache.

The accelerator tiers read the model cache with the Hub switched off, so a
missing snapshot fails as a runner problem instead of downloading gigabytes
mid-test. This fills that cache first. It needs no device: the product's own
``server warmup`` admits the accelerator before downloading, and on a host
whose card is held by a live service that admission refuses - which says
nothing about whether the weights are present.

The model list is the product's own, so this cannot drift from what the tiers
load. A download is idempotent: files already cached are not fetched again.
The first failed download raises, which fails the run.
"""

from __future__ import annotations

import sys

from dev.exit_codes import OK


def main() -> int:
    """Fetch each configured model repo into the cache."""
    import huggingface_hub

    from vaultspec_rag.config._settings import configured_model_repos

    for label, repo_id in configured_model_repos():
        print(f"warming {label}: {repo_id}", flush=True)
        huggingface_hub.snapshot_download(repo_id)
    return OK


if __name__ == "__main__":
    sys.exit(main())

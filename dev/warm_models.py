"""Download every model the configured stack loads into the Hugging Face cache.

The accelerator tiers read the model cache with the Hub switched off, so a
missing snapshot fails as a runner problem instead of downloading gigabytes
mid-test. This fills that cache first. It needs no device: the product's own
``server warmup`` admits the accelerator before downloading, and on a host
whose card is held by a live service that admission refuses - which says
nothing about whether the weights are present.

The fetch is the product's own model step, so the inventory, the pinned
revisions and the completeness probe cannot drift from what the tiers load.
It is idempotent: repositories already cached are not fetched again. Every
repository is attempted, and the run fails unless the cache ends up holding
all of them.
"""

from __future__ import annotations

import sys

from dev.exit_codes import FAILED, OK


def main() -> int:
    """Fetch each configured model repo into the cache."""
    from vaultspec_rag._sync_vocabulary import ProvisionAction
    from vaultspec_rag.commands._provision import provision_models

    result = provision_models()
    for repo in result.repos:
        print(f"{repo.label}: {repo.repo} {repo.detail}", flush=True)
    if result.action in {ProvisionAction.CREATED, ProvisionAction.UNCHANGED}:
        return OK
    print(f"model cache not filled: {result.detail}", file=sys.stderr, flush=True)
    return FAILED


if __name__ == "__main__":
    sys.exit(main())

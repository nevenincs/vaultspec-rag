"""A Hugging Face model cache whose contents a test decides.

Whether the configured model repositories are cached is a fact about the host:
a developer's workstation holds all of them and a fresh runner holds none. A
test of what a command does when the models are present, or when one is
missing, would otherwise assert whichever of those the machine happened to be -
or download several gigabytes to find out.

This points the hub's cache location at a directory the test owns and seeds it
with snapshots that satisfy the product's own completeness probe. Only the
location is substituted: the probe, the offline switch, the decision to fetch,
and the reporting all run unchanged against real files. The location has to be
set on the hub's module because the hub reads its environment once, when it is
first imported, and a test process has long since imported it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .._sparse_profile import sparse_model_revision
from ..config._settings import configured_model_repos

if TYPE_CHECKING:
    from collections.abc import Collection
    from pathlib import Path

    import pytest

#: The files a snapshot needs for the completeness probe to accept it, for
#: every configured repository alike: a config, a tokenizer, the sparse
#: encoder's remote-code module and tokenizer config, and one weight file.
_SNAPSHOT_FILES = (
    "config.json",
    "tokenizer.json",
    "tokenizer_config.json",
    "modeling_splade.py",
    "model.safetensors",
)

_DEFAULT_REVISION = "0123456789abcdef0123456789abcdef01234567"


def seed_model_cache(
    monkeypatch: pytest.MonkeyPatch,
    cache: Path,
    *,
    missing: Collection[str] = (),
) -> Path:
    """Point the hub at *cache* and seed every configured repo but *missing*.

    Args:
        monkeypatch: Restores the hub's real cache location after the test.
        cache: A directory the test owns; created when absent.
        missing: Repository ids to leave out, so the probe finds them absent.

    Returns:
        The cache directory.
    """
    import huggingface_hub.constants as hub_constants

    cache.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(hub_constants, "HF_HUB_CACHE", str(cache))
    for _label, repo in configured_model_repos():
        if repo in missing:
            continue
        repo_dir = cache / f"models--{repo.replace('/', '--')}"
        revision = sparse_model_revision(repo) or _DEFAULT_REVISION
        snapshot = repo_dir / "snapshots" / revision
        snapshot.mkdir(parents=True)
        (repo_dir / "refs").mkdir()
        (repo_dir / "refs" / "main").write_text(revision, encoding="utf-8")
        for name in _SNAPSHOT_FILES:
            (snapshot / name).write_bytes(b"fixture")
    return cache

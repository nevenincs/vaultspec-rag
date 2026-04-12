"""Reproduce the #68 vault-index RSS leak on a synthetic corpus.

Generates a 135-document synthetic vault with a length distribution
that mirrors the real corpus (mix of short notes and longer docs up
to ``max_embed_chars``), then runs ``VaultIndexer.full_index(clean=True)``
under the ``VAULTSPEC_RAG_MEMORY_PROBE`` instrumentation.

Usage:
    VAULTSPEC_RAG_MEMORY_PROBE=1 uv run python tools/profile_vault_index.py

The script prints a per-phase RSS / CUDA delta report and the overall
peak RSS observed by the background sampler.
"""

from __future__ import annotations

import datetime
import logging
import os
import random
import shutil
import sys
import tempfile
from pathlib import Path

# Force the probe on regardless of invocation style so the script is
# useful when run without the env prefix.
os.environ.setdefault("VAULTSPEC_RAG_MEMORY_PROBE", "1")
# Disable HF on-demand safetensors conversion; we want a clean load.
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-5s %(name)s: %(message)s",
)

# Random corpus shape matches observed vault distribution — a long
# tail of short ADR-style notes plus ~20 large research documents near
# the 8000 char limit.
CORPUS_SIZE = 135
LONG_DOC_COUNT = 25
SHORT_LEN_RANGE = (200, 1200)
LONG_LEN_RANGE = (4000, 8000)


def _write_corpus(target: Path) -> None:
    vault = target / ".vault"
    (vault / "adr").mkdir(parents=True, exist_ok=True)
    (vault / "research").mkdir(parents=True, exist_ok=True)
    rng = random.Random(0xC0FFEE)
    today = datetime.date.today().isoformat()
    words = [
        "lorem",
        "ipsum",
        "dolor",
        "sit",
        "amet",
        "consectetur",
        "adipiscing",
        "elit",
    ]

    def body_of(target_chars: int) -> str:
        parts: list[str] = []
        total = 0
        while total < target_chars:
            line = " ".join(rng.choice(words) for _ in range(rng.randint(6, 14)))
            parts.append(line)
            total += len(line) + 1
        return "\n".join(parts)

    for i in range(CORPUS_SIZE):
        is_long = i < LONG_DOC_COUNT
        target_chars = rng.randint(
            *(LONG_LEN_RANGE if is_long else SHORT_LEN_RANGE),
        )
        subdir = "research" if is_long else "adr"
        path = vault / subdir / f"{today}-synthetic-{i:03d}.md"
        frontmatter = (
            "---\n"
            f'tags: ["#{subdir}", "#synthetic-bench"]\n'
            f"date: {today}\n"
            "---\n\n"
            f"# synthetic document {i}\n\n"
        )
        path.write_text(frontmatter + body_of(target_chars), encoding="utf-8")


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="vaultspec-rag-leak-"))
    data_dir = tmp / "data"
    data_dir.mkdir(parents=True)
    os.environ["VAULTSPEC_RAG_ROOT"] = str(tmp)
    os.environ["VAULTSPEC_RAG_DATA_DIR"] = str(data_dir)
    os.environ["VAULTSPEC_RAG_QDRANT_DIR"] = str(data_dir / "qdrant")

    try:
        _write_corpus(tmp)

        from vaultspec_rag.embeddings import EmbeddingModel
        from vaultspec_rag.indexer import VaultIndexer
        from vaultspec_rag.memory_probe import (
            MemoryProbe,
            current_rss_mb,
            is_enabled,
        )
        from vaultspec_rag.progress import NullProgressReporter
        from vaultspec_rag.store import VaultStore

        if not is_enabled():
            print("memory probe disabled — set VAULTSPEC_RAG_MEMORY_PROBE=1")
            return 2

        # Pre-bind result so the post-with-block prints never raise
        # UnboundLocalError when the inner try fails before
        # full_index returns. F6.5 in the rolling audit.
        result = None

        # The probe is used as a context manager so that any exception
        # (CUDA OOM, model load failure) still tears down the sampler
        # thread cleanly.
        with MemoryProbe(name="repro-vault-index") as probe:
            probe.checkpoint("cold-start")
            print(f"cold rss={current_rss_mb():.0f}MB")

            probe.checkpoint("before-model-load")
            model = EmbeddingModel()
            probe.checkpoint("after-model-load")

            store = VaultStore(tmp, embedding_dim=model.dimension)
            try:
                probe.checkpoint("after-store-init")

                indexer = VaultIndexer(tmp, model=model, store=store)
                probe.checkpoint("before-full-index")

                result = indexer.full_index(
                    clean=True,
                    reporter=NullProgressReporter(),
                )
                probe.checkpoint("after-full-index")
            finally:
                store.close()
            probe.checkpoint("after-store-close")

        print(probe.report())
        if result is not None:
            print(
                f"indexed={result.total} added={result.added} "
                f"duration_ms={result.duration_ms}",
            )
        print(f"PEAK RSS: {probe.peak_rss_mb:.0f}MB")
        return 0 if result is not None else 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())

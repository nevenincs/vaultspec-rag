"""The reviewed identity of every default model: repository, commit and bytes.

A model revision is a name the hub resolves, and the hub this package talks
to can be a mirror an operator configured. So a commit hash alone pins
nothing locally: it says which snapshot was asked for, not what arrived. The
table here is what closes that. For each default model it records the SHA256
of every file the repository holds at the pinned commit, and a snapshot is
used only when it matches file for file - nothing missing, nothing extra,
nothing different. An extra file is refused as firmly as a changed one,
because the loaders pick up files by name: an adapter configuration or a
second tokenizer dropped beside the reviewed ones would be read.

The digests are constants for the same reason the Qdrant binary's are. A
source may be moved by configuration; what it has to serve may not. That is
also why no setting can change the sparse model's commit: its repository
ships the code that builds the model, and a commit the environment could
swap would select code no digest here covers.

A model an operator names instead of a default has no entry and cannot have
one. It is loaded from safetensors weights only and without repository code,
and every surface reports it as unpinned.

How the table was derived, 2026-10-05:

1. The commit of each repository is the ``sha`` field of
   ``https://huggingface.co/api/models/<repo>``.
2. The file list at that commit is
   ``https://huggingface.co/api/models/<repo>/tree/<commit>?recursive=1``,
   which gives each file's size, its git blob id, and for a large file the
   SHA256 the hub stores it under.
3. Each file of a snapshot downloaded from ``https://huggingface.co`` was
   hashed locally and confirmed against that listing: a large file by its
   SHA256, every other file by its git blob id, every file by its size.
   All 35 files agreed, with none missing and none extra.
4. The SHA256 recorded here is the one computed locally in step 3.

To re-derive after moving a pin, repeat those steps for the new commit and
replace the commit and its whole table together.

Standard library only: the cache probe that reads this is imported by
processes that never load a model.
"""

from __future__ import annotations

from types import MappingProxyType
from typing import TYPE_CHECKING, Final

from ._sparse_profile import SPARSE_MODEL_ID, SPARSE_MODEL_REVISION

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = [
    "DENSE_MODEL_ID",
    "DENSE_MODEL_REVISION",
    "RERANKER_MODEL_ID",
    "RERANKER_MODEL_REVISION",
    "committed_manifest",
    "committed_revision",
]

DENSE_MODEL_ID: Final = "Qwen/Qwen3-Embedding-0.6B"
DENSE_MODEL_REVISION: Final = "97b0c614be4d77ee51c0cef4e5f07c00f9eb65b3"
RERANKER_MODEL_ID: Final = "BAAI/bge-reranker-v2-m3"
RERANKER_MODEL_REVISION: Final = "953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e"

_DENSE_FILES: Final[Mapping[str, str]] = MappingProxyType(
    {
        ".gitattributes": (
            "34448b82c17d60fec9b65b1f093c115ddbaadc04beb1b0140b6bfed2e012a930"
        ),
        "1_Pooling/config.json": (
            "37bf193fa101f19101bfad9c31d3eb0f786e247b7b1e5cb7f007d730eed1ddbd"
        ),
        "README.md": (
            "c34d9b7e5a267ad3fdd13227a253686bc90844ff4744a2a6a86c7c905e3d06f3"
        ),
        "config.json": (
            "b5bf1f51fc45be473a54718cef92448d90a1be001bf9b9a44b8c7f10a19feaa9"
        ),
        "config_sentence_transformers.json": (
            "10667c72ddb772627bf1780cb7f86af8e2ae0032b8c243c731172064105c6961"
        ),
        "generation_config.json": (
            "28396d421a2108acce96383f6a7de78008f7f1b17f807958f3c14c51dbfb65fb"
        ),
        "merges.txt": (
            "8831e4f1a044471340f7c0a83d7bd71306a5b867e95fd870f74d0c5308a904d5"
        ),
        "model.safetensors": (
            "0437e45c94563b09e13cb7a64478fc406947a93cb34a7e05870fc8dcd48e23fd"
        ),
        "modules.json": (
            "84e40c8e006c9b1d6c122e02cba9b02458120b5fb0c87b746c41e0207cf642cf"
        ),
        "tokenizer.json": (
            "def76fb086971c7867b829c23a26261e38d9d74e02139253b38aeb9df8b4b50a"
        ),
        "tokenizer_config.json": (
            "253153d0738ceb4c668d2eff957714dd2bea0b56de772a9fdccd96cbf517e6a0"
        ),
        "vocab.json": (
            "ca10d7e9fb3ed18575dd1e277a2579c16d108e32f27439684afa0e10b1440910"
        ),
    }
)

_RERANKER_FILES: Final[Mapping[str, str]] = MappingProxyType(
    {
        ".gitattributes": (
            "34448b82c17d60fec9b65b1f093c115ddbaadc04beb1b0140b6bfed2e012a930"
        ),
        "README.md": (
            "c887aa6dd2598f908bf0582ca7068cc816585c7a1b6a07df305b631ede0cb174"
        ),
        "assets/BEIR-bge-en-v1.5.png": (
            "c1e57bfc0bb87408ac0d5084acce36a26914a2ea19f2f9f3560e71be9d4daef6"
        ),
        "assets/BEIR-e5-mistral.png": (
            "5119f2d1b364f79eaa2954bd5efb4a7e56364ee8748571964d800f85683280c4"
        ),
        "assets/CMTEB-retrieval-bge-zh-v1.5.png": (
            "ce02a58c566da5f733b6928cc968865e4d472c8a276546bfce5d0f4452050ed4"
        ),
        "assets/llama-index.png": (
            "62c4fbdeeb44296da80bdd2f0a7a6b5e44f3492072af84fdf3ed99d01a53e596"
        ),
        "assets/miracl-bge-m3.png": (
            "98f40bf0ba104f3efa52ef76da1434fb776834cdc732e6b29d2550672ea2df1b"
        ),
        "config.json": (
            "13dcd6c31d9fec9d1d8e158702072f62d7fa7d312a64b9fe057bec9a08cfe41a"
        ),
        "model.safetensors": (
            "d9e3e081faff1eefb84019509b2f5558fd74c1a05a2c7db22f74174fcedb5286"
        ),
        "sentencepiece.bpe.model": (
            "cfc8146abe2a0488e9e2a0c56de7952f7c11ab059eca145a0a727afce0db2865"
        ),
        "special_tokens_map.json": (
            "8c785abebea9ae3257b61681b4e6fd8365ceafde980c21970d001e834cf10835"
        ),
        "tokenizer.json": (
            "69564b696052886ed0ac63fa393e928384e0f8caada38c1f4864a9bfbf379c15"
        ),
        "tokenizer_config.json": (
            "7e4c1cc848840aeccdd763458c18dd525eb0f795c992e00ebe9c28554e7db2d4"
        ),
    }
)

_SPARSE_FILES: Final[Mapping[str, str]] = MappingProxyType(
    {
        ".gitattributes": (
            "11ad7efa24975ee4b0c3c3a38ed18737f0658a5f75a0a96787b576a78a023361"
        ),
        "README.md": (
            "88fdf044d5540038ec15183ddf6e8b7cbccab6147c95c9ae0b3654d6d4799b80"
        ),
        "config.json": (
            "309486b1c421726f2b8063dd036b62b78c5322c03f71ae9b5ce6362a195d3705"
        ),
        "config_sentence_transformers.json": (
            "17340a5c3e384d0f06e8e246f5f6c6f0fb36bce9311384ee9a981208521f02fb"
        ),
        "custom_st.py": (
            "7d1d2d76dcff78e73ec6411f71bd205015158b16d7d9ef2d9fb1723c37e01528"
        ),
        "model.safetensors": (
            "8b9116e4234b03d5c5eae21d9036d4f1568205152cc019a113abb73c4bdcccbc"
        ),
        "modeling_splade.py": (
            "256197e8d5e1bb4d869b691173bacf923af25601ff36320876da22755c382a24"
        ),
        "modules.json": (
            "1d4556e509b07e7dcb546b81945a050ea4d0721844ba69e9d15cb3584cad84ea"
        ),
        "tokenizer.json": (
            "30498fe64ed450f9af6ebe45e94f7feb9228d4d41532ec8a22fdb446b3536ced"
        ),
        "tokenizer_config.json": (
            "c687151fe628695cfd10eae03bbb97c98613843cbf89b6d8a9c6050cf8ec28fb"
        ),
    }
)

#: The commit each default repository is pinned to.
_REVISIONS: Final[Mapping[str, str]] = MappingProxyType(
    {
        DENSE_MODEL_ID: DENSE_MODEL_REVISION,
        RERANKER_MODEL_ID: RERANKER_MODEL_REVISION,
        SPARSE_MODEL_ID: SPARSE_MODEL_REVISION,
    }
)

#: The files of each default repository at its pinned commit, keyed by both.
#: Keyed by the commit as well as the repository so that a default repository
#: asked for at any other commit has no manifest, instead of being held to
#: one that describes different files.
_MANIFESTS: Final[Mapping[tuple[str, str], Mapping[str, str]]] = MappingProxyType(
    {
        (DENSE_MODEL_ID, DENSE_MODEL_REVISION): _DENSE_FILES,
        (RERANKER_MODEL_ID, RERANKER_MODEL_REVISION): _RERANKER_FILES,
        (SPARSE_MODEL_ID, SPARSE_MODEL_REVISION): _SPARSE_FILES,
    }
)


def committed_revision(repo: str) -> str | None:
    """Return the commit *repo* is pinned to, or ``None`` for a repo not shipped.

    Args:
        repo: A hub repository id.

    Returns:
        The pinned commit of a default model, or ``None`` when the repository
        is one an operator named and nothing here vouches for it.
    """
    return _REVISIONS.get(repo)


def committed_manifest(repo: str, revision: str | None) -> Mapping[str, str] | None:
    """Return the file digests committed for *repo* at *revision*, if any.

    Args:
        repo: A hub repository id.
        revision: The commit the snapshot is for, or ``None`` when no commit
            is named.

    Returns:
        Each file's path relative to the snapshot, with forward slashes,
        mapped to its lower-case hex SHA256; ``None`` when no table covers
        that repository at that commit.
    """
    if revision is None:
        return None
    return _MANIFESTS.get((repo, revision))

"""Reviewed sparse model identity shared by inference and acquisition."""

SPARSE_MODEL_ID = "Linkup-Platform/linkup-sparseup-embed-v1"
SPARSE_MODEL_REVISION = "08314498d4f6a3a205b930ab9f27001404ea94b8"
SPARSE_VOCAB_SIZE = 50370
SPARSE_DOCUMENT_MAX_LENGTH = 512


def sparse_model_revision(model_id: str) -> str | None:
    """Pin the reviewed default; custom model identities retain their defaults."""
    return SPARSE_MODEL_REVISION if model_id == SPARSE_MODEL_ID else None

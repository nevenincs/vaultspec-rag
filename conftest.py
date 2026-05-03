"""Root conftest for all vaultspec tests.

RAG test constants and fixtures live in
src/vaultspec_rag/tests/conftest.py and src/vaultspec_rag/tests/constants.py.
"""

import os

import pytest

# Markers whose tests require exclusive GPU access
_GPU_MARKERS = frozenset({"integration", "quality", "performance", "robustness"})

# Marker for CLI subprocess tests that load their own GPU models.
# These must NOT co-schedule with _GPU_MARKERS tests — combined VRAM
# exceeds 16 GB on RTX 4080.
_SUBPROCESS_GPU = "subprocess_gpu"


def _load_dotenv_if_available() -> None:
    """Load .env file from project root if python-dotenv is available."""
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:
        pass


_load_dotenv_if_available()


def _has_hf_token() -> bool:
    """Return True when Hugging Face auth is available to test code."""
    if os.environ.get("HF_TOKEN"):
        return True
    try:
        from huggingface_hub import get_token
    except ImportError:
        return False
    return bool(get_token())


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Auto-apply GPU xdist grouping to GPU-bound tests."""
    gpu_group = pytest.mark.xdist_group("gpu")
    for item in items:
        item_markers = {m.name for m in item.iter_markers()}
        if item_markers & _GPU_MARKERS:
            item.add_marker(gpu_group)


def pytest_runtestloop(session: pytest.Session) -> None:
    """Fail fast if Hugging Face auth is missing for selected GPU tests.

    Runs after deselection so only *selected* items are checked.
    This avoids blocking unit-only runs that don't need GPU access.
    """
    needs_token = _GPU_MARKERS | {_SUBPROCESS_GPU}
    for item in session.items:
        item_markers = {m.name for m in item.iter_markers()}
        if item_markers & needs_token:
            if not _has_hf_token():
                pytest.exit(
                    "Hugging Face authentication is required for GPU "
                    "tests (gated model naver/splade-v3). Set HF_TOKEN, "
                    "put it in .env, or run `hf auth login` before running "
                    "tests.",
                    returncode=1,
                )
            break

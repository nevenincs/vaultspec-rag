"""Root conftest for all vaultspec tests.

RAG test constants and fixtures live in
src/vaultspec_rag/tests/conftest.py and src/vaultspec_rag/tests/constants.py.
"""

import pytest

# Markers whose tests require exclusive GPU access
_GPU_MARKERS = frozenset({"integration", "quality", "performance", "robustness"})


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Auto-apply xdist_group("gpu") to GPU-bound tests.

    This is a no-op when pytest-xdist is not installed. If xdist is ever
    added, it ensures all GPU tests run in the same worker process —
    CUDA is not fork-safe and concurrent GPU access must be serialized.
    """
    gpu_group = pytest.mark.xdist_group("gpu")
    for item in items:
        item_markers = {m.name for m in item.iter_markers()}
        if item_markers & _GPU_MARKERS:
            item.add_marker(gpu_group)

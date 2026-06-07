"""Re-export synthetic vault generator for test convenience.

The implementation lives in ``vaultspec_rag.synthetic`` so it can be
imported by production code (e.g. ``cli.py handle_quality``) without
depending on the tests subpackage.
"""

from ..synthetic import (
    CorpusManifest,
    GeneratedDoc,
    build_multi_project_fixture,
    build_synthetic_vault,
)

__all__ = [
    "CorpusManifest",
    "GeneratedDoc",
    "build_multi_project_fixture",
    "build_synthetic_vault",
]

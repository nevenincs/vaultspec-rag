"""Centralized test constants for vaultspec test suite.

This module consolidates all test-only constants that were previously
scattered across multiple conftest.py files.  Import from here instead
of redefining values in individual conftest modules.

NOTE: This module must NOT import from core.config -- test constants
are independent of the production configuration system.
"""

from __future__ import annotations

import pathlib

#: Repository root (src/vaultspec_rag/tests/ -> src/vaultspec_rag/ -> src/ -> repo)
PROJECT_ROOT: pathlib.Path = (
    pathlib.Path(__file__).resolve().parent.parent.parent.parent
)

#: src/vaultspec/ — the library source root
LIB_SRC: pathlib.Path = PROJECT_ROOT / "src" / "vaultspec_rag"

#: CLI entry points are now modules inside the vaultspec package
SCRIPTS: pathlib.Path = PROJECT_ROOT / "src" / "vaultspec_rag"

#: test-project/ fixture directory (git-tracked .vault/ seed corpus)
TEST_PROJECT: pathlib.Path = PROJECT_ROOT / "test-project"

#: test-project/.vault/ documentation vault
TEST_VAULT: pathlib.Path = TEST_PROJECT / ".vault"

GPU_FAST_CORPUS_STEMS: frozenset[str] = frozenset(
    [
        # adr (4)
        "2026-01-10-pipeline-execution-model",
        "2026-01-12-connector-protocol-design",
        "2026-01-15-storage-backend-selection",
        "2026-01-20-scheduler-algorithm-choice",
        # plan (2)
        "2026-01-10-pipeline-engine-phase1-plan",
        "2026-01-20-scheduler-phase1-plan",
        # exec (2)
        "2026-01-11-pipeline-parser-complete",
        "2026-01-22-scheduler-worker-pool-complete",
        # reference (3)
        "2026-01-10-pipeline-engine-reference",
        "2026-01-12-connector-api-reference",
        "2026-01-18-nexus-security-audit",
        # research (2)
        "2026-01-09-dag-execution-research",
        "2026-01-19-scheduling-algorithms-research",
    ],
)

QDRANT_SUFFIX_FAST: str = "-fast"
QDRANT_SUFFIX_FULL: str = "-full"
QDRANT_SUFFIX_UNIT: str = "-fast-unit"

TEST_PORT_BASE: int = 10001
TEST_PORT_A2A_BASE: int = 10020
TEST_PORT_SUBAGENT: int = 10010

TIMEOUT_QUICK: int = 15
TIMEOUT_INTEGRATION: int = 120
TIMEOUT_E2E: int = 180
TIMEOUT_CLAUDE_E2E: int = 60
TIMEOUT_GEMINI_E2E: int = 60
TIMEOUT_MCP_E2E: int = 180
TIMEOUT_FULL_CYCLE: int = 180
TIMEOUT_A2A_E2E: int = 300

DELAY_SHORT: float = 0.2
DELAY_MEDIUM: float = 0.3
DELAY_LONG: float = 1.0

ACP_TIMEOUT_READ: float = 10.0
ACP_TIMEOUT_MESSAGE: float = 30.0

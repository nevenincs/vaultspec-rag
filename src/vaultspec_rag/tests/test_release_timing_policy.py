"""Regression guards for release-blocking correctness-test wait policy."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit]

_TEST_ROOT = Path(__file__).parent


def _function(tree: ast.Module, name: str) -> ast.FunctionDef:
    match = next(
        (
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == name
        ),
        None,
    )
    assert match is not None, f"expected function {name!r}"
    return match


def test_uvicorn_release_probe_uses_the_shared_hard_cutoff() -> None:
    """Readiness waits on state and has no machine-tuned local deadline.

    Mutation: replace ``CHILD_PROCESS_TIMEOUT_SECONDS`` in the readiness
    deadline with ``10.0``. The exact name assertion below then fails.
    """
    path = _TEST_ROOT / "integration" / "test_service_logs.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    wait = _function(tree, "_wait_for_uvicorn_access_probe")
    deadline_values = [
        node.value
        for node in ast.walk(wait)
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "deadline"
            for target in node.targets
        )
    ]

    assert len(deadline_values) == 1
    assert any(
        isinstance(node, ast.Name) and node.id == "CHILD_PROCESS_TIMEOUT_SECONDS"
        for node in ast.walk(deadline_values[0])
    ), "Uvicorn readiness must use the shared spawned-child hard cutoff"


def test_release_qdrant_clients_override_the_short_transport_default() -> None:
    """Real-server clients receive the shared hard cutoff explicitly.

    Mutation: remove either shared-cutoff ``timeout`` keyword. The guarded
    call count then falls below the two real-server clients.
    """
    path = _TEST_ROOT / "integration" / "test_service_storage_migration.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    real_server_clients = []
    for call in (node for node in ast.walk(tree) if isinstance(node, ast.Call)):
        if not isinstance(call.func, ast.Name) or call.func.id != "QdrantClient":
            continue
        url = next((item.value for item in call.keywords if item.arg == "url"), None)
        if not (
            isinstance(url, ast.Attribute)
            and isinstance(url.value, ast.Name)
            and url.value.id == "migration_qdrant_server"
        ):
            continue
        timeout = next(
            (item.value for item in call.keywords if item.arg == "timeout"), None
        )
        real_server_clients.append(timeout)

    assert len(real_server_clients) == 2
    assert all(
        isinstance(timeout, ast.Call)
        and isinstance(timeout.func, ast.Name)
        and timeout.func.id == "int"
        and len(timeout.args) == 1
        and isinstance(timeout.args[0], ast.Name)
        and timeout.args[0].id == "CHILD_PROCESS_TIMEOUT_SECONDS"
        for timeout in real_server_clients
    ), "release Qdrant clients must not inherit the five-second HTTP default"


def test_borrower_resume_uses_the_model_operation_hard_cutoff() -> None:
    """A slow model rebuild must not inherit the short admin-call deadline.

    Mutation: remove the explicit timeout keyword from the resume lifecycle
    call. The exact expression assertion below then fails.
    """
    path = _TEST_ROOT.parent / "cli" / "_gpu_lease.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    resume = _function(tree, "_resume_is_acknowledged")
    lifecycle_calls = [
        node
        for node in ast.walk(resume)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_try_borrower_lifecycle_call"
    ]

    assert len(lifecycle_calls) == 1
    timeout = next(
        (item.value for item in lifecycle_calls[0].keywords if item.arg == "timeout"),
        None,
    )
    assert (
        isinstance(timeout, ast.Call)
        and isinstance(timeout.func, ast.Name)
        and timeout.func.id == "get_search_timeout"
        and len(timeout.args) == 1
        and isinstance(timeout.args[0], ast.Constant)
        and timeout.args[0].value is None
    ), "borrower resume must use the model-operation hard cutoff"

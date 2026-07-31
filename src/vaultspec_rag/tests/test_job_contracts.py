"""Cohesive unit coverage for job-management behavior."""

from __future__ import annotations

import ast
import inspect
import subprocess
import sys
import textwrap
from pathlib import Path
from typing import TYPE_CHECKING, cast

import pytest

from .. import job_models
from .. import jobs as jobs_module
from ..job_manager import state as state_module
from ..job_manager._execution import logger as execution_logger
from ..job_manager.manager import JobManager
from ..service import ServiceRegistry
from ..service_quiesce import ServiceQuiesceController

if TYPE_CHECKING:
    from ..embeddings import EmbeddingModel

pytestmark = [pytest.mark.unit]


def test_job_models_are_defined_exactly_once() -> None:
    # These names used to be re-exported through ``jobs`` as a compatibility
    # facade, and this test asserted the forwarding held. The facade is gone:
    # ``job_models`` is the definition site and consumers import from it. What
    # still matters is that no SECOND definition appears - two classes with one
    # name is how an isinstance check starts failing for no visible reason.
    for name in job_models.__all__:
        owner = getattr(job_models, name)
        assert getattr(owner, "__module__", job_models.__name__).endswith(
            ("job_models", "enum", "builtins")
        ), f"{name} is defined outside job_models ({owner!r})"
    assert not set(job_models.__all__) & set(jobs_module.__all__), (
        "jobs must not re-export job_models names; import them from job_models"
    )


def test_job_manager_logs_under_the_jobs_namespace() -> None:
    # The shared logger name is a real contract (operators filter on it) and is
    # independent of how the modules import each other.
    assert execution_logger.name == jobs_module.logger.name == "vaultspec_rag.jobs"


_OWNER_MODULES = (
    "_control.py",
    "_execution.py",
    "_persistence.py",
    "_progress.py",
    "_records.py",
)


def _owner_class(tree: ast.Module) -> ast.ClassDef:
    classes = [node for node in tree.body if isinstance(node, ast.ClassDef)]
    owners = [node for node in classes if node.name.startswith("JobManager")]
    assert len(owners) == 1, "each owner module defines exactly one owner class"
    return owners[0]


def _declared_members(node: ast.ClassDef) -> set[str]:
    declared: set[str] = set()
    for statement in node.body:
        if isinstance(statement, ast.FunctionDef | ast.AsyncFunctionDef):
            declared.add(statement.name)
        elif isinstance(statement, ast.AnnAssign) and isinstance(
            statement.target, ast.Name
        ):
            declared.add(statement.target.id)
    return declared


def _contract_class() -> ast.ClassDef:
    source = Path(state_module.__file__).read_text(encoding="utf-8")
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ClassDef) and node.name == "JobManagerState":
            for base in node.bases:
                if isinstance(base, ast.Name) and base.id == "Protocol":
                    return node
    raise AssertionError("job_manager.state declares no JobManagerState protocol")


def test_shared_owner_surface_is_declared_not_dynamic() -> None:
    # Responsibility for one coordinator is split across several owner classes,
    # so each one reaches state and behaviour a sibling owns. That surface has
    # to be declared member by member on the shared contract. A catch-all
    # ``__getattr__`` there would satisfy every such reference by typing it as
    # ``Any``, which silently retires type checking across the whole package -
    # and no configured rule reports it, so nothing else would catch the
    # regression. Both halves below are load-bearing: the first keeps the
    # escape hatch out, the second keeps the declarations complete.
    contract = _contract_class()
    declared = _declared_members(contract)

    assert "__getattr__" not in declared, (
        "JobManagerState must declare its members explicitly; a __getattr__ "
        "escape hatch types every cross-owner reference as Any"
    )

    package = Path(state_module.__file__).parent
    undeclared: dict[str, set[str]] = {}
    for module_name in _OWNER_MODULES:
        tree = ast.parse((package / module_name).read_text(encoding="utf-8"))
        owner = _owner_class(tree)
        local = _declared_members(owner)
        reached = {
            node.attr
            for node in ast.walk(owner)
            if isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == "self"
        }
        missing = reached - local - declared
        if missing:
            undeclared[module_name] = missing

    assert not undeclared, (
        f"owner modules reach undeclared members on JobManagerState: {undeclared}"
    )


def test_job_manager_rejects_unknown_attributes() -> None:
    manager = JobManager(
        quiesce_controller=ServiceQuiesceController(),
        max_nonterminal=1,
        state_path=None,
    )

    with pytest.raises(AttributeError):
        _ = manager.misspelled_manager_attribute


def test_job_manager_import_does_not_pull_in_jobs() -> None:
    probe = """
import sys

sys.path.insert(0, sys.argv[1])

from vaultspec_rag.job_manager.manager import JobManager  # absolute-import-ok

assert JobManager is not None
assert "vaultspec_rag.jobs" not in sys.modules
"""
    completed = subprocess.run(
        [sys.executable, "-c", probe, str(Path(__file__).parents[2])],
        capture_output=True,
        text=True,
        timeout=30.0,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stderr == ""


# ---------------------------------------------------------------------------
# AST regression guard
# ---------------------------------------------------------------------------


def _parse_jobs_module() -> ast.Module:
    import vaultspec_rag.jobs as jobs_mod

    src = inspect.getsource(jobs_mod)
    return ast.parse(textwrap.dedent(src))


def _parse_job_dispatch_module() -> ast.Module:
    import vaultspec_rag.job_dispatch as dispatch_mod

    src = inspect.getsource(dispatch_mod)
    return ast.parse(textwrap.dedent(src))


class TestIndexDispatchIsExtracted:
    """AST guard for the extracted production indexing dispatch module.

    The load-model-before-lease ordering this class used to check on two
    named runners is now checked package-wide, on all fourteen functions
    that pair the two calls rather than the two that had a test.
    """

    @staticmethod
    def _defined_names(tree: ast.Module) -> set[str]:
        """Return every function name the module defines, sync or async.

        ``ast`` gives the two no common base, so both are named. Filtering
        ``FunctionDef`` alone let an ``async def`` back into the facade
        unseen, and ``jobs`` already defines one.
        """
        return {
            node.name
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
        }

    def test_dispatch_implementations_are_extracted_from_jobs_facade(self) -> None:
        jobs_functions = self._defined_names(_parse_jobs_module())
        dispatch_functions = self._defined_names(_parse_job_dispatch_module())
        assert "_bg_run" not in jobs_functions
        assert {"_run_vault_attempt", "_run_indexing_attempt"} <= dispatch_functions


# ---------------------------------------------------------------------------
# load_model() idempotency — no GPU needed
# ---------------------------------------------------------------------------


class TestLoadModelIdempotency:
    """load_model() is a no-op when _model is already set."""

    def test_second_call_does_not_overwrite_existing_model(self) -> None:
        """Inject a sentinel into _model; second load_model() must leave it."""
        reg = ServiceRegistry()
        sentinel = cast("EmbeddingModel", object())
        # Bypass the real EmbeddingModel construction by injecting directly.
        reg._model = sentinel
        reg.load_model()  # must return without touching _model
        assert reg._model is sentinel, (
            "load_model() must be idempotent: it replaced the existing model"
        )

    def test_model_property_raises_before_load(self) -> None:
        reg = ServiceRegistry()
        with pytest.raises(RuntimeError, match="call load_model\\(\\) first"):
            _ = reg.model

    def test_model_property_succeeds_after_sentinel_inject(self) -> None:
        reg = ServiceRegistry()
        sentinel = cast("EmbeddingModel", object())
        reg._model = sentinel
        assert reg.model is sentinel


# ---------------------------------------------------------------------------
# jobs module basic lifecycle
# ---------------------------------------------------------------------------

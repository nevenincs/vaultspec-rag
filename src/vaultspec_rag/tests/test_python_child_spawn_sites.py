"""Guard: no process is started by this package without being accounted for.

A Python child started on a module, an inline program or a script puts the
directory it was started in, or the script's own, first on its import path.
This package is run from inside project checkouts, so one such child is
enough for a checkout to have its own code run as the operator. Every child
is therefore built by :mod:`vaultspec_rag._python_child`, which adds the
interpreter's safe-path flag, and this module is what stops a new child from
being added any other way.

Three scans of the package source, none of which can be satisfied by leaving
a site out:

* every place that creates a process is listed here by function, with what it
  starts and why that is safe. A site that is not listed fails, and so does a
  listed site that no longer exists, so the list cannot drift into fiction;
* the interpreter's mode switches appear as string constants only in the
  builder and in the launch recogniser. A hand-built interpreter command has
  to spell one of them, so it fails here whatever the interpreter was called;
* the running interpreter is never placed in a command by hand.

The scans read the syntax tree rather than the text, so prose that mentions a
command line does not trip them and a command split across lines does not
slip past.
"""

from __future__ import annotations

import ast
import re
from collections import Counter
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit]

_PACKAGE = Path(__file__).resolve().parents[1]
_BUILDER = "_python_child.py"


class _Starts(Enum):
    """What a process-creating site starts."""

    #: A Python interpreter running this package's code. Its command comes
    #: from the builder, so it runs in safe-path mode.
    PYTHON = "python child, built by the command builder"
    #: A spawn pool worker. Its command is built by the standard library, so
    #: it is opened only through the one constructor that guards its path.
    POOL = "pool worker, opened through the guarded pool constructor"
    #: A program that is not Python: nothing here decides an import path.
    NATIVE = "native program"
    #: Code the project supplies and the operator has consented to run.
    PROJECT = "project-authored command, run on consent"


@dataclass(frozen=True, slots=True)
class _Site:
    starts: _Starts
    calls: dict[str, int]
    why: str


#: Every function in the package that creates a process, keyed by file and
#: qualified name, with each creating call it makes and how often. Adding a
#: process-creating call anywhere changes a count or adds a key, and either
#: fails the scan until the new site is described here.
_SITES: dict[str, _Site] = {
    "_process_probe.py::_windows_image_matches": _Site(
        _Starts.NATIVE,
        {"subprocess.run": 1},
        "tasklist, with a fixed argument list",
    ),
    "cli/_process.py::_spawn_service_request": _Site(
        _Starts.PYTHON,
        {"subprocess.Popen": 1},
        "the resident service, from _service_launch_command",
    ),
    "cli/_process.py::_spawn_windows": _Site(
        _Starts.PYTHON,
        {"subprocess.Popen": 2},
        "the resident service on Windows; the command is its caller's",
    ),
    "commands/_mcp_topology.py::_restore_junction": _Site(
        _Starts.NATIVE,
        {"subprocess.run": 1},
        "powershell.exe, with a fixed command and no profile",
    ),
    "commands/_model_download.py::_run": _Site(
        _Starts.PYTHON,
        {"subprocess.Popen": 1},
        "the model download child, from module_command",
    ),
    "commands/_tool_torch.py::_run_uv": _Site(
        _Starts.NATIVE,
        {"subprocess.run": 1},
        "uv, resolved off PATH; uv chooses how it runs its own interpreter",
    ),
    "commands/_tool_torch.py::_target_mismatch": _Site(
        _Starts.NATIVE,
        {"subprocess.run": 1},
        "uv tool dir, which reads configuration and runs no interpreter",
    ),
    "commands/_uv_sync.py::_run_uv_sync_torch": _Site(
        _Starts.NATIVE,
        {"subprocess.run": 1},
        "uv sync in the target project, on the operator's request",
    ),
    "indexer/_chunk_producer.py::CodeChunkProducer.produce_singles": _Site(
        _Starts.POOL,
        {"multiprocessing.get_context": 1},
        "the spawn context handed to spawn_pool",
    ),
    "indexer/_chunk_producer.py::CodeChunkProducer.run_batch_groups": _Site(
        _Starts.POOL,
        {"multiprocessing.get_context": 1},
        "the spawn context handed to spawn_pool",
    ),
    "indexer/_hook_sandbox.py::default_popen_handle": _Site(
        _Starts.PROJECT,
        {"subprocess.Popen": 1},
        "a preprocess hook: the project's own command, or this package's "
        "entry runner named by file path from script_command",
    ),
    "indexer/_pool_guard.py::spawn_pool": _Site(
        _Starts.POOL,
        {"concurrent.futures.ProcessPoolExecutor": 1},
        "the one pool constructor; holds the workers' import path safe",
    ),
    "indexer/_vault_prep.py::split_documents": _Site(
        _Starts.POOL,
        {"multiprocessing.get_context": 1},
        "the spawn context handed to spawn_pool",
    ),
    "monitor_process.py::MonitorProcess.start": _Site(
        _Starts.NATIVE,
        {"subprocess.Popen": 1},
        "the compiled monitor; it starts its own Python child in safe-path "
        "mode, which the monitor source scan below holds to",
    ),
    "operator_state/_environment_probe.py::probe_interpreter": _Site(
        _Starts.PYTHON,
        {"subprocess.run": 1},
        "the environment probe, from inline_command",
    ),
    "operator_state/_hardware.py::query_hardware": _Site(
        _Starts.NATIVE,
        {"subprocess.run": 1},
        "nvidia-smi, resolved off PATH",
    ),
    "qdrant_runtime/_resolve.py::_reap_on_windows": _Site(
        _Starts.NATIVE,
        {"subprocess.run": 1},
        "taskkill, with a fixed argument list",
    ),
    "qdrant_runtime/_spawn_trust.py::spawn_verified": _Site(
        _Starts.NATIVE,
        {"subprocess.Popen": 2},
        "the qdrant binary, verified against its pinned digest",
    ),
}

#: Functions whose process is a Python child must take their command from the
#: builder. Each names the builder function its command comes from; a site
#: whose command is built by its caller names the caller instead.
_BUILT_BY: dict[str, tuple[str, str]] = {
    "cli/_process.py::_spawn_service_request": (
        "cli/_process.py::_service_launch_command",
        "module_command",
    ),
    "cli/_process.py::_spawn_windows": (
        "cli/_process.py::_service_launch_command",
        "module_command",
    ),
    "commands/_model_download.py::_run": (
        "commands/_model_download.py::_run",
        "module_command",
    ),
    "operator_state/_environment_probe.py::probe_interpreter": (
        "operator_state/_environment_probe.py::probe_interpreter",
        "inline_command",
    ),
    "indexer/_hook_sandbox.py::default_popen_handle": (
        "indexer/_preprocess_runner.py::_build_argv",
        "script_command",
    ),
}

#: Where the interpreter's mode switches may be spelt, and how many times.
#: The builder writes them; the launch recogniser reads them back off another
#: process's command line and starts nothing.
_MODE_SWITCHES = ("-m", "-c")
_MODE_SWITCH_HOMES: dict[str, Counter[str]] = {
    _BUILDER: Counter({"-m": 1, "-c": 1}),
    "_process_probe.py": Counter({"-m": 1, "-c": 1}),
}

_SUBPROCESS_CREATORS = frozenset(
    {"Popen", "run", "call", "check_call", "check_output", "getoutput"}
    | {"getstatusoutput"}
)
_OS_CREATORS = frozenset(
    {"system", "popen", "startfile", "fork", "forkpty", "posix_spawn"}
    | {"posix_spawnp"}
)
_OS_CREATOR_PREFIXES = ("exec", "spawn")
_ASYNCIO_CREATORS = frozenset({"create_subprocess_exec", "create_subprocess_shell"})
_MULTIPROCESSING_CREATORS = frozenset({"Process", "Pool", "get_context"})
_FUTURES_CREATORS = frozenset({"ProcessPoolExecutor"})


def _creates_a_process(module: str, name: str) -> bool:
    if module == "subprocess":
        return name in _SUBPROCESS_CREATORS
    if module == "os":
        return name in _OS_CREATORS or name.startswith(_OS_CREATOR_PREFIXES)
    if module == "asyncio":
        return name in _ASYNCIO_CREATORS
    if module == "multiprocessing":
        return name in _MULTIPROCESSING_CREATORS
    if module in {"concurrent.futures", "concurrent.futures.process"}:
        return name in _FUTURES_CREATORS
    return module in {"_winapi", "pty"}


def _production_files() -> list[Path]:
    return sorted(
        path
        for path in _PACKAGE.rglob("*.py")
        if "tests" not in path.relative_to(_PACKAGE).parts
    )


def _relative(path: Path) -> str:
    return path.relative_to(_PACKAGE).as_posix()


class _Scan(ast.NodeVisitor):
    """Collect what one module says about starting processes."""

    def __init__(self) -> None:
        self.modules: dict[str, str] = {}
        self.names: dict[str, tuple[str, str]] = {}
        self.scope: list[str] = []
        self.creating: Counter[tuple[str, str]] = Counter()
        self.builder_calls: Counter[tuple[str, str]] = Counter()
        self.mode_switches: Counter[str] = Counter()
        self.hand_built: list[str] = []
        self.shells: list[int] = []

    @property
    def _where(self) -> str:
        return ".".join(self.scope) or "<module>"

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            bound = alias.asname or alias.name.split(".")[0]
            self.modules[bound] = alias.name if alias.asname else bound

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        for alias in node.names:
            self.names[alias.asname or alias.name] = (node.module or "", alias.name)

    def _scoped(self, node: ast.AST, name: str) -> None:
        self.scope.append(name)
        self.generic_visit(node)
        self.scope.pop()

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._scoped(node, node.name)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_function(node)

    def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        # Annotations name process types without creating one, so the body and
        # the defaults are walked and the annotations are not.
        self.scope.append(node.name)
        for child in (*node.decorator_list, *node.args.defaults, *node.body):
            self.visit(child)
        for default in node.args.kw_defaults:
            if default is not None:
                self.visit(default)
        self.scope.pop()

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if node.value is not None:
            self.visit(node.value)

    def visit_If(self, node: ast.If) -> None:
        test = node.test
        if isinstance(test, ast.Name) and test.id == "TYPE_CHECKING":
            for child in node.orelse:
                self.visit(child)
            return
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        owner = self._dotted(node.value)
        if owner is not None:
            module = self.modules.get(owner.split(".")[0])
            if module is not None:
                qualified = ".".join([module, *owner.split(".")[1:]])
                if _creates_a_process(qualified, node.attr):
                    self.creating[self._where, f"{qualified}.{node.attr}"] += 1
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> None:
        origin = self.names.get(node.id)
        if origin is None:
            return
        module, name = origin
        if _creates_a_process(module, name):
            self.creating[self._where, f"{module}.{name}"] += 1
        if module.endswith("_python_child"):
            self.builder_calls[self._where, name] += 1

    def visit_Constant(self, node: ast.Constant) -> None:
        if node.value in _MODE_SWITCHES:
            self.mode_switches[str(node.value)] += 1

    def visit_List(self, node: ast.List) -> None:
        self._check_display(node)
        self.generic_visit(node)

    def visit_Tuple(self, node: ast.Tuple) -> None:
        self._check_display(node)
        self.generic_visit(node)

    def visit_BinOp(self, node: ast.BinOp) -> None:
        for operand in (node.left, node.right):
            if self._is_running_interpreter(operand):
                self.hand_built.append(f"{self._where}: line {node.lineno}")
        self.generic_visit(node)

    def visit_keyword(self, node: ast.keyword) -> None:
        value = node.value
        if node.arg == "shell" and not (
            isinstance(value, ast.Constant) and value.value is False
        ):
            self.shells.append(value.lineno)
        self.generic_visit(node)

    def _check_display(self, node: ast.List | ast.Tuple) -> None:
        if not node.elts:
            return
        elements = [
            element.value if isinstance(element, ast.Starred) else element
            for element in node.elts
        ]
        first = elements[0]
        if any(self._is_running_interpreter(element) for element in elements) or (
            _INTERPRETER_NAME.search(self._identifier(first))
        ):
            self.hand_built.append(f"{self._where}: line {node.lineno}")

    def _is_running_interpreter(self, node: ast.AST) -> bool:
        dotted = self._dotted(node)
        return dotted is not None and dotted in _RUNNING_INTERPRETER

    def _identifier(self, node: ast.AST) -> str:
        if (
            isinstance(node, ast.Call)
            and self._dotted(node.func) in {"str", "os.fspath"}
            and len(node.args) == 1
        ):
            # ``str(interpreter)`` is still the interpreter.
            return self._identifier(node.args[0])
        return self._dotted(node) or ""

    @staticmethod
    def _dotted(node: ast.AST) -> str | None:
        parts: list[str] = []
        while isinstance(node, ast.Attribute):
            parts.append(node.attr)
            node = node.value
        if isinstance(node, ast.Name):
            return ".".join([node.id, *reversed(parts)])
        return None


#: The names the running interpreter goes by.
_RUNNING_INTERPRETER = frozenset({"sys.executable", "sys._base_executable"})

#: A command whose first word is called this is an interpreter command.
_INTERPRETER_NAME = re.compile(r"(?:^|[._])(?:interpreter|python\d*)$", re.IGNORECASE)


def _scan(path: Path) -> _Scan:
    scan = _Scan()
    scan.visit(ast.parse(path.read_text(encoding="utf-8"), filename=str(path)))
    return scan


def _scans() -> dict[str, _Scan]:
    return {_relative(path): _scan(path) for path in _production_files()}


def test_every_process_creating_site_is_accounted_for() -> None:
    """A new way of starting a process fails until it is described.

    Shown to fail by adding a ``subprocess.run`` call to a function that is
    not listed: the scan reports the function as unaccounted for. And by
    adding a second call to a listed function: the scan reports the changed
    count. Both pass again with the call removed.
    """
    found: dict[str, dict[str, int]] = {}
    for relative, scan in _scans().items():
        for (where, call), count in scan.creating.items():
            found.setdefault(f"{relative}::{where}", {})[call] = count
    listed = {key: site.calls for key, site in _SITES.items()}

    unaccounted = {key: calls for key, calls in found.items() if key not in listed}
    assert not unaccounted, (
        f"process-creating sites that are not accounted for: {unaccounted}"
    )
    gone = sorted(set(listed) - set(found))
    assert not gone, f"listed sites that no longer create a process: {gone}"
    changed = {
        key: (listed[key], calls)
        for key, calls in found.items()
        if listed[key] != calls
    }
    assert not changed, f"sites whose creating calls changed (listed, found): {changed}"


def test_every_python_child_takes_its_command_from_the_builder() -> None:
    """A site listed as a Python child is tied to the builder call that feeds it.

    Shown to fail by replacing the builder call in the environment probe with
    a hand-written command: the probe is then reported as not built by
    ``inline_command``. Passes with the call restored.
    """
    scans = _scans()
    python_sites = {
        key for key, site in _SITES.items() if site.starts is _Starts.PYTHON
    }
    unnamed = sorted(python_sites - set(_BUILT_BY))
    assert not unnamed, f"python children with no builder named: {unnamed}"
    not_built: list[str] = []
    for site, (builder_site, builder) in _BUILT_BY.items():
        relative, _, where = builder_site.partition("::")
        if scans[relative].builder_calls[where, builder] < 1:
            not_built.append(f"{site} is not built by {builder} in {builder_site}")
    assert not not_built, not_built


def test_the_interpreter_mode_switches_are_spelt_only_where_they_are_listed() -> None:
    """A hand-built interpreter command has to spell a mode switch, and cannot.

    Shown to fail by writing ``[interpreter, "-m", module]`` in the service
    launch in place of the builder call: the scan reports the extra ``-m`` in
    that file. Passes with the builder call restored.
    """
    found = {
        relative: scan.mode_switches
        for relative, scan in _scans().items()
        if scan.mode_switches
    }

    assert found == _MODE_SWITCH_HOMES, (
        "an interpreter mode switch is spelt outside the command builder and "
        f"the launch recogniser, or one of them changed: {found}"
    )


def test_no_command_is_assembled_around_an_interpreter_by_hand() -> None:
    """The interpreter reaches a command only as an argument to the builder.

    This is the scan that catches a script child, which spells no mode switch
    at all. Shown to fail by writing ``[sys.executable, str(runner), ...]`` in
    the preprocess runner in place of the builder call: the scan reports that
    function and line. Passes with the builder call restored.
    """
    hand_built = {
        relative: scan.hand_built
        for relative, scan in _scans().items()
        if scan.hand_built and relative != _BUILDER
    }

    assert not hand_built, (
        f"commands assembled around an interpreter by hand: {hand_built}"
    )


def test_no_process_is_started_through_a_shell() -> None:
    """A shell would resolve its own command line; every command here is a list.

    Shown to fail by passing ``shell=True`` to one process-creating call: the
    scan reports the file and line. Passes with the argument removed.
    """
    shells = {
        relative: scan.shells for relative, scan in _scans().items() if scan.shells
    }

    assert not shells, f"a process is started through a shell: {shells}"


def test_the_monitor_starts_its_python_child_in_safe_path_mode() -> None:
    """The monitor is not Python, so the scans above cannot see its child.

    Its server source is read as text: wherever it passes the module switch
    to an interpreter, the safe-path flag comes immediately before it. Shown
    to fail by removing the flag from the one command the monitor builds.
    """
    server = _PACKAGE.parent / "monitor" / "server"
    sources = sorted(server.glob("*.ts"))
    assert sources, f"no monitor server source under {server}"

    launches = 0
    for source in sources:
        text = source.read_text(encoding="utf-8")
        for match in re.finditer(r'"-m"', text):
            launches += 1
            preceding = text[: match.start()].rstrip()
            assert preceding.endswith('"-P",'), (
                f"{source.name}: a module is run without the safe-path flag"
            )
    assert launches, "the monitor no longer runs a module; this scan reads nothing"

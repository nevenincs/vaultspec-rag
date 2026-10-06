"""Tests for the model hub endpoint setting and its export to the hub client.

The hub client reads ``HF_ENDPOINT`` once, when it is first imported, and
builds its download URLs from that reading. So the setting is only as good as
its timing: a value exported after the client is imported configures nothing,
and nothing fails to say so - the downloads simply go to the default hub.

That is why the ordering is proven here the way it can actually break. Each
real process entry is run in a fresh interpreter, and the client's endpoint
constant is read after the entry returns. An in-process check could not tell:
this interpreter imported the client long before any test ran.

The rest drives the real settings object over the real process environment,
for the precedence between this package's variable and the client's own.
"""

from __future__ import annotations

import ast
import os
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from vaultspec_core.config import VAULTSPEC_TARGET_DIR

from ..cli._process import _build_service_child_env, _ServiceChildEnvRequest
from ..config import _settings
from ..config._registry import entry
from ..config._settings import (
    collect_environment_problems,
    get_config,
    publish_model_hub_endpoint,
)
from ..config._types import EnvVar
from ..server import _main as server_main
from ._config_fixtures import reset_config
from ._scaffold import restore_env

if TYPE_CHECKING:
    from collections.abc import Iterator

pytestmark = [pytest.mark.unit]

_DEFAULT = "https://huggingface.co"
_MIRROR = "https://hub.mirror.example:8443/models"

#: What an operator who configures the client directly might have set. Plain
#: HTTP on purpose: this package does not hold the client's own variable to
#: its HTTPS rule, and a test hub on loopback is exactly this shape.
_OPERATOR = "http://127.0.0.1:9/operator-hub"

_ENDPOINT_VARS = (EnvVar.RAG_HF_ENDPOINT, EnvVar.HF_ENDPOINT)

_URL_SHAPE = "an https URL with a host and no credentials, query or fragment"

#: Run the real CLI entry with no command, which runs the root callback and
#: then prints help, and report the endpoint the client then holds.
_CLI_ENTRY = """
import sys
sys.argv = ["vaultspec-rag"]
from vaultspec_rag.__main__ import main
try:
    main()
except SystemExit as stop:
    assert stop.code in (0, None), stop.code
import huggingface_hub.constants as hub
print("ENDPOINT=" + hub.ENDPOINT, file=sys.stderr)
"""

#: Run the real server entry on its stdio transport, which returns when
#: standard input ends, and report the endpoint the client then holds.
_SERVER_ENTRY = """
import sys
sys.argv = ["vaultspec-search-mcp"]
from vaultspec_rag.server import main
main()
import huggingface_hub.constants as hub
print("ENDPOINT=" + hub.ENDPOINT, file=sys.stderr)
"""


@pytest.fixture
def clean_endpoint() -> Iterator[None]:
    """Run with neither endpoint variable set, and put both back afterwards.

    Restored by hand rather than through ``monkeypatch``: the code under test
    writes the client's variable itself, and a variable that was absent when
    the test began has to be removed again, not left behind for the next test
    to import a client under.
    """
    saved = {var: os.environ.pop(var.value, None) for var in _ENDPOINT_VARS}
    reset_config()
    try:
        yield
    finally:
        for var, previous in saved.items():
            restore_env(var, previous)
        reset_config()


def _endpoint_after(
    entry_script: str,
    tmp_path: Path,
    *,
    configured: str | None,
    operator: str | None,
) -> str:
    """Run one process entry in a fresh interpreter; return the client's endpoint."""
    removed = {
        EnvVar.RAG_HF_ENDPOINT.value,
        EnvVar.HF_ENDPOINT.value,
        EnvVar.RAG_ROOT.value,
        VAULTSPEC_TARGET_DIR.env_name,
    }
    env = {name: value for name, value in os.environ.items() if name not in removed}
    env[EnvVar.STATUS_DIR.value] = str(tmp_path / "status")
    env[EnvVar.QDRANT_STORAGE_DIR.value] = str(tmp_path / "storage")
    if configured is not None:
        env[EnvVar.RAG_HF_ENDPOINT.value] = configured
    if operator is not None:
        env[EnvVar.HF_ENDPOINT.value] = operator
    proc = subprocess.run(
        [sys.executable, "-c", entry_script],
        capture_output=True,
        text=True,
        check=False,
        stdin=subprocess.DEVNULL,
        env=env,
        cwd=tmp_path,
        timeout=180,
    )
    assert proc.returncode == 0, proc.stderr
    reported = [
        line.removeprefix("ENDPOINT=")
        for line in proc.stderr.splitlines()
        if line.startswith("ENDPOINT=")
    ]
    assert len(reported) == 1, proc.stderr
    return reported[0]


_ENTRY_CASES = [
    pytest.param(_MIRROR + "/", _OPERATOR, _MIRROR, id="configured-beats-operator"),
    pytest.param(None, _OPERATOR, _OPERATOR, id="operator-only"),
    pytest.param(None, None, _DEFAULT, id="neither"),
]


@pytest.mark.parametrize(("configured", "operator", "expected"), _ENTRY_CASES)
def test_the_cli_entry_exports_the_endpoint_before_the_client_loads(
    tmp_path: Path, configured: str | None, operator: str | None, expected: str
) -> None:
    """After the real CLI entry runs, the client holds the configured endpoint.

    Mutation: with the export removed from the root callback, the
    ``configured-beats-operator`` case failed on this assertion, the client
    holding the operator's value in place of the configured one. Restored, it
    passed. The other two cases are what the export must not disturb.
    """
    seen = _endpoint_after(
        _CLI_ENTRY, tmp_path, configured=configured, operator=operator
    )

    assert seen == expected


@pytest.mark.parametrize(("configured", "operator", "expected"), _ENTRY_CASES[:2])
def test_the_server_entry_exports_the_endpoint_before_the_client_loads(
    tmp_path: Path, configured: str | None, operator: str | None, expected: str
) -> None:
    """After the real server entry runs, the client holds the configured endpoint.

    The entry is run on its stdio transport, which returns when standard input
    ends. The resident daemon cannot be started in this lane, because it loads
    models onto the accelerator; it reaches the same preflight function, which
    the next test pins.

    Mutation: with the export removed from the server's preflight, the
    ``configured-beats-operator`` case failed on this assertion, the client
    holding the operator's value. Restored, it passed.
    """
    seen = _endpoint_after(
        _SERVER_ENTRY, tmp_path, configured=configured, operator=operator
    )

    assert seen == expected


def test_the_http_daemon_runs_the_shared_preflight_before_anything_else() -> None:
    """The daemon's first statement is the preflight that exports the endpoint.

    Everything the daemon imports afterwards may import the hub client, and
    most of it eventually does. An import placed ahead of the preflight would
    fix the client's endpoint before the configured one was exported.

    Mutation: with the preflight call moved below the daemon's first import,
    this failed on the assertion below; restored, it passed.
    """
    tree = ast.parse(Path(server_main.__file__).read_text(encoding="utf-8"))
    daemon = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "_run_http_daemon"
    )
    statements = daemon.body[1:] if ast.get_docstring(daemon) else daemon.body
    first = statements[0]

    assert (
        isinstance(first, ast.Expr)
        and isinstance(first.value, ast.Call)
        and isinstance(first.value.func, ast.Name)
        and first.value.func.id == "_refuse_unusable_server_environment"
    ), ast.unparse(first)


@pytest.mark.usefixtures("clean_endpoint")
def test_the_default_is_the_official_hub() -> None:
    assert get_config().hf_endpoint == _DEFAULT


@pytest.mark.usefixtures("clean_endpoint")
def test_the_configured_endpoint_outranks_the_operators_own() -> None:
    """This package's variable wins, normalised, over a value already set.

    Mutation: exporting only when the client's variable was unset failed this
    assertion with the operator's value; restored, it passed.
    """
    os.environ[EnvVar.HF_ENDPOINT.value] = _OPERATOR
    os.environ[EnvVar.RAG_HF_ENDPOINT.value] = f"  {_MIRROR}/  "

    publish_model_hub_endpoint()

    assert os.environ[EnvVar.HF_ENDPOINT.value] == _MIRROR


@pytest.mark.parametrize(
    "configured", [None, "", "   "], ids=["unset", "empty", "blank"]
)
@pytest.mark.usefixtures("clean_endpoint")
def test_an_operators_own_endpoint_is_left_exactly_as_set(
    configured: str | None,
) -> None:
    """With this package's variable unset or blank, nothing is overwritten.

    The operator's value is not this package's to validate, so a plain-HTTP
    one survives untouched. Mutation: exporting the resolved setting whether
    or not the variable was set failed this assertion with the default hub in
    place of the operator's value; restored, it passed.
    """
    os.environ[EnvVar.HF_ENDPOINT.value] = _OPERATOR
    if configured is not None:
        os.environ[EnvVar.RAG_HF_ENDPOINT.value] = configured

    publish_model_hub_endpoint()

    assert os.environ[EnvVar.HF_ENDPOINT.value] == _OPERATOR


@pytest.mark.usefixtures("clean_endpoint")
def test_nothing_is_exported_when_only_the_default_applies() -> None:
    """Unset means the client's own default, reached by exporting nothing.

    Mutation: the same unconditional export failed this assertion, the
    client's variable appearing in the environment; restored, it passed.
    """
    publish_model_hub_endpoint()

    assert EnvVar.HF_ENDPOINT.value not in os.environ


@pytest.mark.usefixtures("clean_endpoint")
def test_exporting_does_not_cache_a_configuration() -> None:
    """The export runs before a workspace root is resolved, so it caches nothing."""
    os.environ[EnvVar.RAG_HF_ENDPOINT.value] = _MIRROR

    publish_model_hub_endpoint()

    assert _settings._cached_config is None


@pytest.mark.parametrize(
    "raw",
    [
        "http://hub.mirror.example/models",
        "hub.mirror.example/models",
        "https://user:secret@hub.mirror.example/models",
        "https://hub.mirror.example/models?token=abc",
    ],
    ids=["plain-http", "no-scheme", "credentials", "query"],
)
@pytest.mark.usefixtures("clean_endpoint")
def test_an_unusable_configured_endpoint_is_refused_and_never_exported(
    raw: str,
) -> None:
    """A bad endpoint stops the process at startup and reaches no client.

    Mutation: with the endpoint's declared shape removed from the bounds
    table, every case failed on the problem-count assertion (0 in place of
    1), and the normalisation in the outranking test above failed with the
    trailing slash kept; restored, all passed.
    """
    os.environ[EnvVar.RAG_HF_ENDPOINT.value] = raw
    reset_config()

    problems = collect_environment_problems(None)

    assert len(problems) == 1
    assert EnvVar.RAG_HF_ENDPOINT.value in problems[0]
    assert "hf_endpoint" in problems[0]
    assert _URL_SHAPE in problems[0]
    with pytest.raises(ValueError, match=EnvVar.RAG_HF_ENDPOINT.value):
        publish_model_hub_endpoint()
    assert EnvVar.HF_ENDPOINT.value not in os.environ


@pytest.mark.usefixtures("clean_endpoint")
def test_a_spawned_daemon_inherits_the_exported_endpoint() -> None:
    """The daemon's environment carries the export, so it needs no file.

    The daemon is configured only through the environment the command line
    hands it. Both names travel: the client's, which takes effect the moment
    the daemon imports the client, and this package's, from which the daemon
    re-derives the same value at its own entry.
    """
    os.environ[EnvVar.RAG_HF_ENDPOINT.value] = _MIRROR
    publish_model_hub_endpoint()

    child = _build_service_child_env(_ServiceChildEnvRequest())

    assert child[EnvVar.HF_ENDPOINT.value] == _MIRROR
    assert child[EnvVar.RAG_HF_ENDPOINT.value] == _MIRROR


def test_the_endpoint_setting_cannot_be_supplied_by_a_workspace_file() -> None:
    """A project may not choose the hub a host downloads models from.

    The two declarations that would open a file to it are both absent, and it
    is not a credential, the only kind of entry a workspace ``.env`` may
    supply. The client's own variable is another project's name and is never
    read from a file by this package either.
    """
    for var in _ENDPOINT_VARS:
        declared = entry(var)
        assert not declared.workspace_dotenv, var
        assert not declared.persistable, var
        assert not declared.secret, var

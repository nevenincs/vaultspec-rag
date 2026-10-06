"""The storage backend a ``server start`` selects, decided once.

A start reads its backend in two places: the preflight that fetches the Qdrant
server, and the environment it hands the daemon. When those disagreed, a plain
start after ``install --local-only`` downloaded a server and then told the
daemon to run it, over the choice the operator had saved.

Every combination below is driven through the three things that have to agree,
with nothing substituted:

- the decision the command makes from its flags and the settings;
- the environment built for the daemon from that decision, read back by a
  real child interpreter that resolves its settings the way the daemon does;
- the preflight, run against an empty managed directory with downloading
  switched off, so a preflight that wrongly wants a server fails by name and
  one that rightly wants none passes without ever having a network to reach.

Precedence under test, highest first: a flag, an exported variable, the saved
choice, the default. The address of a server that is already running is
orthogonal: no flag overrides it, and it means no server is fetched.
"""

from __future__ import annotations

import io
import json
import subprocess
import sys
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, cast

import pytest
import typer

from .._python_child import inline_command
from ..cli._core import _build_console
from ..cli._process import _build_service_child_env, _ServiceChildEnvRequest
from ..cli._progress import StartupStatusReporter
from ..cli._service_start import (
    _ensure_start_dependencies,
    _ServiceStartOptions,
)
from ..commands._provision import LOCAL_STORE_SELECTED, decide_backend
from ..config._paths import persist_local_only
from ..config._types import EnvVar
from ..operator_state._installation import ComputeCapability
from ..operator_state._service_environment import ServiceEnvironment
from ..qdrant_runtime._resolve import resolve_binary
from ._model_cache_seed import seed_model_cache
from .conftest import managed_env

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

pytestmark = [pytest.mark.unit]

_LOCAL = EnvVar.LOCAL_ONLY.value
_SERVER = EnvVar.QDRANT_SERVER.value
_URL = EnvVar.QDRANT_URL.value
_REMOTE = "http://qdrant.invalid:6333"

#: The judgement a start has made of its environment by the time it
#: reaches the dependency step: it only gets there accepted.
_ACCEPTED = ServiceEnvironment(sys.executable, ComputeCapability.READY)

#: What a daemon would decide from the environment it was handed. Run in a
#: real interpreter because the claim under test is about a second process:
#: it has the variables and the saved choice, and none of this one's flags.
_DAEMON_PROGRAM = """
import json
from vaultspec_rag.config._settings import get_config
settings = get_config()
print(json.dumps({
    "server_mode": bool(settings.effective_server_mode()),
    "remote": bool(str(settings.qdrant_url or "")),
}))
"""


@dataclass(frozen=True)
class _Case:
    """One combination of saved choice, exported variables and flags.

    Attributes:
        saved: The choice ``install`` saved, or ``None`` for none.
        exported: The backend variables the operator exported.
        local_only: Whether ``--local-only`` is passed.
        qdrant: ``--qdrant`` (``True``), ``--no-qdrant`` (``False``) or
            neither.
        runs_server: Whether the daemon must run the managed server, and so
            whether the preflight must ensure one.
        written: The backend variables the start itself must write for the
            daemon. Everything else has to reach the daemon as exported.
    """

    saved: bool | None = None
    exported: dict[str, str] = field(default_factory=dict[str, str])
    local_only: bool = False
    qdrant: bool | None = None
    runs_server: bool = True
    written: dict[str, str] = field(default_factory=dict[str, str])


_CASES = {
    # No flag: the settings decide, and the start writes nothing.
    "default": _Case(),
    "saved-local-only": _Case(saved=True, runs_server=False),
    "saved-server-mode": _Case(saved=False),
    "exported-local-only": _Case(exported={_LOCAL: "1"}, runs_server=False),
    "exported-server-mode-off": _Case(exported={_SERVER: "0"}, runs_server=False),
    "exported-remote-address": _Case(exported={_URL: _REMOTE}, runs_server=False),
    "export-outranks-saved": _Case(saved=True, exported={_LOCAL: "0"}),
    # Flags: each outranks everything beneath it.
    "local-only-flag": _Case(local_only=True, runs_server=False, written={_LOCAL: "1"}),
    "local-only-flag-over-export": _Case(
        exported={_LOCAL: "0", _SERVER: "1"},
        local_only=True,
        runs_server=False,
        written={_LOCAL: "1"},
    ),
    "no-qdrant-flag": _Case(qdrant=False, runs_server=False, written={_SERVER: "0"}),
    "qdrant-flag-over-saved": _Case(
        saved=True, qdrant=True, written={_SERVER: "1", _LOCAL: "0"}
    ),
    "qdrant-flag-over-exports": _Case(
        exported={_LOCAL: "1", _SERVER: "0"},
        qdrant=True,
        written={_SERVER: "1", _LOCAL: "0"},
    ),
    "local-only-outranks-qdrant": _Case(
        local_only=True,
        qdrant=True,
        runs_server=False,
        written={_LOCAL: "1", _SERVER: "1"},
    ),
    # The remote address is orthogonal: no flag makes a start fetch a server.
    "qdrant-flag-keeps-remote-address": _Case(
        exported={_URL: _REMOTE},
        qdrant=True,
        runs_server=False,
        written={_SERVER: "1", _LOCAL: "0"},
    ),
}


@pytest.fixture(params=sorted(_CASES), ids=sorted(_CASES))
def staged(
    request: pytest.FixtureRequest, isolated_status_dir: Path
) -> Generator[_Case]:
    """Stage one case: the saved choice on disk, the exports in the environment."""
    del isolated_status_dir
    case = _CASES[cast("str", request.param)]
    unset: dict[str, str | None] = {_LOCAL: None, _SERVER: None, _URL: None}
    with managed_env(**{**unset, **case.exported}):
        if case.saved is not None:
            persist_local_only(case.saved)
        yield case


def _daemon_environment(case: _Case) -> dict[str, str]:
    """The environment a start with *case*'s flags builds for its daemon."""
    backend = decide_backend(local_only=case.local_only, qdrant=case.qdrant)
    return _build_service_child_env(
        _ServiceChildEnvRequest(qdrant=backend.qdrant, local_only=backend.local_only)
    )


def _daemon_runs_server(environment: dict[str, str]) -> bool:
    """Ask a real interpreter, given *environment*, whether it runs the server."""
    finished = subprocess.run(
        inline_command(sys.executable, _DAEMON_PROGRAM),
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
        check=False,
    )
    assert finished.returncode == 0, finished.stderr
    last_line = finished.stdout.strip().splitlines()[-1]
    facts = cast("dict[str, bool]", json.loads(last_line))
    return facts["server_mode"] and not facts["remote"]


def test_the_command_decides_what_the_settings_and_flags_call_for(
    staged: _Case,
) -> None:
    """Mutation check: with the decision taken from the flags alone, as it
    was, the saved and exported cases all answer that a server is needed and
    fail here; with ``--qdrant`` no longer overriding the on-disk choice, the
    two ``qdrant-flag-over`` cases fail here. Restoring each passes.
    """
    backend = decide_backend(local_only=staged.local_only, qdrant=staged.qdrant)

    assert (backend.server_unneeded is None) is staged.runs_server


def test_the_daemon_is_handed_only_what_a_flag_decided(staged: _Case) -> None:
    """A backend variable reaches the daemon as a flag set it, or as exported.

    Mutation check: with ``--local-only``'s absence written as an explicit
    off, as it was, every case with no flag carries a local-only variable the
    operator never set, and the comparison fails on it; restoring passes.
    """
    environment = _daemon_environment(staged)

    expected = {**staged.exported, **staged.written}
    carried = {
        name: environment[name]
        for name in (_LOCAL, _SERVER, _URL)
        if name in environment
    }
    assert carried == expected


def test_the_daemon_reaches_the_backend_the_command_decided(staged: _Case) -> None:
    """The second process agrees with the first, from its environment alone.

    Mutation check: with ``--local-only``'s absence written as an explicit
    off, the daemon of the saved-local-only case runs a server the command
    decided against, and the assertion fails; restoring passes.
    """
    assert _daemon_runs_server(_daemon_environment(staged)) is staged.runs_server


def _options(case: _Case) -> _ServiceStartOptions:
    return _ServiceStartOptions(
        port=8766,
        updates=None,
        update_delay_ms=None,
        repeat_update_delay_s=None,
        local_only=case.local_only,
        qdrant=case.qdrant,
        qdrant_auto_provision=None,
        no_preprocess=False,
        json_mode=False,
    )


@pytest.mark.usefixtures("inference_host")
def test_the_preflight_wants_a_server_only_when_the_daemon_will_run_one(
    staged: _Case,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """With downloading off and nothing installed, wanting a server is a failure.

    That makes the preflight's own opinion observable without a network: the
    cases that need no server pass and say why, and the cases that need one
    stop on the missing server. Nothing is written to the managed directory
    either way.

    Mutation check: with the preflight reading the flags instead of the
    decision, the saved, exported and remote cases stop with the missing
    server and fail the exit assertion; restoring passes.
    """
    off = {
        EnvVar.QDRANT_AUTO_PROVISION.value: "0",
        EnvVar.HF_HUB_OFFLINE.value: "1",
    }
    with managed_env(**off):
        seed_model_cache(monkeypatch, tmp_path / "hf-cache")
        assert resolve_binary() is None, "premise: no server may already resolve"
        backend = decide_backend(local_only=staged.local_only, qdrant=staged.qdrant)
        reporter = StartupStatusReporter(
            json_mode=False,
            console=_build_console(interactive=False, file=io.StringIO()),
            interactive=False,
            static_interval_s=0.0,
        )
        stopped: int | None = None
        try:
            with reporter:
                _ensure_start_dependencies(
                    _options(staged), backend, _ACCEPTED, reporter
                )
        except typer.Exit as exit_:
            stopped = exit_.exit_code

    output = " ".join(capsys.readouterr().out.split())
    if staged.runs_server:
        assert stopped == 1
        assert "vaultspec-rag server qdrant install" in output
    else:
        assert stopped is None, output
        assert "Qdrant binary: skipped" in output


def test_a_remote_address_is_named_as_the_reason_and_not_repeated() -> None:
    """The skip says which setting made the server unnecessary, not its value.

    An address can carry a credential, and this sentence is printed.
    """
    secret = "http://user:hunter2@qdrant.invalid:6333"
    with managed_env(**{_URL: secret, _LOCAL: None, _SERVER: None}):
        reason = decide_backend(local_only=False, qdrant=None).server_unneeded

    assert reason is not None
    assert _URL in reason
    assert "hunter2" not in reason
    assert reason != LOCAL_STORE_SELECTED

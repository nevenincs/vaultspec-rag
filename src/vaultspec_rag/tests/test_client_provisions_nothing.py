"""A client installation provisions nothing, on any command.

A client carries no inference stack: it loads no model and cannot run the
service, so a model snapshot or a Qdrant server binary fetched for it is a
download nobody will use. Every command that provisions on a host is driven
here as a client, and each must leave the network and the managed directory
alone.

The installation role is the one pinned input, as everywhere else in the
suite, so the client branch is exercised on a GPU workstation too. The
provisioner's network half is replaced by a recording tripwire that is never
supposed to be reached; it exists for the regressed run, which would otherwise
download the pinned release and - on the start path - go on to spawn a daemon.
The model cache is an empty directory the test owns, with the hub's offline
switch set, so every model is missing and a regressed run fails loudly rather
than fetching gigabytes. What each test asserts is the real outcome: the
report the command gives a client, and a managed directory and a model cache
with nothing new in them.
"""

from __future__ import annotations

import json
import socket
from contextlib import contextmanager
from typing import TYPE_CHECKING, cast

import pytest

from .._sync_vocabulary import ProvisionAction
from ..commands._install import install_run
from ..commands._provision import ProvisionStep
from ..config._paths import read_persisted_local_only
from ..config._settings import configured_model_repos
from ..config._types import EnvVar
from ..operator_state._installation import ComputeCapability
from ._cli_helpers import app, runner
from ._model_cache_seed import seed_model_cache
from ._qdrant_provision_seam import substitute_qdrant_download
from .conftest import managed_env

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

pytestmark = [pytest.mark.unit, pytest.mark.usefixtures("client_installation")]

PROJECT_ONLY = (
    "[project]\n"
    'name = "demo-client"\n'
    'version = "0.1.0"\n'
    'dependencies = ["vaultspec-rag[mcp]"]\n'
)

_NOT_NEEDED = "not needed by a client installation"


def _tree(root: Path) -> list[str]:
    """Every path under *root*, so a comparison names whatever appeared."""
    return sorted(path.relative_to(root).as_posix() for path in root.rglob("*"))


@contextmanager
def _occupied_port() -> Generator[int]:
    """Hold a real listening socket and yield its port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        sock.listen(1)
        yield int(sock.getsockname()[1])


@pytest.fixture(autouse=True)
def empty_model_cache(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> Generator[Path]:
    """An empty model cache with the hub offline, for every test here.

    Every configured model is missing from it, so a command that wrongly
    reached the model fetch would have something to download - and, offline,
    fails instead. Yields the cache directory so a test can assert nothing
    appeared in it.
    """
    with managed_env(**{EnvVar.HF_HUB_OFFLINE.value: "1"}):
        every_repo = [repo for _label, repo in configured_model_repos()]
        yield seed_model_cache(monkeypatch, tmp_path / "hf-cache", missing=every_repo)


def test_start_is_refused_before_anything_is_provisioned(
    monkeypatch: pytest.MonkeyPatch,
    isolated_singleton_dirs: Path,
    tmp_path: Path,
) -> None:
    """``server start`` judges the role before it does anything else.

    The start is aimed at a port something else holds. The port guard is the
    first thing after the role, and everything a start fetches or spawns comes
    after the guard, so a client that is refused as a client - rather than for
    the port - was judged before any of it. The occupied port is also what
    keeps a regressed run from going on to spawn a daemon on this machine.

    Mutation check: with the refusal removed from the start command, or moved
    after the dependency fetch, the start reaches the port guard first and
    fails as ``port_in_use`` - failing the error assertion. Restoring it
    passes.
    """
    del isolated_singleton_dirs
    calls = substitute_qdrant_download(monkeypatch, succeeds=False)
    before = _tree(tmp_path)

    with _occupied_port() as port:
        result = runner.invoke(
            app,
            [
                "server",
                "start",
                "--json",
                "--qdrant-auto-provision",
                "--port",
                str(port),
            ],
        )

    assert calls == [], "a client start reached the Qdrant provisioner"
    assert _tree(tmp_path) == before
    assert result.exit_code == 1, result.output
    payload = cast("dict[str, object]", json.loads(result.stdout))
    assert payload["ok"] is False
    assert payload["error"] == "service_env_no_gpu"
    data = cast("dict[str, object]", payload["data"])
    assert data["detail"] == ComputeCapability.NOT_APPLICABLE.label


def test_install_provisions_nothing_with_every_step_left_on(
    monkeypatch: pytest.MonkeyPatch,
    isolated_singleton_dirs: Path,
    empty_model_cache: Path,
    tmp_path: Path,
) -> None:
    """``install`` with no opt-out at all still fetches nothing for a client.

    No ``--local-only`` and no skip token, so the role is the only thing
    standing between this run and both downloads.

    Mutation check: with the front door's client answer disabled, the Qdrant
    step reaches the tripwire - failing the ``calls`` assertion with
    ``['provision']`` - and the model step reports the offline failure in
    place of the not-needed answer. Restoring it passes.
    """
    workspace = tmp_path / "client"
    workspace.mkdir()
    (workspace / "pyproject.toml").write_text(
        PROJECT_ONLY, encoding="utf-8", newline=""
    )
    calls = substitute_qdrant_download(monkeypatch, succeeds=False)
    before = _tree(isolated_singleton_dirs)

    report = install_run(path=workspace, provision=True, assume_yes=True)

    assert calls == [], "a client install reached the Qdrant provisioner"
    outcome = report.provision_outcome
    assert outcome is not None
    assert {result.step for result in outcome.steps} == set(ProvisionStep)
    for result in outcome.steps:
        assert result.action == ProvisionAction.SKIPPED, result
        assert _NOT_NEEDED in result.detail, result
    assert _tree(isolated_singleton_dirs) == before
    assert _tree(empty_model_cache) == []
    assert read_persisted_local_only() is None


def test_warmup_reports_models_as_not_needed_and_fetches_none(
    empty_model_cache: Path,
) -> None:
    """``server warmup`` tells a client the models are not needed, and stops.

    The cache probe is what the fetch reports first, so its absence, and a
    model cache with nothing in it, are the evidence that no repository was
    looked for or downloaded.

    Mutation check: with the front door's client answer disabled, the verb
    walks the model list, which is all missing with the hub offline, and
    exits 1 - failing the not-needed assertion. Restoring it passes.
    """
    result = runner.invoke(app, ["server", "warmup"])

    assert _NOT_NEEDED in result.output, result.output
    assert "Checking the cache" not in result.output
    assert _tree(empty_model_cache) == []
    assert result.exit_code == 0, result.output


@pytest.mark.parametrize("from_a_local_archive", [False, True])
def test_qdrant_install_reports_skipped_and_writes_nothing(
    monkeypatch: pytest.MonkeyPatch,
    isolated_status_dir: Path,
    tmp_path: Path,
    from_a_local_archive: bool,
) -> None:
    """``server qdrant install`` is not needed on a client, like torch.

    Installing from a local archive is provisioning too: it puts an
    executable into the managed directory, so a client is answered the same
    way for both shapes of the verb, and the archive it named is not read.

    Mutation check: with the client answer removed from the front door's
    Qdrant entry, both shapes reach the tripwire - failing the ``calls``
    assertion with ``['provision']``. Restoring it passes.
    """
    calls = substitute_qdrant_download(monkeypatch, succeeds=False)
    argv = ["server", "qdrant", "install", "--json"]
    if from_a_local_archive:
        supplied = tmp_path / "release-archive"
        supplied.write_bytes(b"a local copy of the release package")
        argv += ["--archive", str(supplied)]
    before = _tree(isolated_status_dir)

    result = runner.invoke(app, argv)

    assert calls == [], "a client reached the Qdrant provisioner"
    assert _tree(isolated_status_dir) == before
    assert result.exit_code == 0, result.output
    payload = cast("dict[str, object]", json.loads(result.stdout))
    assert payload["ok"] is True
    data = cast("dict[str, object]", payload["data"])
    assert data["action"] == ProvisionAction.SKIPPED
    assert data["source"] is None
    assert _NOT_NEEDED in str(data["message"])

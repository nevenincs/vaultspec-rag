"""Service-first search routing and bounded local fallback (issue #202).

These tests are mock-free. They cover three layers of the fix:

* the local-search **mandate resolver** - local search runs only with an
  explicit mandate (``--allow-fallback`` or configured local-only mode), never
  merely because a service port was discovered;
* the **service-first routing** guarantee - a search with no reachable service
  and no mandate errors cleanly and spins up no local engine (proven in a fresh
  interpreter so the no-heavy-libs assertion is meaningful), covering both the
  no-service and the discovered-but-dead-service cases (the latter is the
  regression for the removed silent auto-fallback);
* the **wall-clock deadline** that bounds a mandated local run so a wedged model
  load or store open cannot hang while holding the index lock.

Status-dir isolation uses ``VAULTSPEC_RAG_STATUS_DIR`` per the project's
designated mechanism (see the ``feedback_service_tests_isolate_STATUS_DIR``
memory note).
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import threading
import time
from typing import TYPE_CHECKING

import pytest

from ..cli._search import (
    _local_only_configured,
    _local_search_deadline,
    _local_search_mandated,
)
from ..config import EnvVar, reset_config

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

pytestmark = [pytest.mark.unit]


def _repo_root() -> Path:
    """Return the repository root - a real vaultspec workspace (has .vault)."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[3]
    assert (root / ".vault").is_dir(), root
    return root


def _free_port() -> int:
    """Return a loopback port with no listener, so a connect is refused fast."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.fixture()
def isolated_status_dir(tmp_path: Path) -> Iterator[Path]:
    """Redirect the status dir at an empty tmp dir and clear the local mandate.

    Sets ``VAULTSPEC_RAG_STATUS_DIR`` to a fresh empty directory and clears
    ``VAULTSPEC_RAG_LOCAL_ONLY`` so neither the env nor the persisted marker
    grants a local mandate, then resets the cached config on enter and exit.
    Also isolates ``VAULTSPEC_RAG_QDRANT_STORAGE_DIR``: service discovery now
    resolves the machine-global pointer (status-directory independent) before
    the status-dir hint, so without this a real service running on the host
    would be discovered and the "no service" cases would not hold.
    """
    prev_status = os.environ.get(EnvVar.STATUS_DIR.value)
    prev_local = os.environ.get(EnvVar.LOCAL_ONLY.value)
    prev_storage = os.environ.get(EnvVar.QDRANT_STORAGE_DIR.value)
    status_dir = tmp_path / "vaultspec-rag"
    status_dir.mkdir()
    os.environ[EnvVar.STATUS_DIR.value] = str(status_dir)
    os.environ.pop(EnvVar.LOCAL_ONLY.value, None)
    os.environ[EnvVar.QDRANT_STORAGE_DIR.value] = str(
        tmp_path / "qdrant-server" / "storage"
    )
    reset_config()
    try:
        yield status_dir
    finally:
        for key, prev in (
            (EnvVar.STATUS_DIR.value, prev_status),
            (EnvVar.LOCAL_ONLY.value, prev_local),
            (EnvVar.QDRANT_STORAGE_DIR.value, prev_storage),
        ):
            if prev is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = prev
        reset_config()


class TestLocalSearchMandate:
    """Local search runs only under an explicit mandate."""

    def test_allow_fallback_flag_grants_mandate(
        self, isolated_status_dir: Path
    ) -> None:
        assert not (isolated_status_dir / "local-only.json").exists()
        assert _local_search_mandated(allow_fallback=True) is True

    def test_no_flag_no_config_is_service_first(
        self, isolated_status_dir: Path
    ) -> None:
        assert not (isolated_status_dir / "local-only.json").exists()
        assert _local_only_configured() is False
        assert _local_search_mandated(allow_fallback=False) is False

    def test_local_only_env_truthy_grants_mandate(
        self, isolated_status_dir: Path
    ) -> None:
        assert not (isolated_status_dir / "local-only.json").exists()
        os.environ[EnvVar.LOCAL_ONLY.value] = "1"
        reset_config()
        assert _local_search_mandated(allow_fallback=False) is True

    def test_local_only_env_falsey_denies_mandate(
        self, isolated_status_dir: Path
    ) -> None:
        assert not (isolated_status_dir / "local-only.json").exists()
        os.environ[EnvVar.LOCAL_ONLY.value] = "0"
        reset_config()
        assert _local_search_mandated(allow_fallback=False) is False

    def test_local_only_env_off_list_value_matches_canonical_parser(
        self, isolated_status_dir: Path
    ) -> None:
        """An off-allowlist value is NOT a mandate, matching the config parser.

        The canonical resolver treats only ``1``/``true``/``yes`` as truthy, so
        a value like ``on`` resolves to server mode there. The mandate resolver
        must agree (it delegates to the same parser) rather than re-implement a
        divergent denylist.
        """
        from ..config import get_config

        assert not (isolated_status_dir / "local-only.json").exists()
        os.environ[EnvVar.LOCAL_ONLY.value] = "on"
        reset_config()
        assert get_config().local_only is False
        assert _local_search_mandated(allow_fallback=False) is False


class TestLocalSearchDeadline:
    """The wall-clock deadline bounds a mandated local run."""

    def test_timer_fires_on_slow_body(self) -> None:
        fired = threading.Event()
        with _local_search_deadline(0.05, json_mode=False, on_timeout=fired.set):
            time.sleep(0.6)
        assert fired.is_set()

    def test_timer_cancelled_on_fast_body(self) -> None:
        fired = threading.Event()
        with _local_search_deadline(0.5, json_mode=False, on_timeout=fired.set):
            pass
        # The body returned immediately; the timer is cancelled on exit, well
        # before its 0.5s deadline, so the callback must never run.
        time.sleep(0.2)
        assert not fired.is_set()

    @pytest.mark.parametrize("seconds", [None, 0, -1.0])
    def test_non_positive_deadline_is_noop(self, seconds: float | None) -> None:
        fired = threading.Event()
        with _local_search_deadline(seconds, json_mode=False, on_timeout=fired.set):
            pass
        assert not fired.is_set()


def _run_cli_search_subprocess(
    status_dir: Path,
    *,
    service_json: dict[str, object] | None,
) -> subprocess.CompletedProcess[str]:
    """Run ``search`` in a fresh interpreter against an isolated status dir.

    When *service_json* is given it is written as the discovery file so the
    router resolves a (dead) port; otherwise discovery finds no service. The
    snippet asserts a non-zero exit and that no heavy ML library was imported,
    then prints the captured CLI output for the caller to assert on.
    """
    if service_json is not None:
        (status_dir / "service.json").write_text(
            json.dumps(service_json), encoding="utf-8"
        )
    code = (
        "import os, sys, json\n"
        f"os.environ['VAULTSPEC_RAG_STATUS_DIR'] = {str(status_dir)!r}\n"
        "os.environ.pop('VAULTSPEC_RAG_LOCAL_ONLY', None)\n"
        "from typer.testing import CliRunner\n"
        "from vaultspec_rag.cli import app\n"
        "res = CliRunner().invoke(\n"
        "    app,\n"
        f"    ['-t', {str(_repo_root())!r}, 'search', 'anything',\n"
        "     '--type', 'code', '--json'],\n"
        ")\n"
        "forbidden = ('torch', 'sentence_transformers', 'qdrant_client',\n"
        "             'transformers', 'onnxruntime')\n"
        "heavy = sorted(m for m in sys.modules\n"
        "    if any(m == f or m.startswith(f + '.') for f in forbidden))\n"
        "sys.stderr.write('EXIT=' + str(res.exit_code) + '\\n')\n"
        "sys.stderr.write('HEAVY=' + json.dumps(heavy) + '\\n')\n"
        "sys.stderr.write('OUT=' + json.dumps(res.output) + '\\n')\n"
        "assert res.exit_code != 0, res.output\n"
        "assert not heavy, heavy\n"
    )
    return subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        check=False,
    )


class TestServiceFirstRouting:
    """A search with no mandate never silently degrades to local."""

    def test_no_service_errors_and_loads_no_models(
        self, isolated_status_dir: Path
    ) -> None:
        """No discoverable service + no mandate -> service_down, no local engine."""
        proc = _run_cli_search_subprocess(isolated_status_dir, service_json=None)
        assert proc.returncode == 0, proc.stderr
        assert '"error": "service_down"' in proc.stderr or "service_down" in (
            proc.stderr
        )

    def test_discovered_dead_service_errors_without_fallback(
        self, isolated_status_dir: Path
    ) -> None:
        """A discovered-but-dead service no longer auto-falls back to local.

        This is the direct regression for the removed silent auto-fallback: a
        ``service.json`` is present (so a port is discovered) but nothing
        listens, so the router must report the service unreachable and load no
        models rather than degrade to an unbounded local search.
        """
        proc = _run_cli_search_subprocess(
            isolated_status_dir,
            service_json={"pid": 999_999, "port": _free_port(), "service_token": ""},
        )
        assert proc.returncode == 0, proc.stderr
        assert "port_unreachable" in proc.stderr

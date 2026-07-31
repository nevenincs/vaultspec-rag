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
from ..config._settings import reset_config
from ..config._types import EnvVar
from ..serviceclient._compat import SERVICE_VERSION_FIELD, local_package_version
from ._ports import free_loopback_port
from .conftest import managed_env

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


@pytest.fixture()
def isolated_status_dir(isolated_singleton_dirs: Path) -> Iterator[Path]:
    """Add a cleared local mandate on top of the singleton-dir relocation.

    Both managed directories move because discovery resolves the machine-global
    pointer before the status-dir hint, so relocating only the status dir would
    let a live service on the host satisfy the "no service" cases. Clearing
    ``VAULTSPEC_RAG_LOCAL_ONLY`` on top of that is what makes the mandate come
    from neither the environment nor a persisted marker.
    """
    with managed_env(**{EnvVar.LOCAL_ONLY.value: None}):
        yield isolated_singleton_dirs


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

    def test_mandate_agrees_with_the_canonical_parser_on_every_spelling(
        self, isolated_status_dir: Path
    ) -> None:
        """The mandate resolver never re-implements truthiness.

        It delegates to the canonical config resolver, so it must agree on both
        halves of that parser's contract: ``on`` is a recognised truthy
        spelling and grants a mandate, while an unrecognised token is refused
        outright rather than silently read as false. A divergent denylist here
        would grant or withhold a mandate the config never agreed to.
        """
        from ..config._settings import get_config

        assert not (isolated_status_dir / "local-only.json").exists()
        os.environ[EnvVar.LOCAL_ONLY.value] = "on"
        reset_config()
        assert get_config().local_only is True
        assert _local_search_mandated(allow_fallback=False) is True

        os.environ[EnvVar.LOCAL_ONLY.value] = "onn"
        reset_config()
        with pytest.raises(ValueError, match=EnvVar.LOCAL_ONLY.value):
            _local_search_mandated(allow_fallback=False)


class TestLocalSearchDeadline:
    """The wall-clock deadline bounds a mandated local run."""

    def test_timer_fires_on_slow_body(self) -> None:
        fired = threading.Event()
        with _local_search_deadline(0.05, json_mode=False, on_timeout=fired.set):
            time.sleep(0.6)
        assert fired.is_set()

    def test_timer_cancelled_on_fast_body(self) -> None:
        """Exiting the body cancels the timer - observed, not raced against.

        Sleeping a fraction of the deadline and asserting the callback has not
        run proves only that the deadline had not arrived yet: the whole
        ``finally: timer.cancel()`` can be deleted and that still passes. So
        the deadline is set far beyond anything this test waits for, and the
        cancellation is observed on the timer itself. ``threading.Timer.cancel``
        sets the event the timer thread is waiting on, so a cancelled timer's
        thread ends within milliseconds while an armed one stays alive until it
        fires; joining with a bound far below the deadline is what makes a dead
        thread mean "cancelled" and not "expired".

        Do not shorten the deadline or lengthen the join bound toward each
        other - the gap between them is the whole proof.
        """
        deadline = 30.0
        join_bound = 2.0
        fired = threading.Event()
        pre_existing = set(threading.enumerate())
        with _local_search_deadline(deadline, json_mode=False, on_timeout=fired.set):
            armed = [
                thread
                for thread in threading.enumerate()
                if isinstance(thread, threading.Timer) and thread not in pre_existing
            ]
            assert len(armed) == 1, armed
            timer = armed[0]
            assert timer.is_alive()
        timer.join(join_bound)
        assert not timer.is_alive(), "the deadline timer was not cancelled on exit"
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
            service_json={
                "pid": 999_999,
                "port": free_loopback_port(),
                "service_token": "",
                # This release, so the subject stays reachability: a record
                # without it is refused on the release verdict and the dead
                # socket is never probed.
                SERVICE_VERSION_FIELD: local_package_version(),
            },
        )
        assert proc.returncode == 0, proc.stderr
        assert "port_unreachable" in proc.stderr

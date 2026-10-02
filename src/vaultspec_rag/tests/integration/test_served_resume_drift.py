"""A real served retry repairs a source changed after its admission."""

from __future__ import annotations

import json
import os
import time
from typing import TYPE_CHECKING, cast

import pytest

from ...indexer._run_ledger_models import RunAuthority
from ...job_models import JobMode, JobSource
from ...serviceclient._transport import (
    _try_http_create_job,
    _try_http_get_job,
    _try_http_health,
    _try_http_retry_job,
)
from .._child_signal import CHILD_PROCESS_TIMEOUT_SECONDS
from .conftest import _live_service_context

if TYPE_CHECKING:
    from pathlib import Path


def _object(value: object) -> dict[str, object]:
    assert isinstance(value, dict), value
    return cast("dict[str, object]", value)


def _job(response: object) -> dict[str, object]:
    envelope = _object(response)
    assert envelope.get("ok") is True, envelope
    return _object(envelope["job"])


def _wait_job(port: int, job_id: str, state: str) -> dict[str, object]:
    deadline = time.monotonic() + CHILD_PROCESS_TIMEOUT_SECONDS
    last: dict[str, object] = {}
    while time.monotonic() < deadline:
        last = _job(_try_http_get_job(job_id, port, timeout=5))
        if last["state"] == state:
            return last
        assert last["state"] not in {
            "cancelled",
            "interrupted",
            "succeeded",
            "failed",
        }, last
        time.sleep(0.1)
    pytest.fail(f"job did not reach {state}: {last!r}")


def _wait_marker(path: Path) -> None:
    deadline = time.monotonic() + CHILD_PROCESS_TIMEOUT_SECONDS
    while not path.exists():
        assert time.monotonic() < deadline, f"missing control marker: {path.name}"
        time.sleep(0.05)


def _job_failed(health: object) -> bool:
    reasons = _object(health)["degradations"]
    assert isinstance(reasons, list), reasons
    return any(
        _object(item)["reason"] == "job_failed"
        for item in cast("list[object]", reasons)
    )


@pytest.mark.subprocess_gpu
def test_served_retry_supersedes_a_moving_source_and_clears_degradation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "project"
    root.mkdir()
    (root / ".vault").mkdir()
    for number in range(12):
        (root / f"source_{number}.py").write_text(
            f"def source_{number}(value: int) -> int:\n    return value + {number}\n",
            encoding="utf-8",
        )
    control = tmp_path / "control"
    control.mkdir()
    bootstrap = tmp_path / "bootstrap"
    bootstrap.mkdir()
    (bootstrap / "sitecustomize.py").write_text(
        "import os, sys, traceback\n"
        "from pathlib import Path\n"
        "if any(sys.orig_argv[i:i+2] == ['-m', 'vaultspec_rag.server'] "
        "for i in range(len(sys.orig_argv)-1)):\n"
        "    try:\n"
        "        from vaultspec_rag.tests.integration._served_drift_control "
        "import install\n"
        f"        install(Path({str(root.resolve())!r}), Path({str(control)!r}))\n"
        "    except BaseException:\n"
        "        traceback.print_exc()\n"
        "        os._exit(1)\n",
        encoding="utf-8",
    )
    monkeypatch.setenv(
        "PYTHONPATH",
        os.pathsep.join((str(bootstrap), os.environ.get("PYTHONPATH", ""))),
    )
    with _live_service_context(tmp_path / "service") as (port, _, _):
        assert (control / "installed").exists()
        first = _job(
            _try_http_create_job(
                JobSource.CODE,
                str(root),
                port,
                authority=RunAuthority.REBUILD,
                mode=JobMode.REBUILD,
            )
        )
        first_id = first["id"]
        assert isinstance(first_id, str)
        failed = _wait_job(port, first_id, "failed")
        failed_health = _object(_try_http_health(port, timeout=5))
        assert failed_health["status"] == "degraded"
        assert _job_failed(failed_health)
        committed = _object(
            json.loads((control / "committed.json").read_text(encoding="utf-8"))
        )
        relative = committed["path"]
        assert isinstance(relative, str)
        source = (root / relative).resolve()
        assert source.is_relative_to(root.resolve())
        retry = _job(_try_http_retry_job(first_id, port))
        retry_id = retry["id"]
        assert isinstance(retry_id, str)
        assert retry["parent_job_id"] == first_id
        _wait_marker(control / "admitted")
        with source.open("a", encoding="utf-8") as stream:
            stream.write(
                "\ndef changed_after_admission() -> str:\n"
                "    return 'new source content'\n"
            )
        (control / "changed").touch()
        succeeded = _wait_job(port, retry_id, "succeeded")
        drift = _object(succeeded["drift"])
        count = drift["superseded_paths"]
        assert isinstance(count, int) and count > 0, succeeded
        failed_spec = _object(failed["spec"])
        succeeded_spec = _object(succeeded["spec"])
        assert succeeded_spec["source"] == failed_spec["source"] == JobSource.CODE.value
        assert (
            succeeded_spec["project_root"]
            == failed_spec["project_root"]
            == str(root.resolve())
        )
        _wait_marker(control / "restored")
        retained = _job(_try_http_get_job(first_id, port))
        assert retained["error_kind"] == failed["error_kind"]
        assert retained["finished_at"] == failed["finished_at"]
        healthy = _object(_try_http_health(port, timeout=5))
        assert not _job_failed(healthy)
        assert healthy["status"] == "ready"

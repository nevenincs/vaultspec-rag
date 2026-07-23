"""Real-process regressions for bounded model fixture acquisition."""

from __future__ import annotations

import contextlib
import http.server
import json
import os
import sys
import threading
import time
import uuid
from typing import TYPE_CHECKING, cast

import pytest

from ..config import EnvVar
from ._model_setup import (
    configured_service_model_ids,
    ensure_model_snapshots,
    model_setup_timeout_seconds,
    models_are_cached,
    run_bounded_process,
)
from .integration._helpers import _service_env
from .integration.conftest import (
    _MAX_STARTUP_LOAD_MULTIPLIER,
    _live_service_context,
    _resolve_startup_budget,
    _startup_load_multiplier,
    _verify_offline_service_startup,
)

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path


class _PersistentGatewayTimeout(http.server.BaseHTTPRequestHandler):
    """Delay if requested, then return a real HTTP 504."""

    response_delay_seconds = 0.0
    requests_received = 0

    def do_HEAD(self) -> None:
        self._gateway_timeout()

    def do_GET(self) -> None:
        self._gateway_timeout()

    def _gateway_timeout(self) -> None:
        type(self).requests_received += 1
        time.sleep(type(self).response_delay_seconds)
        self.send_response(http.HTTPStatus.GATEWAY_TIMEOUT)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(b"persistent metadata gateway timeout")

    def log_message(self, format: str, *args: object) -> None:
        """Keep the regression output focused on the acquisition worker."""


class _ThreadingGatewayTimeoutServer(http.server.ThreadingHTTPServer):
    """Do not wait for the deliberately blocked request thread at teardown."""

    daemon_threads = True


def test_configured_service_models_cover_eager_startup() -> None:
    """The bounded preparation set includes every default eager service model."""
    assert configured_service_model_ids() == (
        "Qwen/Qwen3-Embedding-0.6B",
        "naver/splade-v3",
        "BAAI/bge-reranker-v2-m3",
    )


@contextlib.contextmanager
def _gateway_timeout_endpoint(*, response_delay_seconds: float) -> Generator[str]:
    """Serve persistent metadata failures on a real loopback HTTP endpoint."""
    _PersistentGatewayTimeout.response_delay_seconds = response_delay_seconds
    _PersistentGatewayTimeout.requests_received = 0
    server = _ThreadingGatewayTimeoutServer(
        ("127.0.0.1", 0),
        _PersistentGatewayTimeout,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host = str(server.server_address[0])
    port = int(server.server_address[1])
    try:
        yield f"http://{host}:{port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_online_repair_clears_ambient_offline_mode(tmp_path: Path) -> None:
    """An offline parent still reaches the real acquisition endpoint."""
    offline_keys = (
        EnvVar.HF_HUB_OFFLINE.value,
        EnvVar.TRANSFORMERS_OFFLINE.value,
    )
    previous = {key: os.environ.get(key) for key in offline_keys}
    for key in offline_keys:
        os.environ[key] = "1"
    model_id = "vaultspec-regression/ambient-offline-model"
    try:
        with (
            _gateway_timeout_endpoint(response_delay_seconds=0) as endpoint,
            _service_env(
                tmp_path / "service-env",
                env_overrides=dict.fromkeys(offline_keys),
            ),
            pytest.raises(RuntimeError) as caught,
        ):
            ensure_model_snapshots(
                (model_id,),
                timeout_seconds=10,
                cache_dir=tmp_path / "hf-cache",
                endpoint=endpoint,
            )
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    assert _PersistentGatewayTimeout.requests_received > 0
    assert "504" in str(caught.value)
    assert endpoint in str(caught.value)
    assert all(os.environ.get(key) == previous[key] for key in offline_keys)


def test_service_env_entry_failure_restores_every_mutation(tmp_path: Path) -> None:
    """A real context-entry failure restores inherited service and HF values."""
    inherited = {
        "VAULTSPEC_RAG_STATUS_DIR": "ambient-status",
        EnvVar.QDRANT_STORAGE_DIR.value: "ambient-storage",
        EnvVar.QDRANT_PORT.value: "28765",
        EnvVar.HF_HUB_OFFLINE.value: "1",
        EnvVar.TRANSFORMERS_OFFLINE.value: "1",
    }
    previous = {key: os.environ.get(key) for key in inherited}
    os.environ.update(inherited)
    overrides: dict[str, str | None] = {
        EnvVar.HF_HUB_OFFLINE.value: None,
        EnvVar.TRANSFORMERS_OFFLINE.value: None,
        "VAULTSPEC_RAG_INVALID_VALUE": "entry\0failure",
    }
    try:
        with (
            pytest.raises(ValueError),
            _service_env(tmp_path / "service-env", env_overrides=overrides),
        ):
            pytest.fail("invalid environment value should fail after mutations")
        assert all(os.environ.get(key) == value for key, value in inherited.items())
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def test_service_env_duplicate_status_override_restores_original_on_entry_failure(
    tmp_path: Path,
) -> None:
    """A reserved-key override cannot replace the one ambient snapshot."""
    status_key = EnvVar.STATUS_DIR.value
    original = os.environ.get(status_key)
    os.environ[status_key] = "ambient-status-before-duplicate"
    try:
        overrides = {
            status_key: str(tmp_path / "override-status"),
            "VAULTSPEC_RAG_INVALID_VALUE": "entry\0failure",
        }
        with (
            pytest.raises(ValueError),
            _service_env(tmp_path / "reserved-status", env_overrides=overrides),
        ):
            pytest.fail("invalid environment value should fail after mutations")
        assert os.environ.get(status_key) == "ambient-status-before-duplicate"
    finally:
        if original is None:
            os.environ.pop(status_key, None)
        else:
            os.environ[status_key] = original


def test_offline_verification_omits_disabled_reranker_marker(
    tmp_path: Path,
) -> None:
    """Effective disabled-reranker config requires only the dense marker."""
    log_path = tmp_path / "service.log"
    log_path.write_text("EmbeddingModel cache-only mode: True\n", encoding="utf-8")
    with _service_env(
        tmp_path / "service-env",
        env_overrides={EnvVar.RERANKER_ENABLED.value: "0"},
    ):
        assert configured_service_model_ids() == (
            "Qwen/Qwen3-Embedding-0.6B",
            "naver/splade-v3",
        )
        detail = _verify_offline_service_startup(log_path, [])

    assert "EmbeddingModel cache-only mode: True" in detail
    assert "(cache-only=True)" not in detail


def test_persistent_metadata_failure_cannot_hang_model_fixture(
    tmp_path: Path,
) -> None:
    """A retrying real endpoint is cut off by the fixture-local process deadline."""
    deadline = 1.5
    cache_dir = tmp_path / "hf-cache"
    _write_incomplete_hf_cache(
        cache_dir,
        model_id="vaultspec-regression/unavailable-model",
    )
    assert not models_are_cached(
        ("vaultspec-regression/unavailable-model",),
        cache_dir=cache_dir,
    )
    with _gateway_timeout_endpoint(response_delay_seconds=30) as endpoint:
        started = time.monotonic()
        with pytest.raises(RuntimeError) as caught:
            ensure_model_snapshots(
                ("vaultspec-regression/unavailable-model",),
                timeout_seconds=deadline,
                cache_dir=cache_dir,
                endpoint=endpoint,
            )
        elapsed = time.monotonic() - started

    message = str(caught.value)
    assert elapsed < 10
    assert "exceeded 1.500s" in message
    assert "vaultspec-regression/unavailable-model" in message
    assert endpoint in message
    assert "/api/models/vaultspec-regression/unavailable-model/revision/main" in message


def test_worker_process_creation_is_inside_whole_operation_deadline() -> None:
    """A real worker spawned after work expiry is terminated inside the total bound."""
    token = f"vaultspec-model-deadline-{uuid.uuid4().hex}"
    command = [
        sys.executable,
        "-c",
        "import time; time.sleep(60)",
        token,
    ]
    started = time.monotonic()
    # Assert the whole-operation-deadline invariant, not the specific branch:
    # whether the deadline trips during process creation or during the worker
    # wait depends on how fast Popen returns relative to the sub-deadline, so
    # both messages are legitimate and share the "whole-operation deadline"
    # phrasing. Binding to one branch would flake on the Popen-timing race.
    with pytest.raises(RuntimeError, match="whole-operation deadline"):
        run_bounded_process(
            command,
            timeout_seconds=0.001,
            operation="deadline regression worker",
            context=token,
        )
    assert time.monotonic() - started < 0.500

    import psutil

    matching = [
        process.pid
        for process in psutil.process_iter(["cmdline"])
        if token
        in [str(arg) for arg in cast("list[object]", process.info.get("cmdline") or [])]
    ]
    assert matching == []


def test_live_service_repair_failure_uses_shared_startup_envelope(
    tmp_path: Path,
) -> None:
    """Real repair timeout retains exact stage, budget, endpoint, and log state."""
    model_id = "vaultspec-regression/startup-envelope-model"
    with _gateway_timeout_endpoint(response_delay_seconds=30) as endpoint:
        started = time.monotonic()
        with (
            _service_env(
                tmp_path / "outer-env",
                env_overrides={
                    EnvVar.HF_ENDPOINT.value: endpoint,
                    EnvVar.HF_HOME.value: str(tmp_path / "hf-cache"),
                },
            ),
            pytest.raises(AssertionError) as caught,
            _live_service_context(
                tmp_path / "service",
                startup_budget=0.700,
                model_ids=(model_id,),
            ),
        ):
            pytest.fail("real delayed model repair should exhaust startup")
        elapsed = time.monotonic() - started

    message = str(caught.value)
    assert elapsed < 1.250
    assert "stage=model acquisition" in message
    assert "deadline=0.700s" in message
    assert "remaining=" in message
    assert model_id in message
    assert endpoint in message
    assert "worker output tail" in message
    assert "Service output:" in message


def test_startup_load_multiplier_only_widens_the_default_envelope() -> None:
    """Load scaling grows the default envelope, never shrinks it or an override."""
    multiplier = _startup_load_multiplier()
    assert 1.0 <= multiplier <= _MAX_STARTUP_LOAD_MULTIPLIER

    # An explicit startup_budget is the exact envelope - the timeout-behaviour
    # tests depend on it - so it is never load-scaled.
    assert _resolve_startup_budget(0.700) == 0.700

    # The default is load-scaled and can only grow (floor 1.0), bounded by the
    # cap so a runaway load signal cannot inflate the hang-guard without end.
    default = _resolve_startup_budget(None)
    base = model_setup_timeout_seconds()
    assert base <= default <= base * _MAX_STARTUP_LOAD_MULTIPLIER


def _write_incomplete_hf_cache(cache_dir: Path, *, model_id: str) -> None:
    """Materialize a real config-only Hugging Face cache interrupted before weights."""
    owner, name = model_id.split("/", maxsplit=1)
    repo_cache = cache_dir / f"models--{owner}--{name}"
    revision = "0123456789abcdef0123456789abcdef01234567"
    snapshot = repo_cache / "snapshots" / revision
    snapshot.mkdir(parents=True)
    (repo_cache / "refs").mkdir()
    (repo_cache / "refs" / "main").write_text(revision, encoding="utf-8")
    (snapshot / "config.json").write_text("{}\n", encoding="utf-8")
    (snapshot / "tokenizer.json").write_text("{}\n", encoding="utf-8")
    (snapshot / "model-00001-of-00002.safetensors").write_bytes(b"partial")
    (snapshot / "model.safetensors.index.json").write_text(
        json.dumps(
            {
                "weight_map": {
                    "layer.0": "model-00001-of-00002.safetensors",
                    "layer.1": "model-00002-of-00002.safetensors",
                },
            },
        ),
        encoding="utf-8",
    )


def test_model_setup_failure_retains_final_url_and_response(tmp_path: Path) -> None:
    """An HTTP failure preserves the real final metadata URL and response."""
    with (
        _gateway_timeout_endpoint(response_delay_seconds=0) as endpoint,
        pytest.raises(RuntimeError) as caught,
    ):
        ensure_model_snapshots(
            ("vaultspec-regression/unavailable-model",),
            timeout_seconds=10,
            cache_dir=tmp_path / "hf-cache",
            endpoint=endpoint,
        )

    message = str(caught.value)
    assert "504" in message
    assert "/api/models/vaultspec-regression/unavailable-model" in message

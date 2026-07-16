"""Real-process regressions for bounded model fixture acquisition."""

from __future__ import annotations

import contextlib
import http.server
import json
import os
import threading
import time
from typing import TYPE_CHECKING

import pytest

from ..config import EnvVar
from ._model_setup import (
    configured_service_model_ids,
    ensure_model_snapshots,
    models_are_cached,
)
from .integration._helpers import _service_env
from .integration.conftest import _verify_offline_service_startup

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
        "INVALID\0ENV": "entry failure",
    }
    try:
        with (
            pytest.raises(ValueError),
            _service_env(tmp_path / "service-env", env_overrides=overrides),
        ):
            pytest.fail("invalid environment key should fail during context entry")
        assert all(os.environ.get(key) == value for key, value in inherited.items())
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


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

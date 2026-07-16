"""Real-process regressions for bounded model fixture acquisition."""

from __future__ import annotations

import contextlib
import http.server
import json
import threading
import time
from typing import TYPE_CHECKING

import pytest

from ._model_setup import ensure_model_snapshots, models_are_cached

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path


class _PersistentGatewayTimeout(http.server.BaseHTTPRequestHandler):
    """Delay if requested, then return a real HTTP 504."""

    response_delay_seconds = 0.0

    def do_HEAD(self) -> None:
        self._gateway_timeout()

    def do_GET(self) -> None:
        self._gateway_timeout()

    def _gateway_timeout(self) -> None:
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


@contextlib.contextmanager
def _gateway_timeout_endpoint(*, response_delay_seconds: float) -> Generator[str]:
    """Serve persistent metadata failures on a real loopback HTTP endpoint."""
    _PersistentGatewayTimeout.response_delay_seconds = response_delay_seconds
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

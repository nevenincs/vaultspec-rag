"""Guard tests for the managed qdrant child's credential.

The child binds loopback TCP, which every local account can reach, so the only
thing between another user and the collections is the key the child demands.
These tests pin the four places that protection can silently come apart: the
key reaching the child, the published copy being readable by other accounts,
the key being handed to an endpoint that is not the managed child, and a
server that is up but not asking for the key being taken as healthy.

No mocks: the published file is a real file whose permissions are read back,
and the data-plane probe talks to a real HTTP server on a real loopback port.
"""

from __future__ import annotations

import contextlib
import json
import logging
import sys
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import TYPE_CHECKING, NamedTuple

import pytest

from .._qdrant_server_client import open_server_client
from ..config._types import EnvVar
from ..qdrant_runtime._credential import (
    data_plane_auth_fault,
    generate_api_key,
    is_managed_endpoint,
    read_managed_api_key,
    server_api_key,
    write_managed_api_key,
)
from ..qdrant_runtime._supervise import QdrantSupervisor
from ._fake_qdrant_binary import FAKE_SERVER, fake_qdrant_binary, unpinned
from ._http_stubs import QuietHandler
from ._ports import free_loopback_port
from ._private_files import assert_private_file
from .conftest import managed_env

if TYPE_CHECKING:
    from collections.abc import Generator

pytestmark = [pytest.mark.unit]

_KEY_VARIABLE = "QDRANT__SERVICE__API_KEY"
#: A 256-bit key in URL-safe base64, unpadded.
_GENERATED_KEY_CHARS = 43
_SUPERVISE_LOGGER = "vaultspec_rag.qdrant_runtime._supervise"

_COLLECTIONS_BODY = json.dumps(
    {"result": {"collections": []}, "status": "ok", "time": 0.0}
).encode()


class _Served(NamedTuple):
    """A running data-plane stand-in."""

    url: str
    port: int
    #: Set once the root version route has answered. The client probes it on a
    #: thread of its own, so a test that builds a client waits on this before
    #: the server goes away rather than racing that probe.
    version_probed: threading.Event


def _handler(
    accepted_key: str | None, anonymous_status: int, version_probed: threading.Event
) -> type[QuietHandler]:
    """Build a server that answers a collection listing by one fixed policy.

    Args:
        accepted_key: The key answered with 200, or ``None`` to accept none.
        anonymous_status: The status for every request not carrying that key.
        version_probed: Set after the root version route answers.
    """

    class _DataPlane(QuietHandler):
        def do_GET(self) -> None:
            if self.path == "/":
                self._answer(200, b'{"title":"qdrant","version":"1.19.0"}')
                version_probed.set()
            elif self.path != "/collections":
                self._answer(404, b"")
            elif accepted_key and self.headers.get("api-key") == accepted_key:
                self._answer(200, _COLLECTIONS_BODY)
            else:
                self._answer(anonymous_status, _COLLECTIONS_BODY)

        def _answer(self, status: int, body: bytes) -> None:
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return _DataPlane


@contextlib.contextmanager
def _data_plane(
    accepted_key: str | None, *, anonymous_status: int
) -> Generator[_Served]:
    """Serve one data-plane policy on a loopback port for the block."""
    version_probed = threading.Event()
    server = ThreadingHTTPServer(
        ("127.0.0.1", 0), _handler(accepted_key, anonymous_status, version_probed)
    )
    port = int(server.server_address[1])
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield _Served(f"http://127.0.0.1:{port}", port, version_probed)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=10.0)


@contextlib.contextmanager
def _managed_config(
    storage: Path, port: int, *, configured_key: str | None = None
) -> Generator[None]:
    """Make *port* and *storage* the managed endpoint, with no operator URL."""
    with managed_env(
        **{
            EnvVar.QDRANT_PORT.value: str(port),
            EnvVar.QDRANT_STORAGE_DIR.value: str(storage),
            EnvVar.QDRANT_URL.value: None,
            EnvVar.QDRANT_API_KEY.value: configured_key,
        }
    ):
        yield


class TestTheChildDemandsAKey:
    def test_child_environment_carries_a_generated_key(self, tmp_path: Path) -> None:
        # Drop the key from the child environment and the server starts with
        # no credential at all: this is the reported defect. `.get` so the
        # failure lands on this assertion rather than on a lookup.
        first = QdrantSupervisor(
            unpinned(Path("qdrant")),
            http_port=6333,
            storage_dir=tmp_path / "a" / "storage",
        )
        second = QdrantSupervisor(
            unpinned(Path("qdrant")),
            http_port=6333,
            storage_dir=tmp_path / "b" / "storage",
        )
        first_key = first._child_env().get(_KEY_VARIABLE, "")
        second_key = second._child_env().get(_KEY_VARIABLE, "")

        assert len(first_key) >= _GENERATED_KEY_CHARS
        # Per instance: a key shared between supervisors would outlive the
        # server it was issued for.
        assert first_key != second_key
        # Stable for one supervisor: stores hold clients across a restart.
        assert first._child_env().get(_KEY_VARIABLE) == first_key

    def test_operator_key_is_adopted_instead_of_generated(self, tmp_path: Path) -> None:
        supervisor = QdrantSupervisor(
            unpinned(Path("qdrant")),
            http_port=6333,
            storage_dir=tmp_path / "storage",
            api_key="operator-chosen-key",
        )
        assert supervisor._child_env().get(_KEY_VARIABLE) == "operator-chosen-key"

    def test_spawn_publishes_the_key_the_child_was_given(self, tmp_path: Path) -> None:
        # The interpreter stands in for the binary: with no arguments and no
        # stdin it exits at once, which is all a publication test needs. Move
        # the publication after the spawn, or drop it, and the file is absent
        # or stale when the child is already listening.
        storage = tmp_path / "qdrant" / "storage"
        supervisor = QdrantSupervisor(
            # Resolved: an interpreter reached through a link is refused, as
            # any operator-named binary reached through a link is.
            unpinned(Path(sys.executable).resolve()),
            http_port=free_loopback_port(),
            storage_dir=storage,
        )
        supervisor.spawn()
        try:
            published = read_managed_api_key(storage)
        finally:
            assert supervisor.stop(timeout=10.0)

        assert published is not None
        assert published == supervisor._child_env().get(_KEY_VARIABLE)


class TestThePublishedKeyIsOwnerOnly:
    def test_credential_round_trips_and_only_the_owner_can_read_it(
        self, tmp_path: Path
    ) -> None:
        # Publish through the plain writer instead of the private one and the
        # permission assertion fails: every local account could then read the
        # key the server demands, which is the defect with one more step.
        storage = tmp_path / "qdrant" / "storage"
        api_key = generate_api_key()

        path = write_managed_api_key(storage, api_key)

        assert path.parent == storage.parent
        assert read_managed_api_key(storage) == api_key
        assert_private_file(path)
        # No temp sibling left holding a second copy of the secret.
        assert list(path.parent.iterdir()) == [path]

    def test_replacing_a_readable_file_leaves_it_owner_only(
        self, tmp_path: Path
    ) -> None:
        storage = tmp_path / "qdrant" / "storage"
        storage.parent.mkdir(parents=True)
        (storage.parent / "credential.json").write_text("{}", encoding="utf-8")

        path = write_managed_api_key(storage, generate_api_key())

        assert_private_file(path)

    @pytest.mark.parametrize("content", ["", "not json", "[]", "{}", '{"api_key": 7}'])
    def test_unusable_record_reads_as_no_credential(
        self, tmp_path: Path, content: str
    ) -> None:
        storage = tmp_path / "qdrant" / "storage"
        storage.parent.mkdir(parents=True)
        (storage.parent / "credential.json").write_text(content, encoding="utf-8")

        assert read_managed_api_key(storage) is None

    def test_absent_record_reads_as_no_credential(self, tmp_path: Path) -> None:
        assert read_managed_api_key(tmp_path / "qdrant" / "storage") is None


class TestTheKeyGoesToTheManagedChildOnly:
    def test_managed_endpoint_receives_the_published_key(self, tmp_path: Path) -> None:
        storage = tmp_path / "qdrant" / "storage"
        port = free_loopback_port()
        write_managed_api_key(storage, "managed-key")
        with _managed_config(storage, port):
            assert server_api_key(f"http://127.0.0.1:{port}") == "managed-key"
            assert server_api_key(f"http://127.0.0.1:{port}/") == "managed-key"

    @pytest.mark.parametrize(
        "template",
        [
            # Another host at the managed port.
            "http://qdrant.internal:{port}",
            # A name: resolved by something this process does not control.
            "http://localhost:{port}",
            "http://[::1]:{port}",
            # Another port on this host is somebody else's server.
            "http://127.0.0.1:{other}",
            "https://127.0.0.1:{port}",
            "http://127.0.0.1:{port}/prefix",
            "http://127.0.0.1:{port}?x=1",
            "http://127.0.0.1:notaport",
        ],
    )
    def test_any_other_endpoint_is_never_sent_the_managed_key(
        self, tmp_path: Path, template: str
    ) -> None:
        # Loosen the endpoint test - drop the host, the port or the scheme
        # comparison - and the managed key is released to whatever answers
        # there. The key exists on disk for every case, so only the endpoint
        # test stands between it and the URL.
        storage = tmp_path / "qdrant" / "storage"
        port = free_loopback_port()
        url = template.format(port=port, other=port + 1)
        write_managed_api_key(storage, "managed-key")
        with _managed_config(storage, port):
            assert is_managed_endpoint(url) is False
            assert server_api_key(url) is None

    def test_configured_key_wins_for_every_endpoint(self, tmp_path: Path) -> None:
        storage = tmp_path / "qdrant" / "storage"
        port = free_loopback_port()
        write_managed_api_key(storage, "managed-key")
        with _managed_config(storage, port, configured_key="operator-key"):
            assert server_api_key("http://qdrant.internal:6333") == "operator-key"
            assert server_api_key(f"http://127.0.0.1:{port}") == "operator-key"

    def test_managed_endpoint_without_a_published_key_sends_none(
        self, tmp_path: Path
    ) -> None:
        port = free_loopback_port()
        with _managed_config(tmp_path / "qdrant" / "storage", port):
            assert server_api_key(f"http://127.0.0.1:{port}") is None


class TestAReadyServerMustBeAskingForTheKey:
    def test_enforcing_server_is_accepted(self) -> None:
        with _data_plane("the-key", anonymous_status=401) as served:
            assert data_plane_auth_fault(served.url, "the-key") is None

    def test_server_answering_anonymous_requests_is_a_fault(self) -> None:
        # The branch that matters: delete the anonymous check and a server
        # with no credential at all reads as protected, because it accepts
        # the key too. Each fault below names its own branch, so one cannot
        # stand in for another.
        with _data_plane("the-key", anonymous_status=200) as served:
            fault = data_plane_auth_fault(served.url, "the-key")
        assert fault == "it accepts data requests that carry no credential"

    def test_server_refusing_the_key_is_a_fault(self) -> None:
        with _data_plane("another-key", anonymous_status=401) as served:
            fault = data_plane_auth_fault(served.url, "the-key")
        assert fault == "it answered the managed credential with HTTP 401"

    def test_anonymous_answer_that_is_not_a_refusal_is_a_fault(self) -> None:
        with _data_plane("the-key", anonymous_status=500) as served:
            fault = data_plane_auth_fault(served.url, "the-key")
        assert fault == (
            "an anonymous data request was answered with HTTP 500 instead of "
            "a credential refusal"
        )

    def test_silent_endpoint_is_a_fault(self) -> None:
        url = f"http://127.0.0.1:{free_loopback_port()}"
        fault = data_plane_auth_fault(url, "the-key", timeout=0.5)
        assert fault == (
            "an anonymous data request was answered with nothing instead of "
            "a credential refusal"
        )

    def test_fault_never_repeats_the_key(self) -> None:
        with _data_plane("another-key", anonymous_status=401) as served:
            fault = data_plane_auth_fault(served.url, "secret-key-value")
        assert fault is not None
        assert "secret-key-value" not in fault


class TestEveryServerClientPresentsTheKey:
    def test_constructor_authenticates_to_the_managed_endpoint(
        self, tmp_path: Path, recwarn: pytest.WarningsRecorder
    ) -> None:
        # The server refuses any request without the published key, so a
        # listing that succeeds proves the constructor resolved and sent it.
        # Build the client from the URL alone and this raises on the 401.
        storage = tmp_path / "qdrant" / "storage"
        with _data_plane("managed-key", anonymous_status=401) as served:
            write_managed_api_key(storage, "managed-key")
            with _managed_config(storage, served.port):
                client = open_server_client(served.url, timeout=5)
                try:
                    assert client.get_collections().collections == []
                    assert served.version_probed.wait(10.0)
                finally:
                    client.close()
        # Loopback plaintext is not an exposure; the client's warning about it
        # would otherwise fire on every store open.
        assert not [
            str(warning.message)
            for warning in recwarn
            if "insecure connection" in str(warning.message)
        ]


class TestTheSupervisorRefusesAnUnprotectedChild:
    """Readiness alone never lets a child serve the store."""

    def test_start_stops_a_ready_child_that_asks_for_no_key(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        # This child is ready and answers everything, the shape of a binary
        # that ignores the key setting. Remove the post-readiness check from
        # start() and it returns normally, with the store open to every local
        # account and every health signal reading normal.
        supervisor = QdrantSupervisor(
            unpinned(fake_qdrant_binary(tmp_path, FAKE_SERVER.format(enforce=False))),
            http_port=free_loopback_port(),
            storage_dir=tmp_path / "qdrant" / "storage",
            log_path=tmp_path / "qdrant.log",
        )
        try:
            with (
                caplog.at_level(logging.ERROR, logger=_SUPERVISE_LOGGER),
                pytest.raises(RuntimeError) as refused,
            ):
                supervisor.start(timeout=30.0)
            stopped_by_start = not supervisor.is_alive()
        finally:
            assert supervisor.stop(timeout=10.0)

        # The exact branch: a readiness timeout raises RuntimeError too.
        assert "it accepts data requests that carry no credential" in str(refused.value)
        assert "failed to become ready" not in str(refused.value)
        assert stopped_by_start, "the unprotected child was left running"
        assert "stopping it" in caplog.text

    def test_start_accepts_a_child_that_demands_the_key_it_was_given(
        self, tmp_path: Path
    ) -> None:
        # The child refuses every data request that does not carry the key
        # from its own environment. The start succeeds only if the supervisor
        # presents that same key, so this fails if the key never reaches the
        # child or the supervisor probes with a different one.
        supervisor = QdrantSupervisor(
            unpinned(fake_qdrant_binary(tmp_path, FAKE_SERVER.format(enforce=True))),
            http_port=free_loopback_port(),
            storage_dir=tmp_path / "qdrant" / "storage",
            log_path=tmp_path / "qdrant.log",
        )
        try:
            supervisor.start(timeout=30.0)
            assert supervisor.is_alive()
            # Other clients find the same key where the child's owner put it.
            published = read_managed_api_key(supervisor.storage_dir)
            assert published is not None
            assert data_plane_auth_fault(supervisor.url, published) is None
        finally:
            assert supervisor.stop(timeout=10.0)

    def test_restart_refuses_a_child_that_asks_for_no_key(self, tmp_path: Path) -> None:
        # The heartbeat's restart is a second way to a serving child, and must
        # not be a way around the check the first start applies. Remove the
        # check from restart() and it reports this child restarted and leaves
        # it running.
        supervisor = QdrantSupervisor(
            unpinned(fake_qdrant_binary(tmp_path, FAKE_SERVER.format(enforce=False))),
            http_port=free_loopback_port(),
            storage_dir=tmp_path / "qdrant" / "storage",
            log_path=tmp_path / "qdrant.log",
        )
        try:
            restarted = supervisor.restart(timeout=30.0)
            alive = supervisor.is_alive()
        finally:
            assert supervisor.stop(timeout=10.0)

        assert restarted is False
        assert alive is False

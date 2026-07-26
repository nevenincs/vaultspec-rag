"""The client/service release-compatibility signal, end to end on one host.

A client and the daemon it drives are separate installs that drift apart, and
nothing in the wire surface used to say so. These tests cover the whole signal:
the daemon publishes its release, one module classifies it, and each surface
turns an incompatible verdict into something an operator can act on.

The daemon side is a real local HTTP server answering ``/health`` - the same
device the existing start-verb tests use - so the CLI's own transport, envelope
and exit-code paths run unmodified. No client is patched to believe a version it
did not read.
"""

from __future__ import annotations

import http.server
import json
import os
import threading
from typing import TYPE_CHECKING, Any

import pytest
from typer.testing import CliRunner

from ..cli._app import app
from ..serviceclient._compat import (
    SERVICE_VERSION_FIELD,
    VERSION_ERROR_MISMATCH,
    VERSION_ERROR_UNREPORTED,
    VERSION_STATE_MATCH,
    VERSION_STATE_MISMATCH,
    VERSION_STATE_UNREPORTED,
    classify_service_version,
    local_package_version,
)
from ._http_stubs import QuietHandler

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping

pytestmark = [pytest.mark.unit]

runner = CliRunner()

#: A release string that is deliberately not this install's, used wherever a
#: foreign daemon has to be represented.
_FOREIGN_RELEASE = "0.0.1-foreign"


@pytest.fixture
def health_service() -> Iterator[Any]:
    """Serve one caller-chosen ``/health`` body from a real loopback server.

    Yields a setter; the port is read off the returned object. A real server
    rather than a patched transport, so the CLI exercises its own HTTP client,
    its own envelope construction, and its own exit codes.
    """

    class _State:
        body: bytes = b"{}"
        port: int = 0

    state = _State()

    class _Handler(QuietHandler):
        def do_GET(self) -> None:
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(state.body)))
            self.end_headers()
            self.wfile.write(state.body)

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    state.port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield state
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _publish_health(state: Any, **fields: object) -> None:
    """Set the served ``/health`` body and record the matching discovery file."""
    from ..cli._service_status import _write_service_status
    from ..serviceclient._discovery import _status_file

    payload: dict[str, object] = {
        "status": "ready",
        "service_token": "tok-live",
        **fields,
    }
    state.body = json.dumps(payload).encode("utf-8")
    _write_service_status(os.getpid(), state.port)
    status_path = _status_file()
    document = json.loads(status_path.read_text(encoding="utf-8"))
    document["service_token"] = "tok-live"
    status_path.write_text(json.dumps(document), encoding="utf-8")


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------


def test_matching_release_is_the_only_compatible_verdict() -> None:
    """The same release on both sides is compatible; nothing else is."""
    verdict = classify_service_version({SERVICE_VERSION_FIELD: local_package_version()})

    assert verdict.state == VERSION_STATE_MATCH
    assert verdict.is_compatible
    assert verdict.error_code() is None
    assert verdict.remediation() == ()


def test_different_release_is_a_mismatch_naming_both_sides() -> None:
    """A mismatch carries both versions, so the operator sees the actual drift."""
    verdict = classify_service_version({SERVICE_VERSION_FIELD: _FOREIGN_RELEASE})

    assert verdict.state == VERSION_STATE_MISMATCH
    assert not verdict.is_compatible
    assert verdict.error_code() == VERSION_ERROR_MISMATCH
    assert verdict.service_version == _FOREIGN_RELEASE
    assert verdict.client_version == local_package_version()
    assert verdict.reason().count(_FOREIGN_RELEASE) == 1
    assert local_package_version() in verdict.reason()


@pytest.mark.parametrize(
    "payload",
    [
        pytest.param(None, id="no-payload"),
        pytest.param({}, id="field-absent"),
        pytest.param({SERVICE_VERSION_FIELD: ""}, id="field-blank"),
        pytest.param({SERVICE_VERSION_FIELD: "   "}, id="field-whitespace"),
        pytest.param({SERVICE_VERSION_FIELD: 3}, id="field-not-a-string"),
    ],
)
def test_unreadable_release_is_never_a_silent_pass(
    payload: Mapping[str, Any] | None,
) -> None:
    """An unconfirmable version fails closed, as the Qdrant attach check does.

    Asserted on the distinct ``unreported`` state rather than only on
    ``is_compatible``: an operator told "the versions differ" when in fact none
    was reported would go looking for the wrong thing.
    """
    verdict = classify_service_version(payload)

    assert verdict.state == VERSION_STATE_UNREPORTED
    assert not verdict.is_compatible
    assert verdict.error_code() == VERSION_ERROR_UNREPORTED
    assert verdict.service_version is None


def test_verdict_dict_carries_every_field_a_surface_renders() -> None:
    """The envelope view is complete, so no surface re-derives the comparison."""
    verdict = classify_service_version({SERVICE_VERSION_FIELD: _FOREIGN_RELEASE})

    assert verdict.to_dict() == {
        "state": VERSION_STATE_MISMATCH,
        "client_version": local_package_version(),
        "service_version": _FOREIGN_RELEASE,
        "compatible": False,
    }


# ---------------------------------------------------------------------------
# Publication
# ---------------------------------------------------------------------------


def test_readiness_report_publishes_this_installs_release() -> None:
    """``/readiness`` carries the release, so a direct consumer can gate on it."""
    from .._readiness import compute_readiness

    payload = compute_readiness().to_dict()

    assert payload[SERVICE_VERSION_FIELD] == local_package_version()
    assert classify_service_version(payload).is_compatible


@pytest.mark.usefixtures("isolated_singleton_dirs")
def test_the_cli_parent_stamps_the_release_into_the_discovery_file() -> None:
    """The spawn-time write records the release that launched the daemon."""
    from ..cli._service_status import _write_service_status
    from ..serviceclient._discovery import _read_service_status

    _write_service_status(os.getpid(), 1)
    status = _read_service_status()

    assert status is not None
    assert status[SERVICE_VERSION_FIELD] == local_package_version()


# ---------------------------------------------------------------------------
# The start verb: an incompatible daemon is a failure, not `already_running`
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("isolated_singleton_dirs")
def test_start_refuses_to_report_already_running_for_a_foreign_release(
    health_service: Any,
) -> None:
    """The load-bearing gate: attaching to another install is not success.

    Asserted on the exact error code, not merely on a non-zero exit, because
    start has several failure branches and a shared assertion would be
    satisfied by whichever fired.
    """
    _publish_health(health_service, **{SERVICE_VERSION_FIELD: _FOREIGN_RELEASE})

    result = runner.invoke(app, ["server", "start", "--json"])

    assert result.exit_code == 1
    envelope = json.loads(result.stdout)
    assert envelope["ok"] is False
    assert envelope["error"] == VERSION_ERROR_MISMATCH
    assert envelope["data"]["version"]["service_version"] == _FOREIGN_RELEASE
    assert envelope["data"]["version"]["client_version"] == local_package_version()


@pytest.mark.usefixtures("isolated_singleton_dirs")
def test_start_refuses_a_daemon_that_reports_no_release(
    health_service: Any,
) -> None:
    """A daemon predating version reporting gets its own code, not the mismatch one."""
    _publish_health(health_service)

    result = runner.invoke(app, ["server", "start", "--json"])

    assert result.exit_code == 1
    envelope = json.loads(result.stdout)
    assert envelope["ok"] is False
    assert envelope["error"] == VERSION_ERROR_UNREPORTED


@pytest.mark.usefixtures("isolated_singleton_dirs")
def test_start_emits_exactly_one_envelope_on_the_refusal_path(
    health_service: Any,
) -> None:
    """One structured document on stdout, never zero and never two.

    A broker parses this stream. Two envelopes and a trailing human line are
    both protocol violations, so the whole of stdout is parsed as one document
    rather than searched for a substring.
    """
    _publish_health(health_service, **{SERVICE_VERSION_FIELD: _FOREIGN_RELEASE})

    result = runner.invoke(app, ["server", "start", "--json"])

    decoder = json.JSONDecoder()
    envelope, consumed = decoder.raw_decode(result.stdout.lstrip())
    assert isinstance(envelope, dict)
    assert result.stdout.lstrip()[consumed:].strip() == ""


@pytest.mark.usefixtures("isolated_singleton_dirs")
def test_start_refusal_is_non_zero_and_actionable_in_human_mode(
    health_service: Any,
) -> None:
    """Human mode fails too, and prints the one action that resolves it.

    A verb that does not reach the requested state exits non-zero in *both*
    human and JSON mode; a human-mode zero would let an operator believe their
    install is the one running.
    """
    _publish_health(health_service, **{SERVICE_VERSION_FIELD: _FOREIGN_RELEASE})

    result = runner.invoke(app, ["server", "start"])

    assert result.exit_code == 1
    assert _FOREIGN_RELEASE in result.stdout
    assert "vaultspec-rag server stop" in result.stdout


@pytest.mark.usefixtures("isolated_singleton_dirs")
def test_start_still_attaches_to_a_daemon_of_this_release(
    health_service: Any,
) -> None:
    """The gate must not break the idempotent-start contract it sits in front of.

    A same-release daemon is still the `already_running` success at exit 0, so
    a supervising broker can keep starting speculatively.
    """
    _publish_health(health_service, **{SERVICE_VERSION_FIELD: local_package_version()})

    result = runner.invoke(app, ["server", "start", "--json"])

    assert result.exit_code == 0
    envelope = json.loads(result.stdout)
    assert envelope["ok"] is True
    assert envelope["data"]["status"] == "already_running"


# ---------------------------------------------------------------------------
# The MCP surface refuses the same daemon the CLI refuses
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("isolated_singleton_dirs")
def test_mcp_tools_refuse_a_foreign_release_with_the_same_code(
    health_service: Any,
) -> None:
    """One condition, one diagnosis across both adapters.

    The MCP reads the version from the discovery file it already consults for
    the port, so this also pins that the pointer - not just ``/health`` - is a
    sufficient source for the comparison.
    """
    import asyncio

    from ..mcp._tools import search_vault

    _publish_health(health_service, **{SERVICE_VERSION_FIELD: _FOREIGN_RELEASE})
    from ..serviceclient._discovery import _status_file

    status_path = _status_file()
    document = json.loads(status_path.read_text(encoding="utf-8"))
    document[SERVICE_VERSION_FIELD] = _FOREIGN_RELEASE
    status_path.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(RuntimeError) as exc_info:
        asyncio.run(search_vault("anything"))

    message = str(exc_info.value)
    assert message.startswith(f"{VERSION_ERROR_MISMATCH}:")
    assert "vaultspec-rag server stop" in message


# ---------------------------------------------------------------------------
# The discovery schema pair the docs mandated and nothing enforced
# ---------------------------------------------------------------------------


def test_a_pointer_declaring_an_unknown_schema_is_refused() -> None:
    """An unrecognised discriminator means the other fields cannot be trusted."""
    from ..serviceclient._discovery import (
        SERVICE_DISCOVERY_SCHEMA,
        SERVICE_DISCOVERY_VERSION,
        _discovery_pair_understood,
    )

    assert _discovery_pair_understood(
        {"schema": SERVICE_DISCOVERY_SCHEMA, "version": SERVICE_DISCOVERY_VERSION}
    )
    assert not _discovery_pair_understood(
        {"schema": "something.else", "version": SERVICE_DISCOVERY_VERSION}
    )
    assert not _discovery_pair_understood(
        {"schema": SERVICE_DISCOVERY_SCHEMA, "version": SERVICE_DISCOVERY_VERSION + 1}
    )


def test_a_pointer_predating_the_discriminator_is_still_read() -> None:
    """Absent fields are the pre-discriminator case, not a refusal.

    Refusing them would strand every pointer written before the pair existed,
    which is a compatibility break dressed up as a compatibility check.
    """
    from ..serviceclient._discovery import _discovery_pair_understood

    assert _discovery_pair_understood({"pid": 1, "port": 2})


@pytest.mark.usefixtures("isolated_singleton_dirs")
def test_an_unreadable_status_file_degrades_rather_than_reads_absent() -> None:
    """A file this build cannot read must not be reported as "nothing running".

    Reporting absence would invite a caller to start a second daemon that must
    then lose the machine race, so the verdict is degraded with the reason.
    """
    from ..serviceclient._discovery import (
        DISCOVERY_REASON_POINTER_INCOMPATIBLE,
        DISCOVERY_STATE_DEGRADED,
        _status_file,
        resolve_machine_service,
    )

    _status_file().write_text(
        json.dumps(
            {
                "schema": "vaultspec.rag.service",
                "version": 999,
                "pid": os.getpid(),
                "port": 1,
            }
        ),
        encoding="utf-8",
    )

    resolution = resolve_machine_service()

    assert resolution.state == DISCOVERY_STATE_DEGRADED
    assert resolution.reason == DISCOVERY_REASON_POINTER_INCOMPATIBLE


# ---------------------------------------------------------------------------
# The doctor reports it as an actionable divergence
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("isolated_singleton_dirs")
def test_doctor_exits_non_zero_for_a_running_foreign_release() -> None:
    """A foreign daemon lifts the doctor's exit code, as a dead one does."""
    from ..cli._service_doctor import _doctor_exit_code

    compatible: dict[str, object] = {
        "present": True,
        "live": True,
        "version_compatible": True,
    }
    foreign: dict[str, object] = {
        "present": True,
        "live": True,
        "version_compatible": False,
    }

    assert _doctor_exit_code(compatible, None) == 0
    assert _doctor_exit_code(foreign, None) == 1


def test_doctor_ignores_the_release_when_no_daemon_was_observed() -> None:
    """A pre-install run has no daemon to compare, and must stay exit 0.

    ``version_compatible`` is absent rather than False there, and the gate keys
    on ``is False`` for exactly that reason.
    """
    from ..cli._service_doctor import _doctor_exit_code

    absent: dict[str, object] = {"present": False, "live": False}

    assert _doctor_exit_code(absent, None) == 0


# ---------------------------------------------------------------------------
# The CLI data-plane verbs refuse the daemon the MCP refuses
# ---------------------------------------------------------------------------


def _record_foreign_daemon(port: int) -> None:
    """Publish a discovery file naming a live daemon of another release."""
    from ..cli._service_status import _write_service_status
    from ..serviceclient._discovery import _status_file

    _write_service_status(os.getpid(), port)
    status_path = _status_file()
    document = json.loads(status_path.read_text(encoding="utf-8"))
    document[SERVICE_VERSION_FIELD] = _FOREIGN_RELEASE
    status_path.write_text(json.dumps(document), encoding="utf-8")


def test_the_data_plane_seam_pairs_the_address_with_the_verdict() -> None:
    """One seam answers both questions, so no caller can gate only one.

    The CLI shipped gating neither while the MCP gated both, because the address
    and the release were resolved at different places. Asserting the pairing is
    what keeps them from separating again.
    """
    from ..serviceclient._compat import DataPlaneService

    unusable = DataPlaneService(
        port=8766,
        version=classify_service_version({SERVICE_VERSION_FIELD: _FOREIGN_RELEASE}),
    )
    down = DataPlaneService(port=None, version=classify_service_version(None))

    assert unusable.reachable and not unusable.usable
    assert not down.reachable and not down.usable


@pytest.mark.usefixtures("isolated_singleton_dirs")
def test_cli_search_refuses_a_foreign_release_rather_than_answering(
    health_service: Any,
) -> None:
    """A CLI search must not silently answer over a foreign daemon's results.

    This was the adapter drift: the MCP refused and the CLI did not, so one
    condition had two contracts. Asserted on the exact error code the MCP
    raises, which is what pins the two adapters to one diagnosis.
    """
    _record_foreign_daemon(health_service.port)

    result = runner.invoke(app, ["search", "anything", "--json"])

    assert result.exit_code == 1
    envelope = json.loads(result.stdout)
    assert envelope["ok"] is False
    assert envelope["error"] == VERSION_ERROR_MISMATCH
    assert envelope["version"]["service_version"] == _FOREIGN_RELEASE


@pytest.mark.usefixtures("isolated_singleton_dirs")
def test_cli_search_refusal_is_actionable_in_human_mode(
    health_service: Any,
) -> None:
    """Human mode fails too, and names the one action that resolves it."""
    _record_foreign_daemon(health_service.port)

    result = runner.invoke(app, ["search", "anything"])

    assert result.exit_code == 1
    assert _FOREIGN_RELEASE in result.stdout
    assert "vaultspec-rag server stop" in result.stdout


@pytest.mark.usefixtures("isolated_singleton_dirs")
def test_cli_index_refuses_rather_than_indexing_around_a_foreign_daemon(
    health_service: Any,
) -> None:
    """Index refuses instead of falling through to the in-process path.

    Falling through would be worse than stopping: the foreign daemon still owns
    the store and the writer lock, so an in-process run would contend with a
    process this build cannot speak to.
    """
    _record_foreign_daemon(health_service.port)

    result = runner.invoke(app, ["index", "--json"])

    assert result.exit_code == 1
    envelope = json.loads(result.stdout)
    assert envelope["ok"] is False
    assert envelope["error"] == VERSION_ERROR_MISMATCH


@pytest.mark.usefixtures("isolated_singleton_dirs")
def test_stop_is_not_gated_because_it_is_the_remediation() -> None:
    """The verb that resolves the mismatch must never be blocked by it.

    A gate on `stop` would leave the operator holding a verdict they cannot act
    on. Asserted as a source property of the shared seam rather than by driving
    a daemon, because the point is that the lifecycle modules never consult it.
    """
    from pathlib import Path as _Path

    cli_dir = _Path(__file__).resolve().parent.parent / "cli"
    gated = sorted(
        module.name
        for module in cli_dir.glob("_service_*.py")
        if "resolve_data_plane_service" in module.read_text(encoding="utf-8")
    )

    assert gated == []

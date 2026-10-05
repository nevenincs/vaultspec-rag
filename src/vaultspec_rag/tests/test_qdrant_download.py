"""The managed Qdrant download, driven against real loopback HTTPS sources.

Where the bytes come from is configuration; which bytes are accepted is not.
These tests cover the first half: the release base and the redirect hosts are
read from settings, the source must be HTTPS, and every redirect hop is held
to HTTPS and to the hosts the caller allowed. The stand-in sources speak real
TLS, so the request, the redirect handling and the certificate check are the
shipped ones. No test here reaches the public network.
"""

from __future__ import annotations

import io
import threading
import time
import urllib.error
from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest

from .._sync_vocabulary import ProvisionAction
from ..config._types import EnvVar
from ..qdrant_runtime._constants import QDRANT_SERVER_VERSION
from ..qdrant_runtime._provision import download_https, provision
from ..qdrant_runtime._resolve import (
    asset_for_platform,
    binary_filename,
    qdrant_bin_dir,
)
from ._loopback_tls import (
    LOOPBACK_HOST,
    LoopbackSources,
    send_bytes,
    send_redirect,
    send_truncated,
    trusted_loopback_sources,
)
from .conftest import managed_env

if TYPE_CHECKING:
    from collections.abc import Callable, Generator
    from pathlib import Path

    from ._http_stubs import QuietHandler

pytestmark = [pytest.mark.unit]

_PAYLOAD = b"stand-in archive bytes, not a release"

#: A redirect set that lists the stand-ins' address, and one that does not.
_LOOPBACK_ALLOWED = frozenset({LOOPBACK_HOST})
_LOOPBACK_NOT_ALLOWED = frozenset({"storage.example"})


@pytest.fixture
def sources(tmp_path: Path) -> Generator[LoopbackSources]:
    with trusted_loopback_sources(tmp_path / "tls") as started:
        yield started


class TestSourceScheme:
    def test_a_source_that_is_not_https_is_refused_without_a_request(
        self, sources: LoopbackSources
    ) -> None:
        """A plain-HTTP source is refused before anything is sent to it.

        Mutation: removed the scheme check at the top of ``download_https``.
        Observed ``DID NOT RAISE URLError``. Restored; passes.
        """
        plain = sources.serve(
            lambda handler: send_bytes(handler, _PAYLOAD),
            tls=False,
        )
        out = io.BytesIO()

        with pytest.raises(urllib.error.URLError, match="non-HTTPS download URL"):
            download_https(
                plain.url("/asset.bin"), out, redirect_hosts=_LOOPBACK_ALLOWED
            )

        assert plain.requests == []
        assert out.getvalue() == b""


class TestRedirectHosts:
    """Each redirect hop must stay HTTPS and inside the hosts the caller gave."""

    def test_the_source_host_is_contacted_though_the_set_does_not_list_it(
        self, sources: LoopbackSources
    ) -> None:
        """The set bounds redirects only; the source is the caller's choice.

        A caller whose source is one host and whose redirect targets are
        others - a release API in front of an asset store - depends on this.

        Mutation: restored a check in ``download_https`` that refused a source
        whose host is outside the set. Observed the ``URLError`` it raised
        escape the call. Restored; passes.
        """
        source = sources.serve(lambda handler: send_bytes(handler, _PAYLOAD))
        out = io.BytesIO()

        download_https(source.url("/latest"), out, redirect_hosts=_LOOPBACK_NOT_ALLOWED)

        assert source.requests == ["/latest"]
        assert out.getvalue() == _PAYLOAD

    def test_a_redirect_onto_a_listed_host_is_followed(
        self, sources: LoopbackSources
    ) -> None:
        storage = sources.serve(lambda handler: send_bytes(handler, _PAYLOAD))
        origin = sources.serve(
            lambda handler: send_redirect(handler, storage.url("/blob"))
        )
        out = io.BytesIO()

        download_https(origin.url("/asset.bin"), out, redirect_hosts=_LOOPBACK_ALLOWED)

        assert origin.requests == ["/asset.bin"]
        assert storage.requests == ["/blob"]
        assert out.getvalue() == _PAYLOAD

    def test_a_redirect_onto_an_unlisted_host_is_refused_unfollowed(
        self, sources: LoopbackSources
    ) -> None:
        """A hop to a host outside the set is refused, the source's own included.

        Both stand-ins share the loopback address, and the set does not list
        it. The first request is allowed because that host is the chosen
        source; the redirect back to the same host is not, because a redirect
        target earns no trust from the source that issued it.

        Mutation: made the host test in ``_HostPinnedRedirect`` always pass.
        Observed ``DID NOT RAISE URLError``. Restored; passes.
        """
        storage = sources.serve(lambda handler: send_bytes(handler, _PAYLOAD))
        origin = sources.serve(
            lambda handler: send_redirect(handler, storage.url("/blob"))
        )
        out = io.BytesIO()

        with pytest.raises(
            urllib.error.URLError,
            match=f"disallowed host '{LOOPBACK_HOST}'",
        ):
            download_https(
                origin.url("/asset.bin"),
                out,
                redirect_hosts=_LOOPBACK_NOT_ALLOWED,
            )

        assert origin.requests == ["/asset.bin"]
        assert storage.requests == []
        assert out.getvalue() == b""

    def test_a_redirect_that_leaves_https_is_refused_unfollowed(
        self, sources: LoopbackSources
    ) -> None:
        """A downgrade is refused even onto a host the set lists.

        Mutation: removed the scheme test in ``_HostPinnedRedirect``. Observed
        ``DID NOT RAISE URLError``. Restored; passes.
        """
        plain = sources.serve(
            lambda handler: send_bytes(handler, _PAYLOAD),
            tls=False,
        )
        origin = sources.serve(
            lambda handler: send_redirect(handler, plain.url("/blob"))
        )
        out = io.BytesIO()

        with pytest.raises(urllib.error.URLError, match="non-HTTPS URL"):
            download_https(
                origin.url("/asset.bin"), out, redirect_hosts=_LOOPBACK_ALLOWED
            )

        assert origin.requests == ["/asset.bin"]
        assert plain.requests == []
        assert out.getvalue() == b""


class TestReleaseBaseSetting:
    """The download URL is the configured base plus the upstream suffix."""

    def test_the_default_base_is_the_official_release_channel(
        self,
        isolated_singleton_dirs: Path,  # managed-dir isolation
    ) -> None:
        del isolated_singleton_dirs
        with managed_env(**{EnvVar.QDRANT_RELEASE_BASE_URL.value: None}):
            report = provision(dry_run=True)

        assert report.action == ProvisionAction.DRY_RUN
        assert report.url == (
            "https://github.com/qdrant/qdrant/releases/download/"
            f"v{QDRANT_SERVER_VERSION}/{asset_for_platform()}"
        )

    def test_a_base_with_a_port_and_a_path_prefix_keeps_both(
        self,
        isolated_singleton_dirs: Path,  # managed-dir isolation
    ) -> None:
        del isolated_singleton_dirs
        base = "https://mirror.internal.example:8443/artifacts/qdrant"
        with managed_env(**{EnvVar.QDRANT_RELEASE_BASE_URL.value: f"{base}/"}):
            report = provision(dry_run=True)

        assert report.url == f"{base}/v{QDRANT_SERVER_VERSION}/{asset_for_platform()}"

    def test_the_configured_base_is_what_a_real_run_requests(
        self,
        sources: LoopbackSources,
        isolated_singleton_dirs: Path,  # managed-dir isolation
    ) -> None:
        """A run fetches from the configured base, whatever the host set says.

        The base host here is the loopback address, which the default redirect
        hosts do not list. The stand-in serves bytes that are not the pinned
        archive, so the run must then fail on the committed digest and install
        nothing: a source is configurable, the accepted bytes are not.
        """
        del isolated_singleton_dirs
        mirror = sources.serve(lambda handler: send_bytes(handler, _PAYLOAD))
        base = mirror.url("/mirror/qdrant")

        with managed_env(
            **{
                EnvVar.QDRANT_RELEASE_BASE_URL.value: base,
                EnvVar.QDRANT_DOWNLOAD_HOSTS.value: None,
            }
        ):
            report = provision()

        assert mirror.requests == [
            f"/mirror/qdrant/v{QDRANT_SERVER_VERSION}/{asset_for_platform()}"
        ]
        assert report.action == ProvisionAction.FAILED
        assert "SHA256 mismatch" in report.message
        assert not (qdrant_bin_dir() / binary_filename()).exists()


class TestDownloadHostsSetting:
    """A provisioning run takes its redirect hosts from the setting."""

    def test_a_mirror_redirect_is_refused_until_its_storage_host_is_listed(
        self,
        sources: LoopbackSources,
        isolated_singleton_dirs: Path,  # managed-dir isolation
    ) -> None:
        """The same mirror fails closed by default and works once listed.

        Mutation: passed a fixed host set to the download in ``provision``
        instead of the setting. Observed the second half fail on the storage
        request log (``assert [] == ['/blob']``). Restored; passes.
        """
        del isolated_singleton_dirs
        storage = sources.serve(lambda handler: send_bytes(handler, _PAYLOAD))
        mirror = sources.serve(
            lambda handler: send_redirect(handler, storage.url("/blob"))
        )
        base = {EnvVar.QDRANT_RELEASE_BASE_URL.value: mirror.url("/qdrant")}

        with managed_env(**base, **{EnvVar.QDRANT_DOWNLOAD_HOSTS.value: None}):
            refused = provision()

        assert refused.action == ProvisionAction.FAILED
        assert f"disallowed host '{LOOPBACK_HOST}'" in refused.message
        # The refusal names the setting that would admit the mirror's host.
        assert EnvVar.QDRANT_DOWNLOAD_HOSTS.value in refused.message
        assert storage.requests == []

        listed = {EnvVar.QDRANT_DOWNLOAD_HOSTS.value: f"github.com,{LOOPBACK_HOST}"}
        with managed_env(**base, **listed):
            followed = provision()

        assert storage.requests == ["/blob"]
        assert followed.action == ProvisionAction.FAILED
        assert "SHA256 mismatch" in followed.message
        assert not (qdrant_bin_dir() / binary_filename()).exists()


_LONG_PAYLOAD = b"a longer stand-in body, sent in more than one write. " * 512


class _InOrder:
    """Answer successive requests with successive responders, then the last."""

    def __init__(self, *responders: Callable[[QuietHandler], None]) -> None:
        self._responders = responders
        self._guard = threading.Lock()
        self._served = 0

    def __call__(self, handler: QuietHandler) -> None:
        with self._guard:
            index = min(self._served, len(self._responders) - 1)
            self._served += 1
        self._responders[index](handler)


def _busy(handler: QuietHandler) -> None:
    send_bytes(handler, b"try again later", status=HTTPStatus.SERVICE_UNAVAILABLE)


def _trickle(handler: QuietHandler) -> None:
    """Send a body one small piece at a time, three seconds end to end."""
    pieces, piece = 60, b"\0" * 1024
    handler.send_response(HTTPStatus.OK)
    handler.send_header("Content-Length", str(pieces * len(piece)))
    handler.end_headers()
    for _ in range(pieces):
        handler.wfile.write(piece)
        handler.wfile.flush()
        time.sleep(0.05)


class TestRetry:
    """Only a failure of the transport earns another attempt, and only a few."""

    def test_transient_failures_are_retried_and_each_attempt_starts_over(
        self, sources: LoopbackSources
    ) -> None:
        """A dropped transfer and a busy source are both tried again.

        The first answer promises the whole body and hangs up partway, having
        sent bytes the real body does not contain. Were an attempt to keep
        what the one before it wrote, they would survive in the result.

        Mutation: removed the rewind and truncate at the start of
        ``_fetch_once``. Observed the content assertion fail: the result
        began with the dropped attempt's bytes. Restored; passes.
        """
        dropped = b"\xff" * 4096
        source = sources.serve(
            _InOrder(
                lambda handler: send_truncated(
                    handler, dropped, declared=len(_LONG_PAYLOAD)
                ),
                _busy,
                lambda handler: send_bytes(handler, _LONG_PAYLOAD),
            )
        )
        out = io.BytesIO()
        lines: list[str] = []

        download_https(
            source.url("/asset.bin"),
            out,
            redirect_hosts=_LOOPBACK_ALLOWED,
            on_progress=lines.append,
        )

        assert len(source.requests) == 3
        assert out.getvalue() == _LONG_PAYLOAD
        # Each retry is announced, so a slow first attempt does not read as a
        # hung command.
        retries = [line for line in lines if "retrying" in line]
        assert len(retries) == 2
        assert "attempt 2 of 3" in retries[0]
        assert "attempt 3 of 3" in retries[1]

    def test_retries_stop_at_the_bound(self, sources: LoopbackSources) -> None:
        """A source that stays busy is given up on after three attempts.

        The deadline is long enough for a fourth attempt to start, so only
        the attempt bound can be what stops at three.

        Mutation: made ``_retry_delay`` ignore the attempt count. Observed the
        request-count assertion fail (``4 == 3``). Restored; passes.
        """
        source = sources.serve(_busy)

        with pytest.raises(urllib.error.HTTPError) as gave_up:
            download_https(
                source.url("/asset.bin"),
                io.BytesIO(),
                redirect_hosts=_LOOPBACK_ALLOWED,
                deadline_seconds=6.0,
            )

        assert gave_up.value.code == HTTPStatus.SERVICE_UNAVAILABLE
        assert len(source.requests) == 3

    def test_a_refusal_is_not_retried(self, sources: LoopbackSources) -> None:
        """An answer that will not change is asked for once.

        Mutation: made ``_is_transient`` accept every HTTP status. Observed
        the request-count assertion fail (``3 == 1``). Restored; passes.
        """
        source = sources.serve(
            lambda handler: send_bytes(
                handler, b"no such asset", status=HTTPStatus.NOT_FOUND
            )
        )

        with pytest.raises(urllib.error.HTTPError):
            download_https(
                source.url("/asset.bin"),
                io.BytesIO(),
                redirect_hosts=_LOOPBACK_ALLOWED,
            )

        assert len(source.requests) == 1


class TestDeadline:
    """The whole download is bounded, not only each read of it."""

    def test_a_trickling_source_is_cut_at_the_deadline(
        self, sources: LoopbackSources
    ) -> None:
        """A source that never stalls long enough to time out is still bounded.

        Every read succeeds within the socket timeout, so only the overall
        limit can end this transfer before the source is done three seconds
        later. Running past the limit is not a transport fault, so it is not
        retried either.

        Mutation: removed the deadline check in ``_stream_capped``. Observed
        ``DID NOT RAISE URLError``: the transfer ran to completion. Restored;
        passes.
        """
        source = sources.serve(_trickle)
        started = time.monotonic()

        with pytest.raises(
            urllib.error.URLError,
            match=r"did not finish within its 0\.4 second limit",
        ):
            download_https(
                source.url("/asset.bin"),
                io.BytesIO(),
                redirect_hosts=_LOOPBACK_ALLOWED,
                deadline_seconds=0.4,
            )

        assert time.monotonic() - started < 2.0
        assert len(source.requests) == 1

    def test_a_retry_that_cannot_start_before_the_deadline_is_not_made(
        self, sources: LoopbackSources
    ) -> None:
        source = sources.serve(_busy)

        with pytest.raises(urllib.error.HTTPError):
            download_https(
                source.url("/asset.bin"),
                io.BytesIO(),
                redirect_hosts=_LOOPBACK_ALLOWED,
                # Shorter than the first wait between attempts can be.
                deadline_seconds=0.3,
            )

        assert len(source.requests) == 1

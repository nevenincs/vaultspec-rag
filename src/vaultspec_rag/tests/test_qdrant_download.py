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
import urllib.error
from typing import TYPE_CHECKING

import pytest

from .._sync_vocabulary import ProvisionAction
from ..config._types import EnvVar
from ..qdrant_runtime._constants import QDRANT_SERVER_VERSION
from ..qdrant_runtime._download import DownloadLimits, download_https
from ..qdrant_runtime._provision import provision
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
    trusted_loopback_sources,
)
from .conftest import managed_env

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path


pytestmark = [pytest.mark.unit]

_PAYLOAD = b"stand-in archive bytes, not a release"

#: A redirect set that lists the stand-ins' address, and one that does not.
_LOOPBACK_ALLOWED = frozenset({LOOPBACK_HOST})
_LOOPBACK_NOT_ALLOWED = frozenset({"storage.example"})


@pytest.fixture
def sources(tmp_path: Path) -> Generator[LoopbackSources]:
    with trusted_loopback_sources(tmp_path / "tls") as started:
        yield started


class TestShippedLimits:
    def test_a_source_that_never_answers_costs_under_two_minutes(self) -> None:
        """The limits a real run uses bound a silent source to a short wait.

        A source that accepts the connection and then sends nothing is waited
        on for the stall limit, once per attempt, with the longest allowed
        pause between attempts. That sum is what an operator sits through
        before being told, so it is held to a figure here rather than left to
        whatever the three numbers happen to multiply out to. The stall limit
        itself is exercised against a silent server elsewhere, with limits
        small enough to reach.

        Mutation: set the stall limit to 120 seconds. Observed the assertion
        fail (``368.0 <= 100.0``). Restored; passes.
        """
        shipped = DownloadLimits()

        worst_case = (
            shipped.attempts * shipped.stall_seconds
            + (shipped.attempts - 1) * shipped.retry_cap_seconds
        )

        assert worst_case <= 100.0
        # The whole-download deadline must be the looser bound, or it would
        # cut a silent source first and the message would name the wrong one.
        assert worst_case < shipped.deadline_seconds


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

"""Closed support-profile admission over real typed measurements."""

import pathlib
from dataclasses import replace
from typing import cast

import pytest

from .._job_errors import JobError, JobErrorKind
from .._store_writes import VolumeReading
from .._units import human_bytes
from ..index_profiles import (
    IndexDomain,
    StorageBackend,
    SupportMeasurement,
    get_index_support_profile,
    index_support_profile_status,
    validate_profile_admission,
)

pytestmark = [pytest.mark.unit]


def _volume(
    free_bytes: int | None,
    path: str = "managed/storage",
    *,
    role: str = "vector store",
    device: int | None = 1,
) -> VolumeReading:
    """One volume observation with an exact free figure.

    ``VolumeReading`` is a pure record, so the path need not exist; nothing
    in admission touches the filesystem once the probe has run. ``device``
    is what decides whether two readings are the same volume, so distinct
    volumes must be given distinct ids here.
    """
    resolved = pathlib.Path(path)
    return VolumeReading(
        role=role,
        path=resolved,
        measured_path=resolved,
        free_bytes=free_bytes,
        device_id=device,
    )


def test_profiles_keep_code_and_document_limits_independent() -> None:
    profile = get_index_support_profile("managed-service")
    assert profile.limits_for(IndexDomain.CODE) is profile.code
    assert profile.limits_for(IndexDomain.DOCUMENT) is profile.document
    assert profile.document.source_bytes > profile.code.source_bytes


def test_document_profile_admits_within_every_declared_bound() -> None:
    profile = get_index_support_profile("managed-service")
    limits = profile.document
    admitted = validate_profile_admission(
        profile.name,
        IndexDomain.DOCUMENT,
        SupportMeasurement(
            source_files=limits.source_files,
            source_bytes=limits.source_bytes,
            generated_chunks=limits.generated_chunks,
            weighted_bytes=limits.weighted_bytes,
            extracted_bytes=limits.extracted_bytes,
            queue_bytes=limits.queue_bytes,
            rss_bytes=limits.rss_bytes,
            cuda_bytes=limits.cuda_bytes,
        ),
        backend="server",
        available_ram_bytes=profile.minimum_ram_bytes,
        store_volume=_volume(profile.minimum_free_disk_bytes),
    )
    assert admitted is profile


@pytest.mark.parametrize(
    ("measurement", "kind"),
    [
        (SupportMeasurement(500_001, 1), JobErrorKind.CORPUS_LIMIT_EXCEEDED),
        (SupportMeasurement(1, 1, 5_000_001), JobErrorKind.CORPUS_LIMIT_EXCEEDED),
        (
            SupportMeasurement(1, 1, extracted_bytes=128 * 1024**3 + 1),
            JobErrorKind.CORPUS_LIMIT_EXCEEDED,
        ),
        (
            SupportMeasurement(1, 1, queue_bytes=512 * 1024**2 + 1),
            JobErrorKind.CORPUS_LIMIT_EXCEEDED,
        ),
        (
            SupportMeasurement(1, 1, rss_bytes=16 * 1024**3 + 1),
            JobErrorKind.CORPUS_LIMIT_EXCEEDED,
        ),
    ],
)
def test_profile_rejects_corpus_dimensions_structurally(
    measurement: SupportMeasurement,
    kind: JobErrorKind,
) -> None:
    profile = get_index_support_profile("managed-service")
    with pytest.raises(JobError) as raised:
        validate_profile_admission(
            profile.name,
            IndexDomain.CODE,
            measurement,
            backend="server",
            available_ram_bytes=profile.minimum_ram_bytes,
            store_volume=_volume(profile.minimum_free_disk_bytes),
        )
    assert raised.value.error_kind is kind


def test_profile_rejects_backend_host_and_disk_before_corpus() -> None:
    profile = get_index_support_profile("managed-service")
    checks = (
        ("local", profile.minimum_ram_bytes, profile.minimum_free_disk_bytes),
        ("server", profile.minimum_ram_bytes - 1, profile.minimum_free_disk_bytes),
        ("server", profile.minimum_ram_bytes, profile.minimum_free_disk_bytes - 1),
    )
    expected = (
        JobErrorKind.PROFILE_REQUIREMENTS_NOT_MET,
        JobErrorKind.PROFILE_REQUIREMENTS_NOT_MET,
        JobErrorKind.DISK_PREFLIGHT_FAILED,
    )
    for arguments, kind in zip(checks, expected, strict=True):
        backend, ram, disk = arguments
        with pytest.raises(JobError) as raised:
            validate_profile_admission(
                profile.name,
                IndexDomain.DOCUMENT,
                SupportMeasurement(1, 1),
                backend=cast("StorageBackend", backend),  # ty: ignore[redundant-cast]
                available_ram_bytes=ram,
                store_volume=_volume(disk),
            )
        assert raised.value.error_kind is kind


def test_managed_disk_floor_is_a_host_provisioning_number() -> None:
    """The flat floor sizes the HOST, not the run.

    Pinned to the exact value because it is derived - a fresh namespace's
    preallocation, the shared write floor, one ordinary project's measured
    footprint, and an optimizer pass's transient inflation - not chosen for
    roundness. A future edit that drifts it back toward a per-run-sized
    number should have to justify itself here. Whether a particular run
    fits is the per-run point estimate's question, exercised by
    ``TestPerRunEstimateSizesTheRun``.
    """
    profile = get_index_support_profile("managed-service")

    assert profile.minimum_free_disk_bytes == 8 * 1024**3
    # An ordinary indexed project measured 3.4 GiB. A floor more than a few
    # multiples above that is answering the per-run question badly rather
    # than the host question at all.
    assert profile.minimum_free_disk_bytes < 10 * 1024**3


def test_embedded_disk_floor_is_derived_at_its_own_scale() -> None:
    """Same derivation, this profile's scale.

    The preallocation term is included even though local mode preallocates
    nothing, because this profile also accepts the server backend and a
    floor has to hold for every backend its profile admits.
    """
    profile = get_index_support_profile("embedded-local")

    assert profile.minimum_free_disk_bytes == 5 * 1024**3
    assert "server" in profile.accepted_backends


def test_the_disk_floor_ladder_is_ordered() -> None:
    """The smaller profile must never demand more disk than the larger one.

    This is the invariant, not the two value pins above, which only happen
    to agree today. Lowering the managed floor once inverted this ladder and
    nothing in the suite noticed - an incoherent contract that also silently
    disables the refusal's fall-back suggestion, since a suggestion can only
    offer a profile whose floor is lower.
    """
    managed = get_index_support_profile("managed-service")
    embedded = get_index_support_profile("embedded-local")

    assert embedded.minimum_free_disk_bytes < managed.minimum_free_disk_bytes


def test_disk_refusal_names_units_location_and_a_way_out() -> None:
    profile = get_index_support_profile("managed-service")
    free = 3_221_225_472
    volume = _volume(free, "managed/vaultspec-rag/qdrant-server/storage")

    with pytest.raises(JobError) as raised:
        validate_profile_admission(
            profile.name,
            IndexDomain.CODE,
            SupportMeasurement(1, 1),
            backend="server",
            available_ram_bytes=profile.minimum_ram_bytes,
            store_volume=volume,
        )

    detail = raised.value.detail
    assert raised.value.error_kind is JobErrorKind.DISK_PREFLIGHT_FAILED
    # Raw byte integers are what sent an operator to a calculator; the
    # refusal must carry neither the requirement nor the observation as one.
    assert str(free) not in detail
    assert str(profile.minimum_free_disk_bytes) not in detail
    assert "8.0 GiB" in detail
    assert "3.0 GiB" in detail
    # Which location was measured is the whole point: the store volume is
    # routinely not the volume holding the indexed tree. ``describe`` carries
    # the drive where the platform names one, so match it rather than a
    # Windows-shaped literal.
    assert volume.describe() in detail
    assert str(volume.path) in detail
    assert "VAULTSPEC_RAG_QDRANT_STORAGE_DIR" in detail


def test_ordered_ladder_offers_the_lower_floor_as_a_way_out() -> None:
    """With the ladder ordered, a managed refusal has somewhere to send you."""
    profile = get_index_support_profile("managed-service")
    embedded = get_index_support_profile("embedded-local")

    with pytest.raises(JobError) as raised:
        validate_profile_admission(
            profile.name,
            IndexDomain.CODE,
            SupportMeasurement(1, 1),
            backend="server",
            available_ram_bytes=profile.minimum_ram_bytes,
            store_volume=_volume(profile.minimum_free_disk_bytes - 1),
        )

    detail = raised.value.detail
    # The suggestion is only sound because embedded-local accepts the server
    # backend; asserting the name alone would not distinguish a sound
    # suggestion from one that swaps a disk refusal for a backend refusal.
    assert f"VAULTSPEC_RAG_INDEX_SUPPORT_PROFILE={embedded.name}" in detail
    assert "server" in embedded.accepted_backends
    assert human_bytes(embedded.minimum_free_disk_bytes) in detail


def test_the_lowest_profile_offers_no_switch() -> None:
    """Offering the profile that just refused is a dead end.

    The env-var token is asserted absent rather than matching refusal prose
    because the suggestion sentence is the ONLY place that token appears, so
    its absence cannot be produced by a wording change elsewhere.
    """
    profile = get_index_support_profile("embedded-local")

    with pytest.raises(JobError) as raised:
        validate_profile_admission(
            profile.name,
            IndexDomain.CODE,
            SupportMeasurement(1, 1),
            backend="local",
            available_ram_bytes=profile.minimum_ram_bytes,
            store_volume=_volume(profile.minimum_free_disk_bytes - 1),
        )

    assert "VAULTSPEC_RAG_INDEX_SUPPORT_PROFILE" not in raised.value.detail


def test_a_lower_floor_alone_does_not_qualify_a_profile_as_a_suggestion() -> None:
    """The backend rule, exercised against profiles that can trip it.

    No profile in the shipped table can: the only lower-floor profile
    accepts both backends. That is exactly why the selector takes its
    candidate pool as an argument - a rule no test can make fail is a rule
    nobody can trust, and this one was load-bearing while the ladder was
    inverted. These are real ``IndexSupportProfile`` values, not doubles.
    """
    from ..index_profiles import _smaller_disk_profile

    active = get_index_support_profile("managed-service")
    server_only = replace(
        get_index_support_profile("embedded-local"),
        name="server-only-cheap",
        accepted_backends=frozenset({"server"}),
        minimum_free_disk_bytes=active.minimum_free_disk_bytes // 2,
    )

    # Lower floor and an accepted backend: qualifies.
    assert _smaller_disk_profile(active, "server", [server_only]) is server_only
    # Lower floor but the wrong backend: switching would trade a disk
    # refusal for a backend refusal, so no suggestion is made at all.
    assert _smaller_disk_profile(active, "local", [server_only]) is None


def test_unmeasurable_store_volume_skips_the_disk_check() -> None:
    profile = get_index_support_profile("managed-service")

    admitted = validate_profile_admission(
        profile.name,
        IndexDomain.CODE,
        SupportMeasurement(1, 1),
        backend="server",
        available_ram_bytes=profile.minimum_ram_bytes,
        store_volume=_volume(None),
    )

    # An unknown free figure (a remote store this host cannot see) must not
    # be read as zero: refusing on a number nobody measured is the same
    # class of defect as refusing on another volume's number.
    assert admitted is profile


def test_workspace_shortfall_is_reported_as_its_own_condition() -> None:
    profile = get_index_support_profile("managed-service")
    store = _volume(profile.minimum_free_disk_bytes, "managed/storage")
    workspace = _volume(
        1024,
        "project/.vault/data/search-data",
        role="project data dir",
        device=2,
    )

    with pytest.raises(JobError) as raised:
        validate_profile_admission(
            profile.name,
            IndexDomain.CODE,
            SupportMeasurement(1, 1),
            backend="server",
            available_ram_bytes=profile.minimum_ram_bytes,
            store_volume=store,
            workspace_volume=workspace,
        )

    detail = raised.value.detail
    assert raised.value.error_kind is JobErrorKind.DISK_PREFLIGHT_FAILED
    # The two targets have wildly different requirements. Naming the one
    # that is short - and never quoting the store's profile floor at the
    # data dir - is what keeps the operator from freeing space on the
    # wrong drive.
    assert workspace.describe() in detail
    assert "project data dir" in detail
    assert str(store.path) not in detail
    assert human_bytes(profile.minimum_free_disk_bytes) not in detail


def test_workspace_check_defers_when_both_targets_share_a_volume() -> None:
    profile = get_index_support_profile("embedded-local")
    shared = "project/.vault/data/search-data"
    store = _volume(profile.minimum_free_disk_bytes, shared)
    workspace = _volume(1024, shared, role="project data dir", device=1)

    admitted = validate_profile_admission(
        profile.name,
        IndexDomain.CODE,
        SupportMeasurement(1, 1),
        backend="local",
        available_ram_bytes=profile.minimum_ram_bytes,
        store_volume=store,
        workspace_volume=workspace,
    )

    # Local mode puts both targets on one volume, where the store's larger
    # requirement has already answered the question. Reporting a second
    # shortfall on the same drive would invite freeing space twice.
    assert admitted is profile


def test_ram_refusal_reports_units_not_raw_bytes() -> None:
    profile = get_index_support_profile("managed-service")

    with pytest.raises(JobError) as raised:
        validate_profile_admission(
            profile.name,
            IndexDomain.CODE,
            SupportMeasurement(1, 1),
            backend="server",
            available_ram_bytes=profile.minimum_ram_bytes - 1,
            store_volume=_volume(profile.minimum_free_disk_bytes),
        )

    detail = raised.value.detail
    assert str(profile.minimum_ram_bytes) not in detail
    assert "16.0 GiB RAM" in detail


def test_profile_status_keeps_all_resource_dimensions_per_domain() -> None:
    status = index_support_profile_status("managed-service")
    domains = cast("dict[str, dict[str, int]]", status["domains"])
    expected = {
        "source_files",
        "source_bytes",
        "generated_chunks",
        "weighted_bytes",
        "extracted_bytes",
        "queue_bytes",
        "rss_bytes",
        "cuda_bytes",
    }
    assert set(domains["code"]) == expected
    assert set(domains["document"]) == expected

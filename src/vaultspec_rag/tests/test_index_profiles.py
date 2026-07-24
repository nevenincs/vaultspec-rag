"""Closed support-profile admission over real typed measurements."""

import pathlib
from typing import cast

import pytest

from .._job_errors import JobError, JobErrorKind
from .._store_writes import StoreVolume
from ..index_profiles import (
    IndexDomain,
    StorageBackend,
    SupportMeasurement,
    get_index_support_profile,
    index_support_profile_status,
    validate_profile_admission,
)


def _volume(free_bytes: int | None, path: str = "managed/storage") -> StoreVolume:
    """A store-volume observation with an exact free figure.

    ``StoreVolume`` is a pure record, so the path need not exist; nothing in
    admission touches the filesystem once the probe has run.
    """
    resolved = pathlib.Path(path)
    return StoreVolume(path=resolved, measured_path=resolved, free_bytes=free_bytes)


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


def test_disk_refusal_names_units_location_and_a_way_out() -> None:
    profile = get_index_support_profile("managed-service")
    free = 36_157_648_896
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
    assert "64.0 GiB" in detail
    assert "33.7 GiB" in detail
    # Which location was measured is the whole point: the store volume is
    # routinely not the volume holding the indexed tree. ``describe`` carries
    # the drive where the platform names one, so match it rather than a
    # Windows-shaped literal.
    assert volume.describe() in detail
    assert str(volume.path) in detail
    assert "VAULTSPEC_RAG_QDRANT_STORAGE_DIR" in detail
    assert "VAULTSPEC_RAG_INDEX_SUPPORT_PROFILE=embedded-local" in detail


def test_disk_refusal_omits_a_smaller_profile_when_already_smallest() -> None:
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

    # Offering the profile that just refused as its own remediation is a
    # dead end; no lower floor exists, so no suggestion is made.
    assert "VAULTSPEC_RAG_INDEX_SUPPORT_PROFILE" not in raised.value.detail


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

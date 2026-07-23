"""Closed support-profile admission over real typed measurements."""

from typing import cast

import pytest

from .._job_errors import JobError, JobErrorKind
from ..index_profiles import (
    IndexDomain,
    StorageBackend,
    SupportMeasurement,
    get_index_support_profile,
    index_support_profile_status,
    validate_profile_admission,
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
        free_disk_bytes=profile.minimum_free_disk_bytes,
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
        (
            SupportMeasurement(1, 1, cuda_bytes=12 * 1024**3 + 1),
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
            free_disk_bytes=profile.minimum_free_disk_bytes,
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
                free_disk_bytes=disk,
            )
        assert raised.value.error_kind is kind


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

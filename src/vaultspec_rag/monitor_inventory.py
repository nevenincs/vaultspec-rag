"""Read persisted operator inventory for a monitor with no responding daemon."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path


def read_inventory(operation: str, parameters: dict[str, str]) -> dict[str, object]:
    """Use the service's canonical projections with unavailable live readings."""
    root = parameters.get("root")
    if root is not None:
        if not root.strip():
            raise ValueError("root must be a non-empty path.")
        root = str(Path(root).resolve())
    if operation == "repositories":
        from .server._routes_operator import inventory_limit, repository_inventory

        return repository_inventory(
            None, root=root, limit=inventory_limit(parameters.get("limit"))
        )
    if operation != "storage/survey":
        raise ValueError("Unknown persisted inventory operation.")
    from .server._routes_storage import (
        _STORAGE_SURVEY_STATUSES,
        _clamp_survey_limit,
        _shape_survey_payload,
        _SurveyPayloadRequest,
    )
    from .storage_survey_ops import gather_disk_survey, server_storage_collections_dir

    status = parameters.get("status")
    if status is not None and status not in _STORAGE_SURVEY_STATUSES:
        raise ValueError("status must be one of live, orphaned, unknown, unverifiable.")
    directory = server_storage_collections_dir()
    if directory is None:
        raise OSError("The managed collection directory is unavailable on this host.")
    return _shape_survey_payload(
        _SurveyPayloadRequest(
            surveys=gather_disk_survey(directory),
            status_filter=status,
            limit=_clamp_survey_limit(parameters.get("limit")),
            root=root,
            computed_at=datetime.now(UTC).isoformat(),
            source="disk",
        )
    )

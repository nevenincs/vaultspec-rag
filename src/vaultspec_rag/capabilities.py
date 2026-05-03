"""Runtime capability contracts for vaultspec-rag backends."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class BackendCapabilities(BaseModel):
    """Search backend concurrency capabilities exposed to callers.

    Attributes:
        backend: Identifier for the active vector-store backend.
        concurrent_search_supported: Whether the service accepts
            concurrent search requests.
        same_project_search_strategy: How concurrent searches for the
            same project are coordinated before local backend access.
        cross_project_search_strategy: How searches for different
            projects are coordinated by the service.
        local_storage_process_model: Whether the local storage folder
            can be opened by multiple vaultspec-rag processes at once.
    """

    backend: Literal["qdrant-local"] = Field(
        default="qdrant-local",
        description="Vector-store backend identifier",
    )
    concurrent_search_supported: bool = Field(
        default=True,
        description="Whether the service accepts concurrent search requests",
    )
    same_project_search_strategy: Literal["serialized"] = Field(
        default="serialized",
        description="How same-project searches coordinate local backend access",
    )
    cross_project_search_strategy: Literal["parallel"] = Field(
        default="parallel",
        description="How different-project searches are coordinated",
    )
    local_storage_process_model: Literal["exclusive"] = Field(
        default="exclusive",
        description="Whether local Qdrant storage supports multi-process opens",
    )


def backend_capabilities_dict() -> dict[str, object]:
    """Return backend capability fields for JSON response surfaces."""
    return BackendCapabilities().model_dump()

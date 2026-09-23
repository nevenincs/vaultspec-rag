"""Optional features an operator needs to see are active, per service and per root.

Typesafe classification is a property of the service process: one key, shared
by every root it serves. Preprocessing hooks are a property of a repository:
its own rules, gated by the service's preprocess mode.
"""

from __future__ import annotations

from enum import StrEnum

from .._operator_commands import preprocess_status_command

__all__ = ["PreprocessHookState", "TypesafeState"]


class TypesafeState(StrEnum):
    """Hosted search classification, as the service process sees it."""

    OFF = "off"
    PENDING = "pending"
    ACTIVE = "active"
    REJECTED = "rejected"
    COOLDOWN = "cooldown"

    @property
    def label(self) -> str:
        """Plain-language statement of the classification state."""
        return {
            TypesafeState.OFF: "off (no API key; standard ranking)",
            TypesafeState.PENDING: (
                "on (API key set; waiting for its first successful search)"
            ),
            TypesafeState.ACTIVE: "on (recent searches were classified)",
            TypesafeState.REJECTED: (
                "on but the API key was rejected; standard ranking is used"
            ),
            TypesafeState.COOLDOWN: (
                "on but paused after errors; standard ranking is used for now"
            ),
        }[self]

    @property
    def is_enabled(self) -> bool:
        """Whether an API key enrols this service."""
        return self is not TypesafeState.OFF


class PreprocessHookState(StrEnum):
    """Whether a repository's preprocessing hooks run when it is indexed."""

    NONE = "none"
    ACTIVE = "active"
    DISABLED = "disabled"
    INVALID_CONFIG = "invalid_config"

    @property
    def label(self) -> str:
        """Plain-language statement of the hook state."""
        return {
            PreprocessHookState.NONE: "none configured",
            PreprocessHookState.ACTIVE: (
                "active (their commands run directly while indexing, with the "
                "privileges of whoever indexes)"
            ),
            PreprocessHookState.DISABLED: (
                "configured but switched off (VAULTSPEC_RAG_PREPROCESS=off)"
            ),
            PreprocessHookState.INVALID_CONFIG: (
                "configuration is invalid, so no hooks run"
            ),
        }[self]

    @property
    def remediation(self) -> str | None:
        """What the operator should do, or ``None`` when nothing is needed."""
        return {
            PreprocessHookState.NONE: None,
            PreprocessHookState.ACTIVE: None,
            PreprocessHookState.DISABLED: (
                "Unset VAULTSPEC_RAG_PREPROCESS and restart the service to run them."
            ),
            PreprocessHookState.INVALID_CONFIG: (
                f"Run `{preprocess_status_command()}` to see what is wrong."
            ),
        }[self]

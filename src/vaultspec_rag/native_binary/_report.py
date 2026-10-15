"""What one provisioning run of a native binary did, in the shared vocabulary.

Every native binary this product installs reports the same handful of facts:
which action the run took, which version and release artifact it was about,
where the bytes came from, where the executable ended up, the digest it was
held to, and what an operator is told when the run did not simply succeed.
Each provisioner names its own version and artifacts; the shape they are
reported in is one.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    from .._sync_vocabulary import ProvisionAction

__all__ = ["ProvisionReport"]


@dataclass
class ProvisionReport:
    """Structured outcome of one provisioning run.

    Attributes:
        action: A :class:`ProvisionAction` member naming the outcome.
            ``StrEnum`` members compare equal to their string values, so JSON
            consumers can filter on ``"created"``.
        version: The pinned version the run targeted.
        asset: The release artifact name for this platform.
        url: The upstream download URL (informational; empty when nothing
            was or would be fetched).
        binary: Path the active binary lives at (or would live at for a dry
            run).
        sha256: The committed digest the run verified (or would verify).
        message: Human-readable detail, mandatory for ``skipped`` and
            ``failed``.
    """

    action: ProvisionAction
    version: str
    asset: str = ""
    url: str = ""
    binary: Path | None = None
    sha256: str = ""
    message: str = ""

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serialisable view of this report."""
        return {
            "action": str(self.action),
            "version": self.version,
            "asset": self.asset,
            "url": self.url,
            "binary": str(self.binary) if self.binary else None,
            "sha256": self.sha256,
            "message": self.message,
        }

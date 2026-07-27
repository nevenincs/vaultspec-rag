"""The words a provisioning step reports its outcome with.

Two enums carried this vocabulary - one in the install front door, one in the
qdrant runtime - with identical members, and each docstring said it was
"mirroring the project-wide sync vocabulary". Neither owned it, so the mirror
had to be maintained by hand, and it was: a six-entry translation existed
between them whose every entry mapped a member onto the member of the same
name.

An identity map is the clearest possible signal that two types are one type.
It also has to be edited whenever either side gains a member, and a missed
edit raises ``KeyError`` at the moment a new outcome first occurs - which is
to say, on the least-tested path.

The vocabulary is not qdrant's and not the installer's, so it lives in neither
and both import it.
"""

from __future__ import annotations

from enum import StrEnum

__all__ = ["ProvisionAction"]


class ProvisionAction(StrEnum):
    """Closed outcome vocabulary for one provisioning step.

    ``StrEnum`` members compare equal to their value, so a JSON consumer
    filters on the same strings every provisioner emits.

    Values:
        CREATED: provisioned for the first time.
        UPDATED: an existing provision was replaced or advanced.
        UNCHANGED: already correct; nothing was written.
        SKIPPED: deliberately not attempted, with a reason.
        FAILED: attempted and did not succeed.
        DRY_RUN: previewed only, nothing was written.
    """

    CREATED = "created"
    UPDATED = "updated"
    UNCHANGED = "unchanged"
    SKIPPED = "skipped"
    FAILED = "failed"
    DRY_RUN = "dry_run"

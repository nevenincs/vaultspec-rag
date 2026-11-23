"""Install the pinned, verified Qdrant server where the store suites find it.

Several accelerator-free suites attach to, supervise and restart a real Qdrant
server, and refuse to run against anything but the managed install. The
product's own ``server qdrant install`` fetches it only for an environment that
can run the service, and a test environment built without the inference stack
is not one, so it answers ``skipped`` there. This runs the same provisioning
step directly: the same pin, the same download and the same verification.

It is idempotent: an install already in place is left as it is.
"""

from __future__ import annotations

import sys

from dev.exit_codes import FAILED, OK


def main() -> int:
    """Provision the managed Qdrant binary and report what was done."""
    from vaultspec_rag._sync_vocabulary import ProvisionAction
    from vaultspec_rag.qdrant_runtime._provision import provision

    report = provision()
    print(f"qdrant: {report.action.value} {report.message}", flush=True)
    if report.action in {
        ProvisionAction.CREATED,
        ProvisionAction.UNCHANGED,
        ProvisionAction.UPDATED,
    }:
        return OK
    return FAILED


if __name__ == "__main__":
    sys.exit(main())

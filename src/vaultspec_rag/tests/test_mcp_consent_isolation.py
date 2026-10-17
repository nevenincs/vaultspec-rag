"""Test approvals never reach the operator's MCP trust ledger."""

from __future__ import annotations

import json

import pytest
from vaultspec_core.core.mcps_trust import trust_file_path

from ._mcp_consent import grant_isolated

pytestmark = [pytest.mark.unit]


def test_a_grant_without_an_isolated_home_is_refused() -> None:
    # Refused before ``grant`` runs, so this test writes nothing to the real home.
    with pytest.raises(AssertionError, match="operator's MCP trust ledger"):
        grant_isolated([])


@pytest.mark.usefixtures("isolated_mcp_trust_home")
def test_a_grant_in_an_isolated_home_lands_in_that_home() -> None:
    grant_isolated([])

    ledger = json.loads(trust_file_path().read_text(encoding="utf-8"))
    assert ledger == {"version": 1, "grants": {}}

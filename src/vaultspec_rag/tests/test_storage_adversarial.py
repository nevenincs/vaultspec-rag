"""Adversarial / data-safety unit tests for the storage surface.

These guard the invariants that make accidental out-of-scope destruction
impossible: the destructive CLI verbs refuse a ``--json`` run without
``--yes`` (no prompt can corrupt a machine stream into an unintended
apply), an invalid migrate target is rejected before any client opens,
and path-containment rejects traversal / escape. The server-backed
out-of-scope-protection invariant (prune deletes only orphaned, never
unknown or live) lives in the integration suite.
"""

from __future__ import annotations

import pytest
import typer

from ..cli._service_storage import _emit_or_echo_error, _require_yes_for_json
from ..storage_safety import StorageSafetyError, resolve_within

pytestmark = [pytest.mark.unit]


@pytest.mark.parametrize(
    "command",
    ["server.storage.delete", "server.storage.prune", "server.storage.migrate"],
)
def test_json_without_yes_is_refused(command: str) -> None:
    """Every destructive verb refuses --json unless --yes is also given."""
    with pytest.raises(typer.Exit) as exc:
        _require_yes_for_json(command, json_mode=True, yes=False)
    assert exc.value.exit_code == 2


def test_json_with_yes_is_allowed() -> None:
    # --json + --yes is the scripted apply path: no exit raised.
    _require_yes_for_json("server.storage.delete", json_mode=True, yes=True)


def test_human_mode_without_yes_is_allowed() -> None:
    # Human mode prompts/previews instead of erroring on the json guard.
    _require_yes_for_json("server.storage.delete", json_mode=False, yes=False)


def test_emit_or_echo_error_exits_with_code() -> None:
    with pytest.raises(typer.Exit) as exc:
        _emit_or_echo_error(
            "server.storage.migrate", "invalid_target", "bad", 2, json_mode=False
        )
    assert exc.value.exit_code == 2


def test_traversal_escape_is_rejected(tmp_path: object) -> None:
    from pathlib import Path

    base = Path(str(tmp_path)) / "managed"
    base.mkdir()
    with pytest.raises(StorageSafetyError):
        resolve_within(base / ".." / ".." / "etc", base)

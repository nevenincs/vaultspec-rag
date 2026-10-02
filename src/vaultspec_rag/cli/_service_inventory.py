"""Bounded persisted projections for the monitor's portable owner command."""

from __future__ import annotations

import json
from typing import Annotated, cast

import typer

from ..monitor_inventory import read_inventory
from ._app import server_root_app
from ._render import _emit_json, _emit_json_error_and_exit


@server_root_app.command("inventory")
def inventory(
    operation: Annotated[str, typer.Argument(help="repositories or storage/survey")],
    parameters: Annotated[str, typer.Argument(help="Bounded JSON string parameters")],
) -> None:
    """Emit persisted monitor inventory without creating or operating a service."""
    try:
        if len(parameters.encode("utf-8")) > 8192:
            raise ValueError("Inventory parameters are too large.")
        decoded: object = json.loads(parameters)
        if not isinstance(decoded, dict):
            raise ValueError("Inventory parameters must be an object.")
        values = cast("dict[object, object]", decoded)
        if any(
            not isinstance(key, str) or not isinstance(value, str)
            for key, value in values.items()
        ):
            raise ValueError("Inventory parameters must be strings.")
        allowed = {"root", "limit"}
        if operation == "storage/survey":
            allowed.update(("status", "fresh"))
        if values.keys() - allowed:
            raise ValueError("Unknown inventory parameter.")
        payload = read_inventory(operation, cast("dict[str, str]", values))
    except ValueError as exc:
        _emit_json_error_and_exit("server.inventory", "bad_request", str(exc), 2)
    except OSError as exc:
        _emit_json_error_and_exit(
            "server.inventory", "inventory_unavailable", str(exc), 3
        )
    else:
        _emit_json(True, "server.inventory", data=payload)

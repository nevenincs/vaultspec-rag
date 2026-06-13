"""``server doctor`` - bounded readiness report for external dependencies.

A thin adapter over the service-domain readiness reporter (``api.get_readiness``):
it renders the same bounded per-dependency snapshot in human and JSON modes and
mutates nothing. The shared snapshot also backs the ``/readiness`` loopback route
so the CLI verb and the monitoring surface report identical state (the service
domain owns operability; adapters only render it).
"""

from __future__ import annotations

from typing import Annotated, cast

import typer

import vaultspec_rag.cli as _cli

from ..api import get_readiness
from ._app import server_app
from ._render import _emit_json


@server_app.command(
    "doctor",
    help="Report readiness of external dependencies (torch, models, qdrant).",
)
def service_doctor(
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Emit the readiness snapshot as a JSON envelope."),
    ] = False,
) -> None:
    """Render the bounded, read-only dependency readiness snapshot.

    Reports, per external dependency, whether it is provisioned and usable:
    torch CUDA availability, search/rerank model presence, and the qdrant
    binary resolution source plus supervised-server liveness when server mode
    is effective. Performs no provisioning and mutates nothing.
    """
    report = get_readiness()
    if json_output:
        _emit_json(bool(report.get("ready")), "server doctor", data=report)
        return
    _render_readiness(report)


def _render_readiness(report: dict[str, object]) -> None:
    """Render the readiness snapshot as a bounded plain-text summary."""
    server_mode = bool(report.get("server_mode"))
    _cli.console.print("Service readiness", markup=False, highlight=False)
    _cli.console.print(
        f"Backend: {'server' if server_mode else 'local-only'}",
        markup=False,
        highlight=False,
    )
    _cli.console.print(
        f"Readiness: {'ready for requests' if report.get('ready') else 'not ready'}",
        markup=False,
        highlight=False,
    )
    deps = report.get("dependencies")
    dep_list = cast("list[object]", deps) if isinstance(deps, list) else []
    for dep in dep_list:
        if not isinstance(dep, dict):
            continue
        dep_map = cast("dict[str, object]", dep)
        name = str(dep_map.get("name", "?"))
        status = str(dep_map.get("status", "unknown"))
        detail = str(dep_map.get("detail", ""))
        line = f"  {name}: {status}" + (f" - {detail}" if detail else "")
        _cli.console.print(line, markup=False, highlight=False)

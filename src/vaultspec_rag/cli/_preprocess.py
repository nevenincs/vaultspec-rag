"""``preprocess`` command group: inspect, validate, and trial preprocess rules.

Implements the operator surface decided in the ``preprocess-hooks`` ADR (D13):

- ``preprocess list``   - show the resolved rules for the project root.
- ``preprocess check``  - validate ``.vaultragpreprocess.toml`` (the only
  hard-fail path; non-zero exit on an invalid config).
- ``preprocess run-one`` - run the matching rule against one file and print the
  validated output, for authoring/debugging. No indexing side effect.

All three honour the shared ``--json`` envelope.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, cast

import typer
from rich.table import Table

import vaultspec_rag.cli as _cli

from ..indexer._preprocess_config import (
    PreprocessConfigError,
    load_preprocess_rules,
)
from ..indexer._preprocess_runner import PreprocessAbortError, run_preprocessor
from ._app import CLIState, preprocess_app
from ._render import _emit_json, _emit_json_error_and_exit


def _root(ctx: typer.Context) -> Path:
    return cast("CLIState", ctx.obj).target


@preprocess_app.command("list", help="List resolved preprocess rules for the project.")
def handle_preprocess_list(
    ctx: typer.Context,
    json_mode: Annotated[
        bool, typer.Option("--json", help="Emit one JSON envelope instead of a table.")
    ] = False,
) -> None:
    """Show the project's resolved preprocess rules in precedence order."""
    config = load_preprocess_rules(_root(ctx))
    rules = [
        {
            "pattern": r.pattern,
            "command": r.command,
            "priority": r.priority,
            "on_error": r.on_error,
            "timeout_s": r.timeout_s,
        }
        for r in config.rules
    ]
    if json_mode:
        _emit_json(True, "preprocess list", data={"rules": rules})
        return
    if not rules:
        _cli.console.print("No preprocess rules configured (.vaultragpreprocess.toml).")
        return
    table = Table(title="Preprocess Rules", show_header=True)
    table.add_column("Pattern", style="cyan")
    table.add_column("Command", style="white")
    table.add_column("Priority", justify="right")
    table.add_column("on_error", style="yellow")
    table.add_column("timeout_s", justify="right")
    for r in rules:
        table.add_row(
            str(r["pattern"]),
            str(r["command"]),
            str(r["priority"]),
            str(r["on_error"]),
            "-" if r["timeout_s"] is None else str(r["timeout_s"]),
        )
    _cli.console.print(table)


@preprocess_app.command(
    "check", help="Validate .vaultragpreprocess.toml (non-zero on error)."
)
def handle_preprocess_check(
    ctx: typer.Context,
    json_mode: Annotated[
        bool, typer.Option("--json", help="Emit one JSON envelope instead of text.")
    ] = False,
) -> None:
    """Strictly validate the config; exit non-zero on the first defect."""
    try:
        config = load_preprocess_rules(_root(ctx), strict=True)
    except PreprocessConfigError as exc:
        if json_mode:
            _emit_json_error_and_exit(
                "preprocess check",
                "invalid-config",
                str(exc),
                1,
            )
        _cli.console.print(f"[red]Invalid preprocess config:[/red] {exc}")
        raise typer.Exit(code=1) from exc
    count = len(config.rules)
    if json_mode:
        _emit_json(True, "preprocess check", data={"valid": True, "rule_count": count})
        return
    _cli.console.print(f"[green]OK[/green] - {count} valid preprocess rule(s).")


@preprocess_app.command(
    "run-one", help="Run the matching rule against one file (no indexing)."
)
def handle_preprocess_run_one(
    ctx: typer.Context,
    path: Annotated[str, typer.Argument(help="Source file to preprocess.")],
    json_mode: Annotated[
        bool, typer.Option("--json", help="Emit one JSON envelope instead of text.")
    ] = False,
) -> None:
    """Trial the matching preprocessor against one file for authoring/debugging."""
    from ..config import get_config

    root = _root(ctx)
    config = load_preprocess_rules(root)
    src = Path(path)
    abs_path = src if src.is_absolute() else (root / src)
    try:
        rel = str(abs_path.resolve().relative_to(root.resolve())).replace("\\", "/")
    except ValueError:
        rel = str(path).replace("\\", "/")
    rule = config.match(rel)
    if rule is None:
        if json_mode:
            _emit_json(True, "preprocess run-one", data={"matched": False, "path": rel})
            return
        _cli.console.print(f"No preprocess rule matches {rel}.")
        return

    max_bytes = int(get_config().preprocess_max_emitted_bytes)
    try:
        result = run_preprocessor(abs_path, rule, max_emitted_bytes=max_bytes)
    except PreprocessAbortError as exc:
        if json_mode:
            _emit_json_error_and_exit(
                "preprocess run-one",
                "preprocess-abort",
                str(exc),
                1,
            )
        _cli.console.print(f"[red]Preprocessor failed (on_error=fail):[/red] {exc}")
        raise typer.Exit(code=1) from exc

    output = result.output
    unit_count = len(output.units) if output is not None and output.units else 0
    data = {
        "matched": True,
        "path": rel,
        "pattern": rule.pattern,
        "status": result.status,
        "reason": result.reason,
        "output": output.model_dump(mode="json") if output is not None else None,
        "unit_count": unit_count,
    }
    if json_mode:
        _emit_json(True, "preprocess run-one", data=data)
        return
    _cli.console.print(
        f"Rule: [cyan]{rule.pattern}[/cyan] -> status [bold]{result.status}[/bold]"
    )
    if result.reason:
        _cli.console.print(f"Reason: {result.reason}")
    if output is not None:
        mode = "units" if output.units else "text"
        _cli.console.print(
            f"Preprocessor: {output.preprocessor_id} v{output.preprocessor_version} "
            f"(schema v{output.schema_version}); mode={mode}"
            + (f", {unit_count} unit(s)" if unit_count else "")
        )

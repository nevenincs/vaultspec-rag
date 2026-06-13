"""``preprocess`` command group: inspect, validate, and trial preprocess rules.

Implements the operator surface decided in the ``preprocess-hooks`` ADR (D13):

- ``preprocess list``   - show the resolved rules for the project root.
- ``preprocess check``  - validate ``.vaultragpreprocess.toml`` and report
  configuration problems.
- ``preprocess run-one`` - run the matching rule against one file and print the
  validated output, for authoring/debugging. No indexing side effect.

All three honour the shared script-facing ``--json`` output.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, cast

import typer

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


def _format_timeout(timeout_s: object) -> str:
    if timeout_s is None:
        return "no timeout"
    return f"{timeout_s:g}s" if isinstance(timeout_s, float) else f"{timeout_s}s"


def _format_failure_handling(on_error: object) -> str:
    if on_error == "fail":
        return "stop on failure"
    if on_error == "passthrough":
        return "use original file on failure"
    return "skip file on failure"


def _format_preprocess_result(status: str) -> str:
    if status == "ok":
        return "preprocessed"
    if status == "skipped":
        return "skipped"
    if status == "passthrough":
        return "using original file"
    return status


def _format_unit_count(unit_count: int) -> str:
    if unit_count == 1:
        return "1 extracted text section"
    return f"{unit_count} extracted text sections"


@preprocess_app.command("list", help="List resolved preprocess rules for the project.")
def handle_preprocess_list(
    ctx: typer.Context,
    json_mode: Annotated[
        bool,
        typer.Option("--json", help="Emit JSON for scripts instead of human text."),
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
    _cli.console.print(f"Preprocess rules: {len(rules)}")
    for index, rule in enumerate(rules, start=1):
        _cli.console.print(f"{index}. Files: {rule['pattern']}", markup=False)
        _cli.console.print(f"   Priority: {rule['priority']}", markup=False)
        _cli.console.print(
            f"   Failure handling: {_format_failure_handling(rule['on_error'])}",
            markup=False,
        )
        _cli.console.print(
            f"   Timeout: {_format_timeout(rule['timeout_s'])}",
            markup=False,
        )
        _cli.console.print(
            f"   Command: {rule['command']}",
            markup=False,
            highlight=False,
        )


@preprocess_app.command(
    "check", help="Validate .vaultragpreprocess.toml and report configuration problems."
)
def handle_preprocess_check(
    ctx: typer.Context,
    json_mode: Annotated[
        bool,
        typer.Option("--json", help="Emit JSON for scripts instead of human text."),
    ] = False,
) -> None:
    """Strictly validate the config and report the first defect."""
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
        _cli.console.print(
            f"Preprocess config has a problem: {exc}",
            markup=False,
            highlight=False,
        )
        raise typer.Exit(code=1) from exc
    count = len(config.rules)
    if json_mode:
        _emit_json(True, "preprocess check", data={"valid": True, "rule_count": count})
        return
    if count == 0:
        _cli.console.print(
            "Preprocess config is valid. No preprocess rules configured."
        )
        return
    rule_word = "rule" if count == 1 else "rules"
    _cli.console.print(f"Preprocess config is valid: {count} {rule_word}.")


@preprocess_app.command(
    "run-one", help="Run the matching rule against one file (no indexing)."
)
def handle_preprocess_run_one(
    ctx: typer.Context,
    path: Annotated[str, typer.Argument(help="Source file to preprocess.")],
    json_mode: Annotated[
        bool,
        typer.Option("--json", help="Emit JSON for scripts instead of human text."),
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
        _cli.console.print(f"No preprocess rule matches: {rel}.")
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
        _cli.console.print(
            f"Preprocess failed: {exc}",
            markup=False,
            highlight=False,
        )
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
        f"Matched rule: {rule.pattern}",
        markup=False,
        highlight=False,
    )
    _cli.console.print(f"Outcome: {_format_preprocess_result(result.status)}")
    if result.reason:
        _cli.console.print(f"Why: {result.reason}")
    if output is not None:
        content = _format_unit_count(unit_count) if output.units else "text output"
        _cli.console.print(
            f"Preprocessor: {output.preprocessor_id} {output.preprocessor_version}"
        )
        _cli.console.print(f"Output: {content}")

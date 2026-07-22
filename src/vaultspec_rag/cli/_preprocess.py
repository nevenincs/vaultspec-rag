"""``preprocess`` command group: inspect, validate, and trial rules.

Implements the operator surface decided in the ``preprocess-hooks`` ADR (D13),
as amended by the ``preprocess-sandbox-removal`` ADR: hooks are gated only by
the ``off`` kill switch. A root's preprocess config is repo-authored code and
runs directly with the operator's privileges.

- ``preprocess list``    - show the resolved rules for the project root.
- ``preprocess check``   - validate ``.vaultragpreprocess.toml`` and report
  configuration problems.
- ``preprocess run-one`` - run the matching rule against one file and print the
  validated output, for authoring/debugging. No indexing side effect.
- ``preprocess status``  - report the mode, config presence, and rule count.

All honour the shared script-facing ``--json`` output.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, cast

import typer

import vaultspec_rag.cli as _cli

from ..config import PreprocessMode, get_config
from ..indexer._preprocess_config import (
    PREPROCESS_CONFIG_FILENAME,
    PreprocessConfig,
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
            "entry_point": r.entry_point,
            "priority": r.priority,
            "target": r.target.value,
            "extractor_version": r.extractor_version,
            "on_error": r.on_error,
            "timeout_s": r.timeout_s,
            "batch": r.batch,
            "path_independent": r.path_independent,
            "options": dict(r.options),
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
        _cli.console.print(f"   Target: {rule['target']}", markup=False)
        _cli.console.print(
            f"   Extractor version: {rule['extractor_version']}",
            markup=False,
        )
        _cli.console.print(
            "   Cross-path cache reuse: "
            f"{'enabled' if rule['path_independent'] else 'disabled'}",
            markup=False,
        )
        _cli.console.print(
            f"   Failure handling: {_format_failure_handling(rule['on_error'])}",
            markup=False,
        )
        _cli.console.print(
            f"   Timeout: {_format_timeout(rule['timeout_s'])}",
            markup=False,
        )
        _cli.console.print(
            f"   Invocation: {rule['command'] or rule['entry_point']}",
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
        _emit_json(
            True,
            "preprocess check",
            data={
                "valid": True,
                "schema_version": config.schema_version,
                "rule_count": count,
                "targets": sorted({rule.target.value for rule in config.rules}),
                "extractor_versions": sorted(
                    {rule.extractor_version for rule in config.rules}
                ),
                "path_independent_rules": sum(
                    rule.path_independent for rule in config.rules
                ),
            },
        )
        return
    if count == 0:
        _cli.console.print(
            "Preprocess config is valid. No preprocess rules configured."
        )
        return
    rule_word = "rule" if count == 1 else "rules"
    _cli.console.print(f"Preprocess config is valid: {count} {rule_word}.")


def _report_preprocess_no_match(
    root: Path,
    config: PreprocessConfig,
    rel: str,
    *,
    json_mode: bool,
) -> None:
    """Report that no preprocess rule matched *rel*, honoring the off kill switch.

    Routing remains resolved while execution is off. Surface the actionable
    off notice before considering a matching rule so this diagnostic command
    obeys the same execution gate as indexing.
    """
    gate = _gated_rule_state(root, config)
    if gate is not None:
        if json_mode:
            _emit_json(
                True,
                "preprocess run-one",
                data={
                    "matched": False,
                    "path": rel,
                    "gated": True,
                    "mode": "off",
                    "rule_count": gate,
                },
            )
            return
        _cli.console.print(
            _gated_run_one_message(gate),
            markup=False,
            highlight=False,
        )
        return
    if json_mode:
        _emit_json(True, "preprocess run-one", data={"matched": False, "path": rel})
        return
    _cli.console.print(f"No preprocess rule matches: {rel}.")


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
    if _gated_rule_state(root, config) is not None:
        _report_preprocess_no_match(root, config, rel, json_mode=json_mode)
        return
    rule = config.match(rel)
    if rule is None:
        _report_preprocess_no_match(root, config, rel, json_mode=json_mode)
        return

    max_bytes = int(get_config().preprocess_max_emitted_bytes)
    try:
        result = run_preprocessor(
            abs_path,
            rule,
            max_emitted_bytes=max_bytes,
            project_root=root,
        )
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


def _gated_rule_state(root: Path, nonstrict_config: PreprocessConfig) -> int | None:
    """Return the rule count when a root's rules are switched off, else ``None``.

    Policy routing stays available while the execution kill switch is off, so
    the resolved mode is authoritative and the retained rules provide the
    diagnostic count.

    Args:
        root: The workspace root.
        nonstrict_config: The already-resolved non-strict config (the gated one).

    Returns:
        The strict rule count when the rules exist but are switched off, else
        ``None`` (no config, an invalid config, or genuinely no rules).
    """
    from ..config import get_config

    if get_config().preprocess_mode != "off":
        return None
    if nonstrict_config.rules:
        return len(nonstrict_config.rules)
    if not (root / PREPROCESS_CONFIG_FILENAME).is_file():
        return None
    try:
        strict = load_preprocess_rules(root, strict=True)
    except PreprocessConfigError:
        return None
    if not strict.rules:
        return None
    return len(strict.rules)


def _gated_run_one_message(rule_count: int) -> str:
    """Return the actionable line for a switched-off rule set in ``run-one``."""
    word = "rule" if rule_count == 1 else "rules"
    return (
        f"Preprocessing is off; {rule_count} {word} are configured but skipped. "
        "Unset VAULTSPEC_RAG_PREPROCESS=off to run them."
    )


def _would_run(mode: PreprocessMode, rule_count: int) -> bool:
    """Return whether a root's rules would run under the resolved mode.

    Rules run for any root except under the ``off`` kill switch. A root with no
    rules never runs anything.
    """
    return rule_count > 0 and mode != "off"


def _status_effect_line(mode: PreprocessMode, rule_count: int) -> str:
    """Return the human effect/remediation line for ``preprocess status``."""
    if rule_count == 0:
        return "No preprocess rules are configured for this root."
    if mode == "off":
        return (
            "Preprocessing is off (VAULTSPEC_RAG_PREPROCESS=off); rules are "
            "skipped. Unset it to run them."
        )
    return (
        "This root's rules run directly; their commands execute with your privileges."
    )


@preprocess_app.command(
    "status",
    help="Report the preprocess mode, config presence, and rule count.",
)
def handle_preprocess_status(
    ctx: typer.Context,
    json_mode: Annotated[
        bool,
        typer.Option("--json", help="Emit JSON for scripts instead of human text."),
    ] = False,
) -> None:
    """Report the preprocess mode and the root's rule configuration."""
    root = _root(ctx)
    mode = get_config().preprocess_mode
    config_present = (root / PREPROCESS_CONFIG_FILENAME).is_file()

    rule_count = 0
    schema_version: int | None = None
    targets: list[str] = []
    extractor_versions: list[str] = []
    path_independent_rules = 0
    config_valid = True
    if config_present:
        try:
            config = load_preprocess_rules(root, strict=True)
        except PreprocessConfigError:
            config_valid = False
        else:
            rule_count = len(config.rules)
            schema_version = config.schema_version
            targets = sorted({rule.target.value for rule in config.rules})
            extractor_versions = sorted(
                {rule.extractor_version for rule in config.rules}
            )
            path_independent_rules = sum(
                rule.path_independent for rule in config.rules
            )

    effective = _would_run(mode, rule_count)

    if json_mode:
        _emit_json(
            True,
            "preprocess status",
            data={
                "mode": mode,
                "root": str(root),
                "config_present": config_present,
                "config_valid": config_valid,
                "rule_count": rule_count,
                "schema_version": schema_version,
                "targets": targets,
                "extractor_versions": extractor_versions,
                "path_independent_rules": path_independent_rules,
                "would_run": effective,
            },
        )
        return

    _cli.console.print(f"Preprocess mode: {mode}", markup=False, highlight=False)
    _cli.console.print(
        f"Config: {'present' if config_present else 'absent'}"
        f"{'' if config_valid else ' (invalid)'}",
        markup=False,
        highlight=False,
    )
    _cli.console.print(f"Rules: {rule_count}", markup=False, highlight=False)
    if schema_version is not None:
        _cli.console.print(
            f"Schema: {schema_version}; targets: {', '.join(targets) or 'none'}; "
            f"extractor versions: {', '.join(extractor_versions) or 'none'}; "
            f"cross-path cache rules: {path_independent_rules}",
            markup=False,
            highlight=False,
        )
    _cli.console.print(
        f"Effect: {_status_effect_line(mode, rule_count)}",
        markup=False,
        highlight=False,
    )

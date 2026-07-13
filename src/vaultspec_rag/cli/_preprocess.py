"""``preprocess`` command group: inspect, validate, trial, and trust rules.

Implements the operator surface decided in the ``preprocess-hooks`` ADR (D13)
and the trust-on-first-use flow of the ``index-drift-hardening`` ADR (D7):

- ``preprocess list``   - show the resolved rules for the project root.
- ``preprocess check``  - validate ``.vaultragpreprocess.toml`` and report
  configuration problems.
- ``preprocess run-one`` - run the matching rule against one file and print the
  validated output, for authoring/debugging. No indexing side effect.
- ``preprocess trust``   - review a root's resolved command set and persist a
  trust record so its rules run in the default mode.
- ``preprocess untrust`` - drop a root's trust record.
- ``preprocess status``  - report the mode, config presence, resolved-rule-set
  hash, and this root's trust state.

All honour the shared script-facing ``--json`` output.
"""

from __future__ import annotations

from datetime import UTC, datetime
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
from ..indexer._preprocess_trust import (
    hash_rule_set,
    read_trust,
    record_trust,
    remove_trust,
)
from ._app import CLIState, preprocess_app
from ._render import _emit_json, _emit_json_error_and_exit


def _root(ctx: typer.Context) -> Path:
    return cast("CLIState", ctx.obj).target


def _invocation_label(command: str | None, entry_point: str | None) -> str:
    if command is not None:
        return command
    if entry_point is not None:
        return f"entry point {entry_point}"
    return "no invocation"


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
        # The non-strict load applied the mode/trust gate, so an empty config
        # can mean "rules exist but are gated off" (untrusted default, or the
        # off kill switch) rather than "no rule matches this file". Surface the
        # actionable trust guidance instead of a misleading no-match line.
        gate = _gated_rule_state(root, config)
        if gate is not None:
            rule_count, mode = gate
            if json_mode:
                _emit_json(
                    True,
                    "preprocess run-one",
                    data={
                        "matched": False,
                        "path": rel,
                        "gated": True,
                        "mode": mode,
                        "rule_count": rule_count,
                    },
                )
                return
            _cli.console.print(
                _gated_run_one_message(root, rule_count, mode),
                markup=False,
                highlight=False,
            )
            return
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


def _gated_rule_state(
    root: Path, nonstrict_config: PreprocessConfig
) -> tuple[int, PreprocessMode] | None:
    """Return ``(rule_count, mode)`` when a root's rules are gated off, else ``None``.

    The non-strict loader returns an empty config both when a root genuinely
    defines no rules and when every rule was gated off by the tri-state/TOFU
    enforcement (an untrusted default root, or the ``off`` kill switch). The two
    are distinguished by re-resolving in strict mode, which bypasses the gate: a
    non-empty strict result over an empty non-strict one is the gated case.

    Args:
        root: The workspace root.
        nonstrict_config: The already-resolved non-strict config (the gated one).

    Returns:
        ``(strict_rule_count, mode)`` when the rules exist but are gated off,
        else ``None`` (no config, an invalid config, or genuinely no rules).
    """
    if nonstrict_config:
        return None
    if not (root / PREPROCESS_CONFIG_FILENAME).is_file():
        return None
    try:
        strict = load_preprocess_rules(root, strict=True)
    except PreprocessConfigError:
        return None
    if not strict.rules:
        return None
    return len(strict.rules), get_config().preprocess_mode


def _gated_run_one_message(root: Path, rule_count: int, mode: PreprocessMode) -> str:
    """Return the actionable line for a gated-off rule set in ``run-one``."""
    word = "rule" if rule_count == 1 else "rules"
    if mode == "off":
        return (
            f"Preprocessing is off; {rule_count} {word} are configured but "
            "skipped. Unset VAULTSPEC_RAG_PREPROCESS=off to restore "
            "trust-on-first-use."
        )
    return (
        f"This root has {rule_count} preprocess {word} but is not trusted; they "
        f"are skipped. Review and trust them with: "
        f"vaultspec-rag preprocess trust {root}"
    )


def _resolved_command_set(config: PreprocessConfig) -> list[dict[str, object]]:
    """Serialise a resolved config into the reviewable command set for trust."""
    return [
        {
            "pattern": rule.pattern,
            "command": rule.command,
            "entry_point": rule.entry_point,
            "timeout_s": rule.timeout_s,
            "on_error": rule.on_error,
        }
        for rule in config.rules
    ]


def _print_command_set(root: Path, config: PreprocessConfig) -> None:
    """Print the resolved command set an operator is about to trust."""
    rules = config.rules
    _cli.console.print(
        f"Preprocess rules to trust for {root}: {len(rules)}",
        markup=False,
        highlight=False,
    )
    for index, rule in enumerate(rules, start=1):
        _cli.console.print(f"{index}. Files: {rule.pattern}", markup=False)
        _cli.console.print(
            f"   Command: {_invocation_label(rule.command, rule.entry_point)}",
            markup=False,
            highlight=False,
        )
        _cli.console.print(
            f"   Timeout: {_format_timeout(rule.timeout_s)}",
            markup=False,
        )
        _cli.console.print(
            f"   Failure handling: {_format_failure_handling(rule.on_error)}",
            markup=False,
        )
    _cli.console.print(
        "These commands run with your privileges whenever this root is indexed.",
        markup=False,
        highlight=False,
    )


@preprocess_app.command(
    "trust",
    help=(
        "Review this root's resolved preprocess command set and trust it so its "
        "rules run in the default mode."
    ),
)
def handle_preprocess_trust(
    ctx: typer.Context,
    yes: Annotated[
        bool,
        typer.Option(
            "--yes",
            "-y",
            help="Persist the trust record without the confirmation prompt.",
        ),
    ] = False,
    json_mode: Annotated[
        bool,
        typer.Option(
            "--json",
            help=(
                "Emit JSON for scripts instead of human text. Requires --yes so "
                "no confirmation prompt interrupts the JSON output."
            ),
        ),
    ] = False,
) -> None:
    """Trust a root's resolved preprocess rule set (TOFU record, ADR D7)."""
    root = _root(ctx)
    if json_mode and not yes:
        _emit_json_error_and_exit(
            "preprocess trust",
            "json_requires_yes",
            "--json requires --yes so the command can persist trust without an "
            "interactive confirmation prompt.",
            2,
        )
    # Strict resolution so the tri-state/TOFU gate does not hide the very rules
    # the operator is about to trust, and so an invalid config is refused here.
    try:
        config = load_preprocess_rules(root, strict=True)
    except PreprocessConfigError as exc:
        message = f"Cannot trust: the preprocess config has a problem: {exc}"
        if json_mode:
            _emit_json_error_and_exit("preprocess trust", "invalid-config", str(exc), 1)
        _cli.console.print(message, markup=False, highlight=False)
        raise typer.Exit(code=1) from exc
    if not config.rules:
        message = (
            "No preprocess rules to trust: .vaultragpreprocess.toml is absent or "
            "defines no valid rules."
        )
        if json_mode:
            _emit_json_error_and_exit("preprocess trust", "no-rules", message, 1)
        _cli.console.print(message, markup=False, highlight=False)
        raise typer.Exit(code=1)

    rule_set_hash = hash_rule_set(config.rules)
    if not json_mode:
        _print_command_set(root, config)

    if not yes:
        try:
            confirmed = typer.confirm(
                f"Trust these {len(config.rules)} preprocess rule(s) for {root}?",
                default=False,
            )
        except typer.Abort:
            _cli.console.print("Trust cancelled.")
            raise typer.Exit(code=1) from None
        if not confirmed:
            _cli.console.print("Trust cancelled.")
            raise typer.Exit(code=1)

    record = record_trust(
        root,
        rule_set_hash=rule_set_hash,
        trusted_at=datetime.now(UTC).isoformat(),
    )
    if json_mode:
        _emit_json(
            True,
            "preprocess trust",
            data={
                "trusted": True,
                "root": record.root,
                "prefix": record.prefix,
                "rule_set_hash": record.rule_set_hash,
                "trusted_at": record.trusted_at,
                "rule_count": len(config.rules),
                "commands": _resolved_command_set(config),
            },
        )
        return
    _cli.console.print(
        f"Trusted {len(config.rules)} preprocess rule(s) for {root}.",
        markup=False,
        highlight=False,
    )
    _cli.console.print(f"Trust hash: {record.rule_set_hash}", markup=False)


@preprocess_app.command(
    "untrust",
    help="Remove this root's preprocess trust record so its rules stop running.",
)
def handle_preprocess_untrust(
    ctx: typer.Context,
    json_mode: Annotated[
        bool,
        typer.Option("--json", help="Emit JSON for scripts instead of human text."),
    ] = False,
) -> None:
    """Drop a root's preprocess trust record (ADR D7)."""
    root = _root(ctx)
    removed = remove_trust(root)
    if json_mode:
        _emit_json(
            True,
            "preprocess untrust",
            data={"removed": removed, "root": str(root)},
        )
        return
    if removed:
        _cli.console.print(
            f"Removed the preprocess trust record for {root}.",
            markup=False,
            highlight=False,
        )
    else:
        _cli.console.print(
            f"No preprocess trust record existed for {root}.",
            markup=False,
            highlight=False,
        )


def _trust_state(
    *,
    config_present: bool,
    rule_count: int,
    current_hash: str | None,
    trusted_hash: str | None,
) -> str:
    """Classify a root's trust state for ``preprocess status``."""
    if not config_present or rule_count == 0:
        return "not_applicable"
    if trusted_hash is None:
        return "absent"
    if current_hash is not None and trusted_hash == current_hash:
        return "match"
    return "mismatch"


def _would_run(mode: PreprocessMode, trust_state: str) -> bool:
    """Return whether a root's rules would run under the mode and trust state."""
    if trust_state in ("not_applicable",):
        return False
    if mode == "off":
        return False
    if mode == "trust_all":
        return True
    return trust_state == "match"


def _status_effect_line(mode: PreprocessMode, trust_state: str, root: Path) -> str:
    """Return the human effect/remediation line for ``preprocess status``."""
    if trust_state == "not_applicable":
        return "No preprocess rules are configured for this root."
    if mode == "off":
        return (
            "Preprocessing is off (VAULTSPEC_RAG_PREPROCESS=off); rules are "
            "skipped. Unset it to restore trust-on-first-use."
        )
    if mode == "trust_all":
        return (
            "Trust checking is bypassed (VAULTSPEC_RAG_PREPROCESS_TRUST_ALL); "
            "every root's rules run with your privileges."
        )
    if trust_state == "match":
        return "This root is trusted; its rules run when indexed."
    if trust_state == "mismatch":
        return (
            "The trusted rule set no longer matches the current one; the rules "
            f"are skipped until re-trusted with: vaultspec-rag preprocess trust "
            f"{root}"
        )
    return (
        "This root is not trusted; its rules are skipped. Trust them with: "
        f"vaultspec-rag preprocess trust {root}"
    )


@preprocess_app.command(
    "status",
    help=(
        "Report the preprocess mode, config presence, resolved-rule-set hash, and "
        "this root's trust state."
    ),
)
def handle_preprocess_status(
    ctx: typer.Context,
    json_mode: Annotated[
        bool,
        typer.Option("--json", help="Emit JSON for scripts instead of human text."),
    ] = False,
) -> None:
    """Report the tri-state mode and this root's trust state (ADR D7/D8)."""
    root = _root(ctx)
    mode = get_config().preprocess_mode
    config_present = (root / PREPROCESS_CONFIG_FILENAME).is_file()

    rule_count = 0
    current_hash: str | None = None
    config_valid = True
    if config_present:
        try:
            config = load_preprocess_rules(root, strict=True)
        except PreprocessConfigError:
            config_valid = False
        else:
            rule_count = len(config.rules)
            if config.rules:
                current_hash = hash_rule_set(config.rules)

    record = read_trust(root)
    trusted_hash = record.rule_set_hash if record is not None else None
    trusted_at = record.trusted_at if record is not None else None
    trust_state = _trust_state(
        config_present=config_present,
        rule_count=rule_count,
        current_hash=current_hash,
        trusted_hash=trusted_hash,
    )
    effective = _would_run(mode, trust_state)

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
                "rule_set_hash": current_hash,
                "trust_record_present": record is not None,
                "trusted_hash": trusted_hash,
                "trusted_at": trusted_at,
                "trust_state": trust_state,
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
    _cli.console.print(
        f"Rule set hash: {current_hash if current_hash else 'none'}",
        markup=False,
        highlight=False,
    )
    _cli.console.print(f"Trust state: {trust_state}", markup=False, highlight=False)
    if trusted_at:
        _cli.console.print(f"Trusted at: {trusted_at}", markup=False, highlight=False)
    _cli.console.print(
        f"Effect: {_status_effect_line(mode, trust_state, root)}",
        markup=False,
        highlight=False,
    )

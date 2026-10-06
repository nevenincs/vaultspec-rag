"""``preprocess`` command group: inspect, validate, approve, and trial rules.

A root's rules run only once the operator has approved that root's exact
policy, and never under the ``off`` kill switch. There is no sandbox: an
approved rule is repo-authored code that runs directly with the operator's
privileges.

- ``preprocess list``    - show the resolved rules for the project root.
- ``preprocess check``   - validate ``.vaultragpreprocess.toml`` and report
  configuration problems.
- ``preprocess approve`` - let the root's current rules run when it is indexed.
- ``preprocess revoke``  - withdraw that approval.
- ``preprocess run-one`` - run the matching rule against one file and print the
  validated output, for authoring/debugging. No indexing side effect.
- ``preprocess status``  - report the mode, approval, config presence, and rule
  count.

All honour the shared script-facing ``--json`` output.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, cast

import typer

import vaultspec_rag.cli as _cli

from .._operator_commands import index_command
from .._root_identity import canonical_root_path
from ..config._settings import get_config
from ..indexer._preprocess_approval import approve_policy, revoke_approval
from ..indexer._preprocess_config import (
    PREPROCESS_CONFIG_FILENAME,
    PreprocessConfigError,
    PreprocessPolicyError,
    config_hook_state,
    hook_state,
    load_preprocess_rules,
)
from ..indexer._preprocess_runner import PreprocessAbortError, run_preprocessor
from ..operator_state._features import PreprocessHookState
from ._app import CLIState, JsonMode, preprocess_app
from ._render import _emit_json, _emit_json_error_and_exit, _plain, _print_next_action

if TYPE_CHECKING:
    from ..config._types import PreprocessMode


def _root(ctx: typer.Context) -> Path:
    # The root callback sets ctx.obj to a CLIState for every subcommand except
    # server/install/uninstall (_app._configure_root_context), and preprocess
    # is never one of those three.
    return cast("CLIState", ctx.obj).target


def _config_error_kind(exc: PreprocessConfigError) -> str:
    """Return the stable structured kind for one config failure."""
    if isinstance(exc, PreprocessPolicyError):
        return exc.error_kind.value
    return "invalid-config"


def _report_config_error(
    command: str,
    exc: PreprocessConfigError,
    *,
    json_mode: bool,
) -> None:
    """Render one config failure without leaking an exception traceback."""
    error_kind = _config_error_kind(exc)
    if json_mode:
        _emit_json_error_and_exit(command, error_kind, str(exc), 1)
    _plain(f"Preprocess config has a problem ({error_kind}): {exc}")
    raise typer.Exit(code=1) from exc


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
    json_mode: JsonMode = False,
) -> None:
    """Show the project's resolved preprocess rules in precedence order."""
    try:
        config = load_preprocess_rules(_root(ctx))
    except PreprocessConfigError as exc:
        _report_config_error("preprocess list", exc, json_mode=json_mode)
        return
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
        _plain(f"{index}. Files: {rule['pattern']}")
        _plain(f"   Priority: {rule['priority']}")
        _plain(f"   Target: {rule['target']}")
        _plain(f"   Extractor version: {rule['extractor_version']}")
        _plain(
            "   Cross-path cache reuse: "
            f"{'enabled' if rule['path_independent'] else 'disabled'}"
        )
        _plain(f"   Failure handling: {_format_failure_handling(rule['on_error'])}")
        _plain(f"   Timeout: {_format_timeout(rule['timeout_s'])}")
        _plain(f"   Invocation: {rule['command'] or rule['entry_point']}")


@preprocess_app.command(
    "check", help="Validate .vaultragpreprocess.toml and report configuration problems."
)
def handle_preprocess_check(
    ctx: typer.Context,
    json_mode: JsonMode = False,
) -> None:
    """Strictly validate the config and report the first defect."""
    try:
        config = load_preprocess_rules(_root(ctx), strict=True)
    except PreprocessConfigError as exc:
        _report_config_error("preprocess check", exc, json_mode=json_mode)
        return
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


def _format_invocation(command: str | None, entry_point: str | None) -> str:
    return command if command is not None else f"entry point {entry_point}"


def _report_store_error(command: str, exc: OSError, *, json_mode: bool) -> None:
    """Report that the approval store could not be read or written.

    Nothing was changed: the store is rewritten whole, so a failed read is
    refused rather than treated as an empty store.
    """
    message = (
        f"The preprocess approval store could not be updated ({exc}). "
        "Nothing was changed; run the command again."
    )
    if json_mode:
        _emit_json_error_and_exit(command, "approval-store-unavailable", message, 1)
    _plain(message, soft_wrap=True)
    raise typer.Exit(code=1) from exc


@preprocess_app.command(
    "approve",
    help=(
        "Approve this project's current preprocess rules so indexing may run "
        "their commands. Any later change to the rules needs approval again."
    ),
)
def handle_preprocess_approve(
    ctx: typer.Context,
    json_mode: JsonMode = False,
) -> None:
    """Record the operator's approval of the root's exact current policy."""
    root = _root(ctx)
    try:
        config = load_preprocess_rules(root, strict=True)
    except PreprocessConfigError as exc:
        _report_config_error("preprocess approve", exc, json_mode=json_mode)
        return
    digest = config.policy_digest
    rules = [
        {
            "pattern": rule.pattern,
            "invocation": _format_invocation(rule.command, rule.entry_point),
        }
        for rule in config.rules
    ]
    if digest is None or not rules:
        status = "no_rules"
    elif config.approved_for(root):
        status = "already_approved"
    else:
        try:
            approve_policy(
                root,
                digest,
                approved_at=datetime.now(UTC).isoformat(timespec="seconds"),
            )
        except OSError as exc:
            _report_store_error("preprocess approve", exc, json_mode=json_mode)
            return
        status = "approved"

    if json_mode:
        _emit_json(
            True,
            "preprocess approve",
            data={
                "status": status,
                "root": str(canonical_root_path(root)),
                "policy_digest": digest if rules else None,
                "rule_count": len(rules),
                "rules": rules,
            },
        )
        return
    if status == "no_rules":
        _plain("No preprocess rules configured; there is nothing to approve.")
        return
    word = "rule" if len(rules) == 1 else "rules"
    lead = "Already approved" if status == "already_approved" else "Approved"
    # Soft-wrapped so a path, a command or the digest stays one line a reader
    # can take whole.
    _plain(
        f"{lead}: {len(rules)} preprocess {word} for {canonical_root_path(root)}",
        soft_wrap=True,
    )
    for index, rule in enumerate(rules, start=1):
        _plain(f"{index}. Files: {rule['pattern']}", soft_wrap=True)
        _plain(f"   Invocation: {rule['invocation']}", soft_wrap=True)
    _plain(f"Policy digest: {digest}", soft_wrap=True)
    _plain(
        "These commands run with your privileges when this project is indexed. "
        f"Any change to {PREPROCESS_CONFIG_FILENAME} needs approval again.",
        soft_wrap=True,
    )
    if status == "approved":
        _print_next_action(index_command())


@preprocess_app.command(
    "revoke",
    help="Withdraw approval of this project's preprocess rules so they stop running.",
)
def handle_preprocess_revoke(
    ctx: typer.Context,
    json_mode: JsonMode = False,
) -> None:
    """Remove the operator's approval of the root's policy."""
    root = _root(ctx)
    try:
        status = "revoked" if revoke_approval(root) else "not_approved"
    except OSError as exc:
        _report_store_error("preprocess revoke", exc, json_mode=json_mode)
        return
    if json_mode:
        _emit_json(
            True,
            "preprocess revoke",
            data={"status": status, "root": str(canonical_root_path(root))},
        )
        return
    if status == "revoked":
        _plain(
            f"Revoked approval of preprocess rules for {canonical_root_path(root)}",
            soft_wrap=True,
        )
        return
    _plain("This project's preprocess rules were not approved; nothing to revoke.")


def _report_gated_run_one(
    rel: str,
    state: PreprocessHookState,
    rule_count: int,
    *,
    json_mode: bool,
) -> None:
    """Report that the root's rules are held back, so nothing ran for *rel*.

    This diagnostic command obeys the same execution gate as indexing, and
    says which half of it is closed before considering a matching rule.
    """
    if json_mode:
        _emit_json(
            True,
            "preprocess run-one",
            data={
                "matched": False,
                "path": rel,
                "gated": True,
                "mode": get_config().preprocess_mode,
                "hooks": state.value,
                "rule_count": rule_count,
            },
        )
        return
    counted = "1 rule is" if rule_count == 1 else f"{rule_count} rules are"
    if state is PreprocessHookState.DISABLED:
        # This command runs in the calling shell, so the switch to clear is
        # the shell's own rather than a service's.
        lead = "Preprocessing is off"
        remedy = "Unset VAULTSPEC_RAG_PREPROCESS=off to run them."
    else:
        lead = "Preprocess rules are not approved"
        remedy = state.remediation
    _plain(f"{lead}; {counted} configured but skipped. {remedy}", soft_wrap=True)


def _report_preprocess_no_match(rel: str, *, json_mode: bool) -> None:
    """Report that no preprocess rule matched *rel*."""
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
    json_mode: JsonMode = False,
) -> None:
    """Trial the matching preprocessor against one file for authoring/debugging."""
    root = _root(ctx)
    try:
        config = load_preprocess_rules(root)
    except PreprocessConfigError as exc:
        _report_config_error("preprocess run-one", exc, json_mode=json_mode)
        return
    src = Path(path)
    abs_path = src if src.is_absolute() else (root / src)
    try:
        rel = str(abs_path.resolve().relative_to(root.resolve())).replace("\\", "/")
    except ValueError:
        rel = str(path).replace("\\", "/")
    # Gated on the config object the rule below is taken from, so what runs is
    # what was approved.
    state = config_hook_state(root, config, get_config().preprocess_mode)
    if state in {PreprocessHookState.DISABLED, PreprocessHookState.UNAPPROVED}:
        _report_gated_run_one(rel, state, len(config.rules), json_mode=json_mode)
        return
    rule = config.match(rel)
    if rule is None:
        _report_preprocess_no_match(rel, json_mode=json_mode)
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
        _plain(f"Preprocess failed: {exc}")
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
    _plain(f"Matched rule: {rule.pattern}")
    _cli.console.print(f"Outcome: {_format_preprocess_result(result.status)}")
    if result.reason:
        _cli.console.print(f"Why: {result.reason}")
    if output is not None:
        content = _format_unit_count(unit_count) if output.units else "text output"
        _cli.console.print(
            f"Preprocessor: {output.preprocessor_id} {output.preprocessor_version}"
        )
        _cli.console.print(f"Output: {content}")


def _running_service_preprocess_mode() -> PreprocessMode | None:
    """Return the preprocess mode of the service that would run the hooks.

    Indexing runs in the service, so its mode decides whether hooks run; this
    shell's environment only decides when no service is answering.
    """
    from ..operator_state._models import HealthReport
    from ..serviceclient._discovery import _default_service_port
    from ..serviceclient._transport import _try_http_health
    from ..serviceclient._typed_state import parse_report

    port = _default_service_port()
    health = parse_report(
        HealthReport, _try_http_health(port) if port is not None else None
    )
    return health.features.preprocess_mode if health is not None else None


def _print_approval(rule_count: int, approved: bool) -> None:
    """Say whether a root's rules are approved; a root without rules has none."""
    if rule_count:
        _plain(f"Approval: {'approved' if approved else 'not approved'}")


@preprocess_app.command(
    "status",
    help="Report the preprocess mode, approval, config presence, and rule count.",
)
def handle_preprocess_status(
    ctx: typer.Context,
    json_mode: JsonMode = False,
) -> None:
    """Report the preprocess mode, approval, and the root's rule configuration."""
    root = _root(ctx)
    service_mode = _running_service_preprocess_mode()
    mode = service_mode or get_config().preprocess_mode
    config_present = (root / PREPROCESS_CONFIG_FILENAME).is_file()

    rule_count = 0
    schema_version: int | None = None
    targets: list[str] = []
    extractor_versions: list[str] = []
    path_independent_rules = 0
    policy_digest: str | None = None
    approved = False
    config_valid = True
    config_error_kind: str | None = None
    config_error_message: str | None = None
    if config_present:
        try:
            config = load_preprocess_rules(root, strict=True)
        except PreprocessConfigError as exc:
            config_valid = False
            config_error_kind = _config_error_kind(exc)
            config_error_message = str(exc)
        else:
            rule_count = len(config.rules)
            schema_version = config.schema_version
            targets = sorted({rule.target.value for rule in config.rules})
            extractor_versions = sorted(
                {rule.extractor_version for rule in config.rules}
            )
            path_independent_rules = sum(rule.path_independent for rule in config.rules)
            policy_digest = config.policy_digest
            approved = config.approved_for(root)

    state = (
        hook_state(rule_count, mode, approved=approved)
        if config_valid
        else PreprocessHookState.INVALID_CONFIG
    )

    if json_mode:
        _emit_json(
            True,
            "preprocess status",
            data={
                "mode": mode,
                "mode_source": "service" if service_mode else "local",
                "root": str(root),
                "config_present": config_present,
                "config_valid": config_valid,
                "config_error_kind": config_error_kind,
                "config_error_message": config_error_message,
                "rule_count": rule_count,
                "schema_version": schema_version,
                "targets": targets,
                "extractor_versions": extractor_versions,
                "path_independent_rules": path_independent_rules,
                "policy_digest": policy_digest,
                "approved": approved,
                "would_run": state is PreprocessHookState.ACTIVE,
                "hooks": state.value,
            },
        )
        return

    source = "the running service" if service_mode else "this shell"
    _plain(f"Preprocess mode: {mode} (from {source})")
    _plain(
        f"Config: {'present' if config_present else 'absent'}"
        f"{'' if config_valid else ' (invalid)'}"
    )
    _plain(f"Rules: {rule_count}")
    _print_approval(rule_count, approved)
    if config_error_kind is not None:
        _plain(f"Config error: {config_error_kind}: {config_error_message}")
    if schema_version is not None:
        _plain(
            f"Schema: {schema_version}; targets: {', '.join(targets) or 'none'}; "
            f"extractor versions: {', '.join(extractor_versions) or 'none'}; "
            f"cross-path cache rules: {path_independent_rules}"
        )
    remedy = f" {state.remediation}" if state.remediation else ""
    # Soft-wrapped so a command in the remedy is not folded mid-token.
    _plain(f"Hooks: {state.label}.{remedy}", soft_wrap=True)

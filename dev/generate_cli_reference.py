"""Generate ``docs/cli.md`` from the live Typer command tree."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, cast

import typer.main

from vaultspec_rag.cli._app import app

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "docs" / "cli.md"

COMMAND_NOTES: dict[str, tuple[str, ...]] = {
    "server status": (
        "A running service's summary lists its optional features: the `Typesafe:`",
        "line reports the daemon's classifier enrollment and observed usability,",
        "not the calling shell's key, and `Reranking:`, `Preprocessing:` and",
        "`File watcher:` say whether each is on. JSON includes",
        "`data.health.features` when health is available. A stopped or crashed",
        "service prints one line naming its state and how to start it. See",
        "[Typesafe enrollment](configuration.md#typesafe-enrollment)",
        "for state meanings; status never makes a paid classification call.",
    ),
    "status": (
        "The overview names the service and where it is, whether this installation",
        "is a client or an inference host, and whether it can run inference. The",
        "`Compute:` line names the machine's GPU and the environment's torch build",
        "separately, and a `Fix:` line appears only when the environment is broken,",
        "never for a client that has no GPU work to do. The project's preprocessing",
        "hooks are always shown; Typesafe, reranking and the file watcher are shown",
        "when a service answers. A service from another release is reported as a",
        "release mismatch rather than read around.",
    ),
    "server start": (
        "Successful starts and already-running responses include Typesafe enrollment",
        "from the daemon (`Typesafe:` in human output, `data.typesafe` in JSON).",
        "Set the dedicated key before launching the server; attaching to an existing",
        "server does not change its environment. Enrollment alone does not confirm a",
        "valid, funded key: the first search evaluation establishes usability. See",
        "[Typesafe enrollment](configuration.md#typesafe-enrollment).",
    ),
}


def _commands(command: Any) -> dict[str, Any]:
    return cast("dict[str, Any]", getattr(command, "commands", None) or {})


def _paths(
    command: Any, prefix: tuple[str, ...] = ()
) -> list[tuple[tuple[str, ...], Any]]:
    found: list[tuple[tuple[str, ...], Any]] = []
    for name, child in _commands(command).items():
        path = (*prefix, name)
        if _commands(child):
            found.extend(_paths(child, path))
        else:
            found.append((path, child))
    return found


def _cell(value: object) -> str:
    text = str(value).replace("\b", " ").replace("|", "\\|")
    return " ".join(text.split())


def _summary(value: object) -> str:
    text = str(value or "").split("\b", 1)[0].strip()
    return _cell(text)


def _default(param: Any) -> str:
    value = getattr(param, "default", None)
    if value is None:
        return "required" if getattr(param, "required", False) else "-"
    if value is False:
        return "off"
    if value is True:
        return "on"
    return _cell(value)


def _type_name(param: Any) -> str:
    value = getattr(getattr(param, "type", None), "name", None)
    return _cell(value or "value")


def _parameter_rows(command: Any, *, options: bool) -> list[str]:
    rows: list[str] = []
    for param in command.params:
        opts = [*getattr(param, "opts", ()), *getattr(param, "secondary_opts", ())]
        is_option = getattr(param, "param_type_name", "") != "argument"
        if is_option != options:
            continue
        name = ", ".join(f"`{opt}`" for opt in opts) if opts else f"`{param.name}`"
        help_text = _cell(getattr(param, "help", "") or "-")
        required = "yes" if getattr(param, "required", False) else "no"
        rows.append(
            f"| {name} | {_type_name(param)} | {required} "
            f"| {_default(param)} | {help_text} |"
        )
    return rows


def _table(command: Any, *, options: bool) -> list[str]:
    rows = _parameter_rows(command, options=options)
    if not rows:
        return ["None.", ""]
    return [
        "| Name | Type | Required | Default | Description |",
        "| --- | --- | --- | --- | --- |",
        *rows,
        "",
    ]


def _command_tree(commands: list[tuple[tuple[str, ...], Any]]) -> list[str]:
    lines: list[str] = []
    previous: tuple[str, ...] = ()
    for path, _ in commands:
        shared = 0
        for left, right in zip(previous, path, strict=False):
            if left != right:
                break
            shared += 1
        for depth in range(shared, len(path)):
            partial = path[: depth + 1]
            label = " ".join(partial)
            indent = "  " * depth
            if depth == len(path) - 1:
                lines.append(
                    f"{indent}- [{path[-1]}](#{label.replace(' ', '-').lower()})"
                )
            else:
                lines.append(f"{indent}- **{path[-1]}**")
        previous = path
    return lines


def render() -> str:
    root = typer.main.get_command(app)
    commands = _paths(root)
    lines = [
        "# vaultspec-rag CLI reference",
        "",
        "::::{container} vs-cli-reference",
        "",
        "Generated from the live command surface. Each entry lists the command's "
        "arguments, options, types, defaults, and help text.",
        "",
        "## Global options",
        "",
        *_table(root, options=True),
        "## Commands",
        "",
    ]
    lines.extend([*_command_tree(commands), ""])
    for path, command in commands:
        label = " ".join(path)
        usage = f"vaultspec-rag {label}"
        lines.extend(
            [
                f"## {label}",
                "",
                _summary(getattr(command, "help", "")),
                "",
                *(COMMAND_NOTES.get(label, ())),
                *([""] if label in COMMAND_NOTES else []),
                "```bash",
                usage,
                "```",
                "",
                "### Arguments",
                "",
                *_table(command, options=False),
                "### Options",
                "",
                *_table(command, options=True),
            ]
        )
    lines.extend(["::::", ""])
    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    expected = render()
    if args.check:
        if OUTPUT.read_text(encoding="utf-8") != expected:
            print(f"stale: {OUTPUT.relative_to(ROOT)}")
            return 1
        print(f"current: {OUTPUT.relative_to(ROOT)}")
        return 0
    OUTPUT.write_text(expected, encoding="utf-8", newline="\n")
    print(f"generated: {OUTPUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

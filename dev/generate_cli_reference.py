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


def _commands(command: Any) -> dict[str, Any]:
    return cast("dict[str, Any]", getattr(command, "commands", None) or {})


def _paths(command: Any, prefix: tuple[str, ...] = ()) -> list[tuple[tuple[str, ...], Any]]:
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


def _parameter_rows(command: Any, *, options: bool) -> list[str]:
    rows: list[str] = []
    for param in command.params:
        opts = [*getattr(param, "opts", ()), *getattr(param, "secondary_opts", ())]
        is_option = getattr(param, "param_type_name", "") != "argument"
        if is_option != options:
            continue
        name = ", ".join(f"`{opt}`" for opt in opts) if opts else f"`{param.name}`"
        help_text = _cell(getattr(param, "help", "") or "-")
        rows.append(f"| {name} | {_default(param)} | {help_text} |")
    return rows


def _table(command: Any, *, options: bool) -> list[str]:
    rows = _parameter_rows(command, options=options)
    if not rows:
        return ["None.", ""]
    return ["| Name | Default | Description |", "| --- | --- | --- |", *rows, ""]


def render() -> str:
    root = typer.main.get_command(app)
    commands = _paths(root)
    lines = [
        "# vaultspec-rag CLI reference",
        "",
        "Generated from the live command surface. Run `python -m dev.generate_cli_reference` after changing a command, argument, option, default, or help string.",
        "",
        "## Global options",
        "",
        *_table(root, options=True),
        "## Commands",
        "",
    ]
    for path, _ in commands:
        label = " ".join(path)
        lines.append(f"- [{label}](#{label.replace(' ', '-').lower()})")
    lines.append("")
    for path, command in commands:
        label = " ".join(path)
        usage = f"vaultspec-rag {label}"
        lines.extend(
            [
                f"## {label}",
                "",
                _summary(getattr(command, "help", "")),
                "",
                f"`{usage}`",
                "",
                "### Arguments",
                "",
                *_table(command, options=False),
                "### Options",
                "",
                *_table(command, options=True),
            ]
        )
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

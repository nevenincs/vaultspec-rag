"""Guards that rag's own help surface survives another package's import.

vaultspec-core's CLI publishes a POSIX metavar grammar for positional
arguments, and the only seam Typer offers for that is a module global: core
rebinds ``typer.main.TyperArgument`` for the whole interpreter the moment
``vaultspec_core.cli`` is imported. Rag builds its command tree lazily, at
the first render, so whichever of the two happens first decides how rag's
own ``--help`` dresses a positional - ``{project}`` or ``PROJECT``.

That made a real failure. Rag's help tests asserted the brace form, which
held when they ran alone and stopped holding in a full lane the moment one
other test module imported core's command tree at collection. The
assertions were reporting what else the process had imported, not what rag
publishes.

What rag actually promises about these arguments is the name: the CLI takes
a project, and nothing in the surface calls it a root. That survives either
grammar, and the runs below hold it to both - the dressed and the
undressed - in one process, in the order that used to break it.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
from typer.testing import CliRunner

from ..cli import app
from ._cli_helpers import usage_metavar

pytestmark = [pytest.mark.unit]

#: The positional-taking commands whose language the help tests assert.
_PROJECT_COMMANDS = [
    ["server", "projects", "unload", "--help"],
    ["server", "updates", "start", "--help"],
    ["server", "updates", "stop", "--help"],
    ["server", "updates", "timing", "--help"],
]


@pytest.mark.parametrize("argv", _PROJECT_COMMANDS)
def test_the_positional_is_named_project_after_core_cli_is_imported(
    argv: list[str],
) -> None:
    """Importing another package's command tree must not rename rag's argument.

    The import is the whole point of the test and is deliberately performed
    inside it: it rebinds an interpreter-wide global, and doing it here
    reproduces the exact sequence - rag rendered, core imported, rag
    rendered again - that a full lane produces by collection order alone.
    """
    runner = CliRunner()

    before = runner.invoke(app, argv)
    assert before.exit_code == 0, before.output
    assert usage_metavar(before.output) == "project"

    import vaultspec_core.cli

    assert vaultspec_core.cli.app is not None

    after = runner.invoke(app, argv)
    assert after.exit_code == 0, after.output
    assert usage_metavar(after.output) == "project"
    assert "Project root" not in after.output


@pytest.mark.timeout(120)
@pytest.mark.parametrize("argv", _PROJECT_COMMANDS)
def test_the_positional_is_named_project_when_core_is_imported_first(
    argv: list[str],
) -> None:
    """The order that actually breaks it, in an interpreter that has not run yet.

    A rebinding of the argument class only reaches parameters built after
    it, and this process built rag's tree at its first render - so the
    damaging order, core's import ahead of rag's first render, is
    unreachable from inside a lane that has already rendered once. A fresh
    interpreter is the only place it exists.
    """
    probe = textwrap.dedent(
        f"""
        import vaultspec_core.cli  # noqa: F401 - the rebinding under test
        from typer.testing import CliRunner
        from vaultspec_rag.cli import app

        result = CliRunner().invoke(app, {argv!r})
        assert result.exit_code == 0, result.output
        print(result.output.splitlines()[0])
        """
    )
    completed = subprocess.run(
        [sys.executable, "-c", probe],
        capture_output=True,
        check=True,
        cwd=str(Path(__file__).resolve().parents[2]),
        encoding="utf-8",
        errors="replace",
    )
    usage = completed.stdout.strip().splitlines()[-1]
    assert usage_metavar(usage) == "project", usage

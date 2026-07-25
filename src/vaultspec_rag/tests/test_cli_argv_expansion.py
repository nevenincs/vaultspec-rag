"""Guards that the command line reaches the search parser verbatim.

These tests must run the CLI as a real subprocess. The in-process runner every
other CLI test uses hands the parser an explicit argument list, and the parser
only rewrites arguments it reads from the process command line itself - so the
whole rewriting pass is unreachable from an in-process test, and a regression
here would pass the rest of the suite untouched.

The rewriting is also cwd-relative: a pattern only expands if it matches
something next to the running process. Each subprocess therefore runs from a
workspace seeded with files the pattern really matches, so a regression
reproduces instead of silently passing.

These guards were checked in both directions. Re-enabling the rewriting pass at
the single invocation site fails all three on their own assertions: the pattern
case on ``src/**`` having become ``src\\alpha.py src\\beta.py``, the variable
case on the reference resolving to the value exported below, and the home case
on ``~nosuchuser`` resolving to an absolute path. Restoring it passes them.
Keep the assertions this specific - a looser matcher passes on the wrong branch.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from ..search._result_shaping import filter_raw_codebase_results

if TYPE_CHECKING:
    from collections.abc import Iterator

pytestmark = [pytest.mark.unit]

#: Set in the subprocess environment so the variable-reference case does not
#: depend on which variables the host happens to export.
_PROBE_VAR = "VAULTSPEC_RAG_ARGV_PROBE"
_PROBE_VALUE = "substituted-before-the-cli-saw-it"


@pytest.fixture
def argv_workspace() -> Iterator[Path]:
    """A short-pathed workspace whose ``src`` tree a glob really matches."""
    root = Path(tempfile.mkdtemp(prefix="vsargv"))
    try:
        (root / ".vault").mkdir()
        (root / ".vaultspec").mkdir()
        source = root / "src"
        source.mkdir()
        (source / "alpha.py").write_text("alpha\n", encoding="utf-8")
        (source / "beta.py").write_text("beta\n", encoding="utf-8")
        yield root
    finally:
        shutil.rmtree(root, ignore_errors=True)


def _run_search(workspace: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """Run ``search`` from inside ``workspace`` with isolated runtime dirs."""
    env = {
        **os.environ,
        _PROBE_VAR: _PROBE_VALUE,
        "NO_COLOR": "1",
        "FORCE_COLOR": "0",
        # Never let a run reach the operator's own service directory or
        # storage, even on the paths that exit before contacting either.
        "VAULTSPEC_RAG_STATUS_DIR": str(workspace / "st"),
        "VAULTSPEC_RAG_QDRANT_STORAGE_DIR": str(workspace / "qd"),
    }
    return subprocess.run(
        [sys.executable, "-m", "vaultspec_rag", "search", *args],
        capture_output=True,
        check=False,
        cwd=str(workspace),
        env=env,
        encoding="utf-8",
        errors="replace",
    )


class TestCommandLineReachesTheParserVerbatim:
    """The command line is data, not a second shell to be re-run."""

    @pytest.mark.timeout(120)
    def test_repeated_pattern_option_keeps_its_glob(self, argv_workspace: Path) -> None:
        """``--include-path`` keeps the glob instead of the files it matched.

        Pairing the code-only filter with ``--type vault`` gives a decision
        that is reached the moment parsing succeeds, so the outcome depends on
        the command line and nothing else. Rewritten, the pattern becomes the
        two seeded files: the first is taken as the option's value and the rest
        arrive as stray positionals, which the command reports as unexpected
        options before any filter is validated.
        """
        result = _run_search(
            argv_workspace,
            "anything",
            "--type",
            "vault",
            "--include-path",
            "src/**",
            "--json",
        )

        # Names the cause directly: a seeded filename in the output can only
        # have come from the pattern being expanded against the workspace.
        assert "alpha.py" not in result.stdout, (
            "--include-path was expanded into the files it matched; the glob "
            f"must reach the parser verbatim. stdout={result.stdout!r}"
        )
        assert "beta.py" not in result.stdout, (
            "--include-path was expanded into the files it matched; the glob "
            f"must reach the parser verbatim. stdout={result.stdout!r}"
        )
        payload = json.loads(result.stdout)
        assert payload["error"] == "invalid_filter_for_search_type"
        assert payload["offending"] == ["--include-path"]
        assert result.returncode == 2

    @pytest.mark.parametrize(
        "supplied",
        [
            pytest.param(f"%{_PROBE_VAR}%", id="variable-reference"),
            pytest.param("~nosuchuser", id="home-shorthand"),
        ],
    )
    @pytest.mark.timeout(120)
    def test_option_value_is_not_substituted(
        self,
        argv_workspace: Path,
        supplied: str,
    ) -> None:
        """A value carrying shell shorthand arrives exactly as typed.

        ``--prefer`` rejects any value outside its three choices and quotes the
        value it received, which makes the value the run actually parsed
        directly observable. A variable reference and a home shorthand are the
        two substitutions that apply to every argument, pattern or not, so a
        query or an identifier is exposed to them just as a path option is.
        """
        result = _run_search(
            argv_workspace,
            "anything",
            "--type",
            "code",
            "--prefer",
            supplied,
            "--json",
        )

        payload = json.loads(result.stdout)
        assert payload["error"] == "invalid_prefer_value"
        # Substitution resolves either form to an absolute path, so any value
        # other than the one typed is the rewriting pass showing through.
        assert payload["value"] == supplied, (
            f"--prefer value was rewritten to {payload['value']!r}; the "
            "command line must reach the parser verbatim"
        )
        assert result.returncode == 2


class TestGlobPatternFiltersRealResults:
    """The pattern the CLI now delivers is the one that does the filtering."""

    _RAW_RESULTS: tuple[dict[str, object], ...] = (
        {"path": "src/vaultspec_rag/indexer/_chunking.py", "score": 0.91},
        {"path": "src/vaultspec_rag/indexer/_file_state.py", "score": 0.88},
        {"path": "src/vaultspec_rag/cli/_search.py", "score": 0.84},
        {"path": "tests/test_indexer.py", "score": 0.71},
    )

    def _paths(self, results: list[dict[str, object]]) -> list[str]:
        return [str(r["path"]) for r in results]

    def test_include_glob_keeps_only_the_named_subtree(self) -> None:
        kept = filter_raw_codebase_results(
            list(self._RAW_RESULTS),
            ["src/vaultspec_rag/indexer/*"],
            [],
        )

        assert self._paths(kept) == [
            "src/vaultspec_rag/indexer/_chunking.py",
            "src/vaultspec_rag/indexer/_file_state.py",
        ]

    def test_exclude_glob_drops_the_named_subtree(self) -> None:
        kept = filter_raw_codebase_results(
            list(self._RAW_RESULTS),
            [],
            ["tests/*"],
        )

        assert "tests/test_indexer.py" not in self._paths(kept)
        assert len(kept) == 3

    def test_a_matched_file_list_is_not_the_filter_the_pattern_was(self) -> None:
        """Why a rewritten pattern is worse than a rejected one.

        Substitution replaces a pattern with the files that happened to sit
        next to the caller when the command ran. The index is not that tree: it
        holds every file the project ever indexed, including ones the caller's
        directory does not contain. The substituted list can only ever name
        what was there, so anything else the pattern covers is dropped without
        a word - a narrower search that still returns results and so reads as a
        successful one.
        """
        pattern = "src/vaultspec_rag/indexer/*"
        # What substitution yields when only one of the two indexed files is
        # present next to the caller.
        substituted = ["src/vaultspec_rag/indexer/_chunking.py"]

        by_pattern = filter_raw_codebase_results(list(self._RAW_RESULTS), [pattern], [])
        by_substitution = filter_raw_codebase_results(
            list(self._RAW_RESULTS), substituted, []
        )

        assert self._paths(by_pattern) == [
            "src/vaultspec_rag/indexer/_chunking.py",
            "src/vaultspec_rag/indexer/_file_state.py",
        ]
        assert self._paths(by_substitution) == [
            "src/vaultspec_rag/indexer/_chunking.py"
        ], "a substituted file list silently drops what the pattern covered"

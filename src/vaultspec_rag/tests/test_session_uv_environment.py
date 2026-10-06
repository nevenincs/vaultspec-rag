"""A session on a foreign interpreter keeps uv off the checkout's environment.

The session's audit hook refuses a uv launch this process makes against an
environment no test created. It cannot see a launch made by a child, so the
session start also names a project environment under its own temporary tree
whenever uv could otherwise find the checkout's ``.venv`` unusable and replace
it: whenever the interpreter running the session is not that environment.

The decision is a function of three paths and one existing value, and is
exercised here with real directories. Each case records the mutation it was
seen to fail under, run alone, with the mutation removed again before the
next.
"""

from __future__ import annotations

import os
import sys
from typing import TYPE_CHECKING

import pytest

from ._singleton_root_fixtures import uv_project_environment_redirect

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.unit

#: uv's own name for where a project's environment lives.
_PROJECT_ENVIRONMENT = "UV_PROJECT_ENVIRONMENT"


def test_a_session_on_the_checkouts_own_environment_changes_nothing(
    tmp_path: Path,
) -> None:
    """The checkout's own ``.venv`` is left as uv's project environment.

    However the two paths are spelled: the interpreter reports its prefix as
    it was launched, which need not be how the checkout was named.

    Mutation: comparing the paths as spelled returned a redirect for the
    second spelling, and dropping the comparison returned one for the first;
    restored, it passed.
    """
    checkout = tmp_path / "checkout"
    (checkout / ".venv").mkdir(parents=True)
    (checkout / "src").mkdir()

    for prefix in (checkout / ".venv", checkout / "src" / ".." / ".venv"):
        assert (
            uv_project_environment_redirect(
                prefix=prefix,
                rootdir=checkout,
                configured=None,
                scratch=tmp_path / "scratch",
            )
            is None
        )


def test_a_session_on_any_other_interpreter_names_its_own_environment(
    tmp_path: Path,
) -> None:
    """Another interpreter over the checkout must not reach its ``.venv``.

    The path is only named. uv builds the environment when something first
    asks for one, and refuses a directory it finds occupied by anything else.

    Mutation: returning no path failed the first assertion; restored, it
    passed.
    """
    checkout = tmp_path / "checkout"
    (checkout / ".venv").mkdir(parents=True)
    elsewhere = tmp_path / "elsewhere" / ".venv"
    elsewhere.mkdir(parents=True)
    scratch = tmp_path / "scratch"

    redirect = uv_project_environment_redirect(
        prefix=elsewhere, rootdir=checkout, configured=None, scratch=scratch
    )

    assert redirect is not None
    assert redirect.parent == scratch
    assert not redirect.exists()


def test_an_environment_the_operator_named_is_left_alone(tmp_path: Path) -> None:
    """A value already set wins, whichever interpreter the session runs from.

    Mutation: with the configured value ignored this returned the redirect;
    restored, it passed.
    """
    checkout = tmp_path / "checkout"
    (checkout / ".venv").mkdir(parents=True)
    elsewhere = tmp_path / "elsewhere" / ".venv"
    elsewhere.mkdir(parents=True)

    assert (
        uv_project_environment_redirect(
            prefix=elsewhere,
            rootdir=checkout,
            configured=str(tmp_path / "operators-own"),
            scratch=tmp_path / "scratch",
        )
        is None
    )


def test_this_session_named_an_environment_unless_it_runs_from_the_checkouts(
    request: pytest.FixtureRequest, tmp_path: Path
) -> None:
    """The session start applies the decision, for every process it starts.

    Nothing is asserted about a session running from the checkout's own
    environment: there the variable is the operator's to set or leave unset,
    so this can only fail on a session running from some other interpreter.

    Mutation: with the session start discarding the decision, a session run
    from another checkout's interpreter failed this assertion with the
    variable unset; restored, it passed.
    """
    left_alone = (
        uv_project_environment_redirect(
            prefix=sys.prefix,
            rootdir=request.config.rootpath,
            configured=None,
            scratch=tmp_path,
        )
        is None
    )
    assert left_alone or os.environ.get(_PROJECT_ENVIRONMENT), (
        "this session runs from an interpreter that is not the checkout's own "
        "environment and named no project environment for uv, so a uv process "
        "started by a child can create or replace the checkout's .venv"
    )

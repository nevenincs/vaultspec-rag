"""Unit tests for the operator-supplied Qdrant binary settings.

A binary this package did not download has no digest compiled in to check it
against, so the operator declares one. The path and the digest are two halves
of one setting, and what these tests hold is that neither half is ever usable
alone: a path with no digest would be a binary run unverified, which is the
one thing the settings must make impossible to configure.

The refusal reaches every operator who already exports the path, on the first
command after an upgrade, so its wording is tested too: it has to name both
variables and say how to produce the digest without a trip to the manual.

Every case drives the real settings object over the real process environment;
the command-line cases run the real entry point in a fresh interpreter.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from typing import TYPE_CHECKING

import pytest

from ..config._registry import entry
from ..config._settings import collect_environment_problems, get_config
from ..config._types import EnvVar, OperatorBinary, OperatorBinaryPairError
from ._config_fixtures import reset_config
from ._scaffold import restore_env, set_env

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

pytestmark = [pytest.mark.unit]

_PATH_VAR = EnvVar.QDRANT_BINARY
_DIGEST_VAR = EnvVar.QDRANT_BINARY_SHA256
_PAIR = (_PATH_VAR, _DIGEST_VAR)

_BINARY = "/opt/qdrant/qdrant"
_DIGEST = "0123456789abcdef" * 4

#: The opening every pairing refusal shares, whichever half is missing.
_TOGETHER = f"{_PATH_VAR.value} and {_DIGEST_VAR.value} must be set together"

#: How to produce the digest, per platform. An operator meeting the refusal
#: for the first time needs one of these and nothing else.
_DIGEST_COMMANDS = (
    "Get-FileHash -Algorithm SHA256 <path>",
    "sha256sum <path>",
    "shasum -a 256 <path>",
)

_DIGEST_SHAPE = "a SHA256 digest of 64 hexadecimal characters"


@pytest.fixture
def clean_pair() -> Iterator[None]:
    """Run from an environment that sets neither half of the pair."""
    saved = {var: os.environ.pop(var.value, None) for var in _PAIR}
    reset_config()
    try:
        yield
    finally:
        for var, previous in saved.items():
            restore_env(var, previous)
        reset_config()


def _configure(path: str | None, digest: str | None) -> None:
    """Set the pair as given and drop the settings cached before it."""
    for var, value in ((_PATH_VAR, path), (_DIGEST_VAR, digest)):
        if value is None:
            os.environ.pop(var.value, None)
        else:
            os.environ[var.value] = value
    reset_config()


@pytest.mark.usefixtures("clean_pair")
def test_unset_selects_the_managed_install() -> None:
    cfg = get_config()

    assert cfg.qdrant_operator_binary is None
    assert cfg.qdrant_binary_sha256 is None
    assert collect_environment_problems(None) == []


@pytest.mark.usefixtures("clean_pair")
def test_both_halves_resolve_as_one_value() -> None:
    _configure(_BINARY, _DIGEST)

    assert get_config().qdrant_operator_binary == OperatorBinary(_BINARY, _DIGEST)


@pytest.mark.usefixtures("clean_pair")
def test_the_digest_is_accepted_in_either_case_and_returned_lowered() -> None:
    """Upper case is what PowerShell prints, so it must not be refused.

    The reader compares against a computed digest, which is lower case, so
    the setting hands it that form. Mutation: returning the digest without
    lowering it failed this assertion with the upper-case text; restored, it
    passed.
    """
    _configure(_BINARY, f"  {_DIGEST.upper()}\t")

    resolved = get_config().qdrant_operator_binary

    assert resolved is not None
    assert resolved.sha256 == _DIGEST


@pytest.mark.parametrize("digest", [None, "", "   "], ids=["unset", "empty", "blank"])
@pytest.mark.usefixtures("clean_pair")
def test_a_path_without_a_digest_is_refused_naming_both_and_the_remedy(
    digest: str | None,
) -> None:
    """A path alone never builds a configuration, so it can never be run.

    One problem is reported, and it is self-sufficient: both variables, and
    the command that prints the digest on each platform.

    Mutations. With the pairing dropped from the construction-time checks,
    this failed DID NOT RAISE. With the missing-digest branch removed from
    the accessor, it failed DID NOT RAISE as well, and the accessor returned
    a path with no digest. Restored after each, it passed.
    """
    _configure(_BINARY, digest)

    with pytest.raises(OperatorBinaryPairError) as excinfo:
        get_config()

    message = str(excinfo.value)
    assert message.startswith(_TOGETHER)
    assert f"{_DIGEST_VAR.value} does not declare its SHA256" in message
    for command in _DIGEST_COMMANDS:
        assert command in message
    assert collect_environment_problems(None) == [message]


@pytest.mark.usefixtures("clean_pair")
def test_a_digest_without_a_path_is_refused_naming_both() -> None:
    """A digest alone verifies nothing, and is as much a mistake as the reverse.

    Mutation: with the missing-path branch removed from the accessor this
    failed DID NOT RAISE; restored, it passed.
    """
    _configure(None, _DIGEST)

    with pytest.raises(OperatorBinaryPairError) as excinfo:
        get_config()

    message = str(excinfo.value)
    assert message.startswith(_TOGETHER)
    assert f"{_PATH_VAR.value} names no Qdrant binary" in message
    assert collect_environment_problems(None) == [message]


@pytest.mark.usefixtures("clean_pair")
def test_only_the_half_pair_refusal_carries_its_own_type() -> None:
    """The code that resolves the binary tells this refusal from every other.

    It reports a half pair as a fault of the binary configuration, and must
    not relabel an unrelated unusable setting as one. So the type is raised
    for the half pair alone, including when a configuration is built; a
    digest that is not a digest stays an ordinary refusal; and a half pair
    among several problems is the ordinary collective refusal, because it is
    then a report about several settings.

    Mutation: with the single problem re-raised as a copy of its text, the
    construction-time half pair arrived as a plain ``ValueError`` and the
    first assertion failed; restored, it passed.
    """
    _configure(_BINARY, None)
    with pytest.raises(ValueError) as lone:
        get_config()
    assert type(lone.value) is OperatorBinaryPairError

    _configure(_BINARY, "not-a-digest")
    with pytest.raises(ValueError) as malformed:
        get_config()
    assert type(malformed.value) is ValueError

    _configure(_BINARY, None)
    previous = set_env(EnvVar.PORT, "notaport")
    try:
        reset_config()
        with pytest.raises(ValueError) as several:
            get_config()
    finally:
        restore_env(EnvVar.PORT, previous)
        reset_config()
    assert type(several.value) is ValueError
    assert _TOGETHER in str(several.value)
    assert EnvVar.PORT.value in str(several.value)


@pytest.mark.parametrize(
    "digest",
    [
        _DIGEST[:-1],
        _DIGEST + "0",
        "g" + _DIGEST[1:],
        "sha256:" + _DIGEST,
        _DIGEST[:32] + " " + _DIGEST[32:],
    ],
    ids=["too-short", "too-long", "not-hex", "prefixed", "inner-whitespace"],
)
@pytest.mark.usefixtures("clean_pair")
def test_a_value_that_is_not_a_digest_is_refused_as_one_problem(digest: str) -> None:
    """A malformed digest is refused for its shape, once, and not as a missing half.

    It could never match a hashed file, so refusing it at startup beats a
    mismatch at the first spawn. Mutation: with the digest's declared shape
    removed from the bounds table every case failed on the problem count (0
    in place of 1); restored, all passed.
    """
    _configure(_BINARY, digest)

    problems = collect_environment_problems(None)

    assert len(problems) == 1
    assert _DIGEST_VAR.value in problems[0]
    assert "qdrant_binary_sha256" in problems[0]
    assert _DIGEST_SHAPE in problems[0]
    assert _TOGETHER not in problems[0]


@pytest.mark.usefixtures("clean_pair")
def test_the_pair_is_rechecked_on_every_read() -> None:
    """A configuration built with both halves still refuses once one is gone.

    Settings resolve from the live environment, so the object that passed at
    construction is no proof about a later read. That holds for a read of the
    path on its own as much as for the pair, or the path would be a way round
    the digest.

    Mutation: with the path read resolved generically instead of through the
    pair, the second refusal below failed DID NOT RAISE, the bare path coming
    back with no digest behind it; restored, it passed.
    """
    _configure(_BINARY, _DIGEST)
    cfg = get_config()
    assert cfg.qdrant_operator_binary is not None
    assert cfg.qdrant_binary == _BINARY
    assert cfg.qdrant_binary_sha256 == _DIGEST

    del os.environ[_DIGEST_VAR.value]

    with pytest.raises(ValueError, match=_TOGETHER):
        _ = cfg.qdrant_operator_binary
    with pytest.raises(ValueError, match=_TOGETHER):
        _ = cfg.qdrant_binary


@pytest.mark.parametrize("var", _PAIR, ids=lambda v: v.value)
def test_neither_half_can_be_supplied_by_a_workspace_file(var: EnvVar) -> None:
    """A project may not name a binary for the host to run, nor vouch for one.

    Neither is eligible for a workspace ``.env`` or persistable into the
    project store. The digest is not a secret either: it is echoed in the
    refusal so the operator can see what was read.
    """
    declared = entry(var)

    assert not declared.workspace_dotenv
    assert not declared.persistable
    assert not declared.secret


def _run_cli(tmp_path: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """Run the real command-line entry with a path set and no digest."""
    env = {
        name: value
        for name, value in os.environ.items()
        if name not in {_PATH_VAR.value, _DIGEST_VAR.value}
    }
    env[_PATH_VAR.value] = _BINARY
    env[EnvVar.STATUS_DIR.value] = str(tmp_path / "status")
    env[EnvVar.QDRANT_STORAGE_DIR.value] = str(tmp_path / "storage")
    return subprocess.run(
        [sys.executable, "-m", "vaultspec_rag", *args],
        capture_output=True,
        text=True,
        check=False,
        stdin=subprocess.DEVNULL,
        env=env,
        cwd=tmp_path,
        timeout=180,
    )


@pytest.mark.parametrize("option", ["--help", "--version"])
def test_root_help_and_version_still_answer_under_the_refusal(
    tmp_path: Path, option: str
) -> None:
    """The two answers that need no configuration are not held hostage by it.

    This is the behaviour every other settings refusal already has, matched
    rather than extended: an operator locked out by the upgrade can still ask
    the tool what it is and how it is used.
    """
    proc = _run_cli(tmp_path, option)

    assert proc.returncode == 0, proc.stderr
    assert _TOGETHER not in proc.stderr


def test_a_command_is_refused_before_it_runs_with_the_whole_remedy(
    tmp_path: Path,
) -> None:
    """Every command stops at the door, on standard error, with exit status 1."""
    proc = _run_cli(tmp_path, "server", "status")

    assert proc.returncode == 1
    assert proc.stdout == ""
    assert proc.stderr.startswith(f"Error: {_TOGETHER}")
    for command in _DIGEST_COMMANDS:
        assert command in proc.stderr


def test_a_json_caller_gets_the_refusal_as_one_envelope(tmp_path: Path) -> None:
    """Machine output stays machine output: one error envelope, nothing else."""
    proc = _run_cli(tmp_path, "server", "status", "--json")

    assert proc.returncode == 1
    envelope = json.loads(proc.stdout)
    assert _TOGETHER in json.dumps(envelope)
    assert _TOGETHER not in proc.stderr

"""Where a credential may come from, and which process is allowed to read it.

A workspace ``.env`` is repository content. Opening it to a globally installed
tool would let a cloned repository configure that tool, so the framework opens
it only for a process running the workspace's own interpreter, in a workspace
that declares this package as a project dependency. What this suite pins is
that the two halves of that gate are both live here, that the session
environment still outranks the file, and that the one process which must not
read any file - the resident daemon, which serves many roots at once - is
handed the resolved value instead.

Real workspaces on disk, real declaration files, real ``.env`` files, and
explicit environment mappings. The interpreter half of the gate is driven by
passing a prefix rather than by moving this interpreter, which is the one
input a test cannot arrange for real.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

import pytest
from vaultspec_core.config import CredentialSource
from vaultspec_core.core.enums import InstallMode
from vaultspec_core.core.workspace_mode import (
    PackageDeclaration,
    write_package_declaration,
)

from ..cli._process import _build_service_child_env, _ServiceChildEnvRequest
from ..config._credentials import (
    DAEMON_CREDENTIALS,
    credential_assignments,
    workspace_credential,
)
from ..config._registry import PACKAGE, entry
from ..config._types import EnvVar
from ._import_probe import assert_fresh_import_excludes, import_probe_source
from ._scaffold import restore_env, set_env

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

pytestmark = [pytest.mark.unit]

_DOTENV_KEY = "key-from-the-workspace-file"
_SESSION_KEY = "key-from-the-session"


def _workspace(root: Path, *, package: str, mode: InstallMode) -> Path:
    """Build a real workspace declaring *mode* for *package*."""
    root.mkdir(parents=True, exist_ok=True)
    write_package_declaration(root, package, PackageDeclaration(install_mode=mode))
    return root


def _dotenv(root: Path, var: EnvVar, value: str = _DOTENV_KEY) -> Path:
    """Write a real workspace ``.env`` carrying one variable."""
    (root / ".env").write_text(
        f"# workspace credentials\n{var.value}={value}\n", encoding="utf-8"
    )
    return root


@pytest.fixture
def no_session_credentials() -> Iterator[None]:
    """Clear the credentials from this process's own environment."""
    saved = {var: os.environ.pop(var.value, None) for var in DAEMON_CREDENTIALS}
    try:
        yield
    finally:
        for var, previous in saved.items():
            restore_env(var, previous)


@pytest.mark.parametrize("var", DAEMON_CREDENTIALS, ids=lambda v: v.value)
def test_a_dependency_workspace_supplies_the_key_to_its_own_interpreter(
    tmp_path: Path, var: EnvVar
) -> None:
    """Both halves of the gate satisfied: the file answers."""
    root = _dotenv(
        _workspace(tmp_path, package=PACKAGE, mode=InstallMode.DEPENDENCY), var
    )

    from vaultspec_core.config import resolve_credential

    credential = resolve_credential(
        entry(var), root, {}, interpreter_prefix=root / ".venv"
    )

    assert credential is not None
    assert credential.key == _DOTENV_KEY
    assert credential.source is CredentialSource.DOTENV


@pytest.mark.parametrize("var", DAEMON_CREDENTIALS, ids=lambda v: v.value)
def test_an_interpreter_outside_the_workspace_never_opens_the_file(
    tmp_path: Path, var: EnvVar
) -> None:
    """A globally installed tool pointed at a clone reads nothing from it.

    This is the half of the gate the install mode alone cannot supply: the
    mode is resolved from files the repository itself writes, so a freshly
    cloned repository could otherwise declare its way into configuring a tool
    that merely happens to be pointed at it.
    """
    root = _dotenv(
        _workspace(tmp_path / "project", package=PACKAGE, mode=InstallMode.DEPENDENCY),
        var,
    )
    outside = tmp_path / "tools" / "venv"
    outside.mkdir(parents=True)

    from vaultspec_core.config import resolve_credential

    assert resolve_credential(entry(var), root, {}, interpreter_prefix=outside) is None


@pytest.mark.parametrize("var", DAEMON_CREDENTIALS, ids=lambda v: v.value)
def test_a_tool_mode_workspace_never_opens_the_file(
    tmp_path: Path, var: EnvVar
) -> None:
    """A workspace that does not run this package as a project dependency."""
    root = _dotenv(_workspace(tmp_path, package=PACKAGE, mode=InstallMode.TOOL), var)

    from vaultspec_core.config import resolve_credential

    assert (
        resolve_credential(entry(var), root, {}, interpreter_prefix=root / ".venv")
        is None
    )


@pytest.mark.parametrize("var", DAEMON_CREDENTIALS, ids=lambda v: v.value)
def test_the_session_outranks_the_file(tmp_path: Path, var: EnvVar) -> None:
    """An exported key wins over one the repository supplies.

    The order is the whole resolution contract in miniature: the session
    environment is rung two and repository content is rung three, so an
    operator who exports a key for one run is never overruled by a file they
    may not have written.
    """
    root = _dotenv(
        _workspace(tmp_path, package=PACKAGE, mode=InstallMode.DEPENDENCY), var
    )

    from vaultspec_core.config import resolve_credential

    credential = resolve_credential(
        entry(var),
        root,
        {var.value: _SESSION_KEY},
        interpreter_prefix=root / ".venv",
    )

    assert credential is not None
    assert credential.key == _SESSION_KEY
    assert credential.source is CredentialSource.ENVIRONMENT


def test_a_settings_variable_is_never_read_from_the_file(tmp_path: Path) -> None:
    """Repository content supplies keys and never settings.

    A ``.env`` naming a port would otherwise let a clone repoint the service
    of anyone who ran a command inside it.
    """
    root = _workspace(tmp_path, package=PACKAGE, mode=InstallMode.DEPENDENCY)
    (root / ".env").write_text(f"{EnvVar.PORT.value}=9999\n", encoding="utf-8")

    with pytest.raises(ValueError, match="not a credential"):
        workspace_credential(EnvVar.PORT, root)


def test_a_key_from_the_workspace_file_becomes_a_daemon_assignment(
    tmp_path: Path, no_session_credentials: None
) -> None:
    """The daemon is handed what it may not read for itself.

    The resident service answers for every root it holds, so a file belonging
    to one of them must never configure it. The command line has exactly one
    resolved workspace and is the only process entitled to open that file, so
    it resolves the key and assigns it into the child's environment. Nothing
    else could supply these values: the fixture has cleared the session, so an
    assignment here came from the file or from nowhere.
    """
    assert no_session_credentials is None
    root = _workspace(tmp_path, package=PACKAGE, mode=InstallMode.DEPENDENCY)
    (root / ".env").write_text(
        "\n".join(
            f"{var.value}={_DOTENV_KEY}-{var.name}" for var in DAEMON_CREDENTIALS
        ),
        encoding="utf-8",
    )

    assigned = credential_assignments(root, interpreter_prefix=root / ".venv")

    assert {var.env_name: value for var, value in assigned} == {
        var.value: f"{_DOTENV_KEY}-{var.name}" for var in DAEMON_CREDENTIALS
    }


def test_a_file_outside_the_gate_never_becomes_a_daemon_assignment(
    tmp_path: Path, no_session_credentials: None
) -> None:
    """A globally installed tool hands the daemon nothing the clone wrote."""
    assert no_session_credentials is None
    root = _dotenv(
        _workspace(tmp_path / "project", package=PACKAGE, mode=InstallMode.DEPENDENCY),
        EnvVar.HF_TOKEN,
    )
    outside = tmp_path / "tools" / "venv"
    outside.mkdir(parents=True)

    assert credential_assignments(root, interpreter_prefix=outside) == ()


def test_the_daemon_environment_carries_the_sessions_credentials(
    tmp_path: Path,
) -> None:
    """A key the session holds is still there when the daemon starts.

    Narrower than the assignment test above, and deliberately so: this one
    says only that building the child environment does not lose what the
    session already had. The file-sourced half cannot be proved here, because
    the gate turns on where THIS interpreter lives, which a test cannot move;
    it is proved against the resolver, which is what puts the value into this
    mapping.
    """
    root = _workspace(tmp_path, package=PACKAGE, mode=InstallMode.DEPENDENCY)
    previous = set_env(EnvVar.TYPESAFE_API_KEY, _SESSION_KEY)
    try:
        env = _build_service_child_env(_ServiceChildEnvRequest(root=root))
    finally:
        restore_env(EnvVar.TYPESAFE_API_KEY, previous)

    assert env[EnvVar.TYPESAFE_API_KEY.value] == _SESSION_KEY


def test_the_daemon_child_environment_never_pins_the_project_root(
    tmp_path: Path,
) -> None:
    """The multi-root daemon must not inherit one workspace's root."""
    root = _workspace(tmp_path, package=PACKAGE, mode=InstallMode.DEPENDENCY)
    previous = set_env(EnvVar.RAG_ROOT, str(root))
    try:
        env = _build_service_child_env(_ServiceChildEnvRequest(root=root))
    finally:
        restore_env(EnvVar.RAG_ROOT, previous)

    assert EnvVar.RAG_ROOT.value not in env


def test_no_workspace_resolves_no_assignments() -> None:
    """Without a resolved workspace the inherited environment is the whole of it."""
    assert credential_assignments(None) == ()


def test_an_unconfigured_workspace_assigns_nothing(
    tmp_path: Path, no_session_credentials: None
) -> None:
    """Nothing is invented for a workspace that supplies no key."""
    assert no_session_credentials is None
    root = _workspace(tmp_path, package=PACKAGE, mode=InstallMode.DEPENDENCY)

    assert credential_assignments(root, interpreter_prefix=root / ".venv") == ()


def test_the_daemon_never_reaches_the_credential_resolver() -> None:
    """The resident service holds no workspace, so it opens no workspace file.

    It serves many roots at once and a file belonging to one of them is not
    configuration for the rest. The guard is an import guard because that is
    the level the property holds at: a daemon that cannot reach the resolver
    cannot call it by accident on some later request path. Run in a fresh
    interpreter, since this one's module table is polluted by every test
    before it.
    """
    assert_fresh_import_excludes(
        import_probe_source(
            "vaultspec_rag.server._main",
            forbidden=("vaultspec_rag.config._credentials",),
        )
    )

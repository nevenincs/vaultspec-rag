"""Code-file authorization exercises real aliases through the HTTP handler.

Removing canonical authorization produced 20 response assertion failures;
restoring it passed all 20 file, chain, and directory alias cases.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from starlette.testclient import TestClient

from ..server import ServerRouteRuntime, create_http_app
from ..service import ServiceRegistry

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

pytestmark = [pytest.mark.unit]


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    (tmp_path / ".vault").mkdir()
    return tmp_path


@pytest.fixture
def client() -> Iterator[TestClient]:
    app = create_http_app(
        ServerRouteRuntime(
            token="code-file-test-token",
            registry=ServiceRegistry(),
            port=8765,
        ),
        lifespan=None,
    )
    with TestClient(
        app,
        headers={"Authorization": "Bearer code-file-test-token"},
        base_url="http://127.0.0.1",
    ) as route_client:
        yield route_client


@pytest.mark.parametrize(
    "target_path",
    [
        ".env",
        ".env.production",
        "tls/server.pem",
        "tls/server.key",
        "config/credentials.json",
        "deploy/secrets.yaml",
        ".git/config",
        "service.json",
        ".vaultspec-rag/state.txt",
    ],
)
@pytest.mark.parametrize("chained", [False, True])
def test_sensitive_target_denied_through_file_alias(
    client: TestClient, workspace: Path, target_path: str, chained: bool
) -> None:
    """Checking only the caller's alias lets the protected target reach the read."""
    target = workspace / target_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("protected fixture content\n", encoding="utf-8")
    alias = workspace / "source.py"
    alias.symlink_to(target)
    if chained:
        outer = workspace / "outer.py"
        outer.symlink_to(alias)
        alias = outer

    response = client.post(
        "/code-file", json={"path": alias.name, "project_root": str(workspace)}
    )

    assert response.status_code == 200
    assert response.json() == {"error": "access denied"}


@pytest.mark.parametrize("sensitive_dir", [".git", ".vaultspec-rag"])
def test_sensitive_directory_denied_through_directory_alias(
    client: TestClient, workspace: Path, sensitive_dir: str
) -> None:
    """A safe basename still needs authorization against its resolved parents."""
    target_dir = workspace / sensitive_dir
    target_dir.mkdir()
    (target_dir / "config").write_text("protected fixture content\n", encoding="utf-8")
    (workspace / "source").symlink_to(target_dir, target_is_directory=True)

    response = client.post(
        "/code-file", json={"path": "source/config", "project_root": str(workspace)}
    )

    assert response.status_code == 200
    assert response.json() == {"error": "access denied"}


@pytest.mark.parametrize("alias_name", [".env", "credentials.json", "service.json"])
def test_sensitive_alias_to_safe_target_remains_denied(
    client: TestClient, workspace: Path, alias_name: str
) -> None:
    """Removing caller-name authorization failed all three response assertions;
    restoring it passed all three, preserving the old sensitive-alias policy.
    """
    target = workspace / "main.py"
    target.write_text("print('hello')\n", encoding="utf-8")
    (workspace / alias_name).symlink_to(target)

    response = client.post(
        "/code-file", json={"path": alias_name, "project_root": str(workspace)}
    )

    assert response.status_code == 200
    assert response.json() == {"error": "access denied"}


@pytest.mark.parametrize("path_form", ["relative", "absolute", "normalised", "alias"])
def test_safe_source_reads_preserve_content(
    client: TestClient, workspace: Path, path_form: str
) -> None:
    source_dir = workspace / "src"
    source_dir.mkdir()
    target = source_dir / "main.py"
    content = "print('héllo')\n"
    target.write_text(content, encoding="utf-8")
    paths = {
        "relative": "src/main.py",
        "absolute": str(target),
        "normalised": "src/../src/main.py",
        "alias": "source.py",
    }
    (workspace / "source.py").symlink_to(target)

    response = client.post(
        "/code-file",
        json={"path": paths[path_form], "project_root": str(workspace)},
    )

    assert response.status_code == 200
    assert response.json() == {"content": content}


def test_alias_outside_workspace_remains_denied(
    client: TestClient, workspace: Path
) -> None:
    """Removing the containment branch failed the exact error assertion;
    restoring it passed, proving this is the workspace rejection branch.
    """
    target = workspace.parent / "outside.py"
    target.write_text("outside fixture content\n", encoding="utf-8")
    (workspace / "source.py").symlink_to(target)

    response = client.post(
        "/code-file", json={"path": "source.py", "project_root": str(workspace)}
    )

    assert response.status_code == 200
    assert response.json() == {"error": "path 'source.py' is outside the workspace"}

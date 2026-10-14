"""Release provenance requires the committed producer, even for local builds.

The second half is what a checkout does with the monitor it just compiled:
pack it, admit it, install it where resolution looks, and refuse to install
anything whose bytes are not what the pin about to be written describes.
"""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

import pytest

import tools.monitor.build as build
from tools.monitor.pins import PINS_PATH
from tools.packaging.products import MONITOR_EXECUTABLE, VAULTSPEC_RAG
from vaultspec_rag.monitor_runtime._assets import monitor_executable_name
from vaultspec_rag.native_binary._install import file_sha256
from vaultspec_rag.native_binary._targets import host_target

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.unit

_VERSION = "9.9.9"
#: Stands in for a compiled monitor. What the install does with it is decided
#: by its bytes, so bytes are all it needs to be.
_COMPILED = b"#!a monitor this checkout compiled\x00" * 64


def test_release_identity_refuses_dirty_checkout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lock = tmp_path / "package-lock.json"
    lock.write_text("{}\n", encoding="utf-8")
    for args in (
        ["git", "init", "-q"],
        ["git", "add", "package-lock.json"],
        [
            "git",
            "-c",
            "user.name=Build tests",
            "-c",
            "user.email=build@example.invalid",
            "commit",
            "-qm",
            "Seed producer",
        ],
    ):
        subprocess.run(args, cwd=tmp_path, check=True, capture_output=True)
    revision = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    monkeypatch.setattr(build, "ROOT", tmp_path)
    committed = build.release_identity("vaultspec-rag-v1.2.3", revision)
    assert committed.development is False
    lock.write_text('{"changed":true}\n', encoding="utf-8")
    # Bypassing the dirty-checkout gate must fail the named admission assertion.
    with pytest.raises(ValueError, match="requires a clean producer checkout"):
        build.release_identity("vaultspec-rag-v1.2.3", revision)
    local = build.release_identity("vaultspec-rag-v1.2.3", revision, development=True)
    assert local.development is True
    assert local.lock_sha256 != committed.lock_sha256


@pytest.fixture
def compiled(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A finalized monitor where the compiler leaves one, in a throwaway checkout.

    The checkout root is relocated so the generated pin lands in this test's
    own directory: the real one admits the monitor this working copy runs.
    """
    monkeypatch.setattr(build, "ROOT", tmp_path / "checkout")
    raw = tmp_path / "dist-bin"
    raw.mkdir()
    binary = raw / VAULTSPEC_RAG.asset_name(MONITOR_EXECUTABLE, host_target())
    binary.write_bytes(_COMPILED)
    return binary


def test_the_monitor_a_checkout_compiled_is_pinned_and_installed_for_it(
    compiled: Path, tmp_path: Path
) -> None:
    """One command leaves a monitor this checkout's resolver will admit.

    The executable lands under the name resolution looks for, beside the
    programs it was given, and the pin says it was built here, for this
    version, under no release tag, with the digest the installed file hashes
    to.
    """
    programs = tmp_path / "programs"

    installed = build.install_development_monitor(compiled, _VERSION, programs)

    assert installed == programs / monitor_executable_name(host_target())
    assert installed.read_bytes() == _COMPILED
    pins = (build.ROOT / PINS_PATH).read_text(encoding="utf-8")
    assert "PROVENANCE: Final[str] = 'development'" in pins
    assert f"RELEASE_VERSION: Final[str] = {_VERSION!r}" in pins
    assert "RELEASE_TAG: Final[str] = ''" in pins
    assert f"{host_target()!r}: {file_sha256(installed)!r}," in pins


def test_bytes_the_pin_would_not_describe_are_never_installed(
    compiled: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The install is held to the digest the pin will carry, before it lands.

    Mutation: removed the ``verify_native_binary`` call on the extracted
    executable. Observed this test fail on the nothing-installed assertion,
    with the unadmitted bytes landed under the installed name. Restored;
    passes.
    """
    monkeypatch.setattr(
        build,
        "digests_for",
        lambda archive, _executable: (file_sha256(archive), "f" * 64),
    )
    programs = tmp_path / "programs"

    with pytest.raises(RuntimeError, match="pin mismatch"):
        build.install_development_monitor(compiled, _VERSION, programs)

    assert not (programs / monitor_executable_name(host_target())).exists()
    assert not (build.ROOT / PINS_PATH).exists()

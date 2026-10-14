"""Release provenance requires the committed producer, even for local builds.

The second half is what a checkout does with the monitor it just compiled:
pack it, admit it, install it where resolution looks, and refuse to install
anything whose bytes are not what the pin about to be written describes.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

import tools.monitor.build as build
from tools.monitor.pins import PINS_PATH
from tools.packaging.products import MONITOR_EXECUTABLE, VAULTSPEC_RAG
from vaultspec_rag.monitor_runtime._assets import monitor_executable_name
from vaultspec_rag.native_binary._install import file_sha256
from vaultspec_rag.native_binary._targets import host_target
from vaultspec_rag.tests._separate_installation import run_program

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


#: Run in a throwaway checkout: install a compiled monitor as a development
#: build does, and report what came of it. The arguments are the compiled
#: monitor, the version, where the programs go, and the checkout this runs in.
_INSTALL_THE_COMPILED_MONITOR = """
import json
import sys
from pathlib import Path

from tools.monitor import build

compiled, version, programs, root = json.loads(sys.argv[1])
assert build.ROOT == Path(root), build.ROOT
try:
    installed = build.install_development_monitor(
        Path(compiled), version, Path(programs)
    )
except Exception as exc:
    print(json.dumps({"raised": type(exc).__name__, "message": str(exc)}))
else:
    print(json.dumps({"installed": str(installed)}))
"""


@pytest.fixture
def checkout(tmp_path: Path) -> Path:
    """A throwaway checkout holding a copy of this one's release tooling.

    The tooling finds its checkout by its own location, so run from this copy
    it writes the generated pin here. The real pin, which admits the monitor
    this working copy runs, is never reachable from the test, whether or not
    the install under test does what it should.
    """
    root = tmp_path / "checkout"
    shutil.copytree(
        Path(build.__file__).resolve().parents[1],
        root / "tools",
        ignore=shutil.ignore_patterns(
            "__pycache__", "tests", "test_*.py", "conftest.py"
        ),
    )
    return root


@pytest.fixture
def compiled(tmp_path: Path) -> Path:
    """A finalized monitor where the compiler leaves one."""
    raw = tmp_path / "dist-bin"
    raw.mkdir()
    binary = raw / VAULTSPEC_RAG.asset_name(MONITOR_EXECUTABLE, host_target())
    binary.write_bytes(_COMPILED)
    return binary


def _install_in(checkout: Path, binary: Path, programs: Path) -> dict[str, object]:
    """Run the development install from *checkout*, in a fresh interpreter."""
    return run_program(
        Path(sys.executable),
        checkout,
        _INSTALL_THE_COMPILED_MONITOR,
        str(binary),
        _VERSION,
        str(programs),
        str(checkout.resolve()),
    )


def test_the_monitor_a_checkout_compiled_is_pinned_and_installed_for_it(
    compiled: Path, checkout: Path, tmp_path: Path
) -> None:
    """One command leaves a monitor this checkout's resolver will admit.

    The executable lands under the name resolution looks for, beside the
    programs it was given, and the pin says it was built here, for this
    version, under no release tag, with the digest the installed file hashes
    to.
    """
    programs = tmp_path / "programs"

    outcome = _install_in(checkout, compiled, programs)

    installed = programs / monitor_executable_name(host_target())
    assert outcome == {"installed": str(installed)}
    assert installed.read_bytes() == _COMPILED
    pins = (checkout / PINS_PATH).read_text(encoding="utf-8")
    assert "PROVENANCE: Final[str] = 'development'" in pins
    assert f"RELEASE_VERSION: Final[str] = {_VERSION!r}" in pins
    assert "RELEASE_TAG: Final[str] = ''" in pins
    assert f"{host_target()!r}: {file_sha256(installed)!r}," in pins


def test_bytes_the_pin_would_not_describe_are_never_installed(
    compiled: Path, checkout: Path, tmp_path: Path
) -> None:
    """The install is held to the digest the pin will carry, before it lands.

    The archive is packed from the finalized monitor staged under its release
    name, and the digest the pin will carry is taken from the file the install
    is told about. A file replaced between those two steps is how they differ
    in a build; naming another file from the same directory is the same
    disagreement, and the bytes that come out of the archive are then not the
    ones the pin would describe.

    Mutation: removed the ``verify_native_binary`` call on the extracted
    executable. Observed this test fail on the nothing-installed assertion,
    with the unadmitted bytes landed under the installed name. Restored;
    passes.
    """
    other = compiled.parent / "a-monitor-that-is-not-the-one-packed"
    other.write_bytes(b"#!a monitor of some other build\x00" * 64)
    programs = tmp_path / "programs"

    outcome = _install_in(checkout, other, programs)

    assert outcome["raised"] == "RuntimeError"
    assert "pin mismatch" in str(outcome["message"])
    assert not (programs / monitor_executable_name(host_target())).exists()
    assert not (checkout / PINS_PATH).exists()

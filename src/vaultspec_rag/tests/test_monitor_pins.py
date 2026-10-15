"""Unit tests for the monitor digests an installation admits a monitor under.

The monitor is built from this product's own source, so nobody reviews its
digests before the release ships. What stands in for that review is where the
digests live and which installation is allowed to use them, and that is what
these tests hold: digests minted on a workstation never admit a monitor
inside an installed release, digests from another release never admit one at
all, and digests found anywhere but inside the installed package are not
found.

Every case drives the real reader over modules the real generator wrote, and
the installation cases drive the real metadata reader over real distribution
metadata written to disk.
"""

from __future__ import annotations

from dataclasses import replace
from importlib.util import module_from_spec, spec_from_file_location
from typing import TYPE_CHECKING

import pytest

from tools.monitor.pins import GeneratedPins, write

from ..monitor_runtime._assets import monitor_archive_name, monitor_executable_name
from ..monitor_runtime._pins import (
    MONITOR_PIN_INVALID,
    MONITOR_PIN_UNRELEASED,
    MONITOR_PIN_VERSION_MISMATCH,
    MONITOR_TARGET_UNPINNED,
    MONITOR_UNPINNED,
    PINS_MODULE,
    Installation,
    MonitorPinError,
    PinProvenance,
    read_pin,
    this_installation,
)
from ._separate_installation import INSTALLED_FROM_A_WHEEL, build_installation

if TYPE_CHECKING:
    from pathlib import Path
    from types import ModuleType

pytestmark = [pytest.mark.unit]

_TARGET = "x86_64-pc-windows-msvc"
_OTHER_TARGET = "aarch64-apple-darwin"
_VERSION = "1.2.3"
_ARCHIVE_DIGEST = "a" * 64
_EXECUTABLE_DIGEST = "b" * 64

#: An installed release: a version, and nothing saying it came from a tree.
_RELEASED = Installation(version=_VERSION, development=False)
#: A development installation: the checkout's own.
_IN_DEVELOPMENT = Installation(version=_VERSION, development=True)


#: The digests a release of this version published, as the generator states
#: them. Each case varies one field of this with ``replace``.
_RELEASE_PINS = GeneratedPins(
    provenance=PinProvenance.RELEASE,
    version=_VERSION,
    tag="vaultspec-rag-v1.2.3",
    archives={_TARGET: _ARCHIVE_DIGEST},
    executables={_TARGET: _EXECUTABLE_DIGEST},
)
#: The same digests, minted by a development build on this machine.
_DEVELOPMENT_PINS = replace(_RELEASE_PINS, provenance=PinProvenance.DEVELOPMENT, tag="")

#: Run in a separate installation: what that installation says it is.
_JUDGE_THIS_INSTALLATION = """
import json

from vaultspec_rag.monitor_runtime._pins import this_installation

installation = this_installation()
print(json.dumps(
    {"version": installation.version, "development": installation.development}
))
"""

#: Run in a separate installation: whether a module of the generated pins'
#: bare name can be found, and what asking for a pin answers regardless.
_ASK_FOR_THE_PIN = """
import json
import sys
from importlib.util import find_spec

from vaultspec_rag.monitor_runtime._pins import MonitorPinError, monitor_pin

findable = find_spec("_generated_pins") is not None
try:
    monitor_pin(json.loads(sys.argv[1])[0])
except MonitorPinError as refused:
    error = refused.error
else:
    error = None
print(json.dumps({"findable": findable, "error": error}))
"""


def _written(
    directory: Path, pins: GeneratedPins, name: str = "_generated_pins"
) -> ModuleType:
    """Write *pins* with the real generator into *directory* and import it.

    What the reader is handed is exactly what the generator produces, rather
    than a stand-in shaped like it.
    """
    return _import_file(name, write(directory / f"{name}.py", pins))


def _import_file(name: str, path: Path) -> ModuleType:
    """Import the module at *path* under *name* without putting it on the path."""
    spec = spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _handwritten(
    directory: Path, body: str, name: str = "_handwritten_pins"
) -> ModuleType:
    """Import a pins module written by hand, for shapes the generator refuses.

    The generator rejects a malformed pin before it writes one, which is the
    point of it. The reader still has to refuse the same shapes, because the
    file it reads is not the file the generator wrote once an installation has
    been tampered with.
    """
    path = directory / f"{name}.py"
    path.write_text(body, encoding="utf-8")
    return _import_file(name, path)


class TestAnAdmittedPin:
    def test_a_release_pin_names_the_archive_and_the_member_it_admits(
        self, tmp_path: Path
    ) -> None:
        """What is fetched, what is extracted, and what each is held to."""
        pin = read_pin(_written(tmp_path, _RELEASE_PINS), _TARGET, _RELEASED)

        assert pin.provenance is PinProvenance.RELEASE
        assert pin.version == _VERSION
        assert pin.tag == "vaultspec-rag-v1.2.3"
        assert pin.target == _TARGET
        assert pin.archive_name == monitor_archive_name(_VERSION, _TARGET)
        assert pin.archive_sha256 == _ARCHIVE_DIGEST
        assert pin.executable_name == monitor_executable_name(_TARGET)
        assert pin.executable_sha256 == _EXECUTABLE_DIGEST

    def test_a_development_pin_admits_a_monitor_in_a_development_install(
        self, tmp_path: Path
    ) -> None:
        """A checkout that built its own monitor starts without being configured."""
        pins = _written(tmp_path, _DEVELOPMENT_PINS)

        pin = read_pin(pins, _TARGET, _IN_DEVELOPMENT)

        assert pin.provenance is PinProvenance.DEVELOPMENT
        assert pin.tag == ""
        assert pin.executable_sha256 == _EXECUTABLE_DIGEST


class TestRefusals:
    """Each refusal, and the code an envelope carries for it."""

    def test_no_pins_at_all_admits_nothing(self) -> None:
        """A source checkout verifies no monitor rather than trusting one.

        Mutation: returned an empty ``MonitorPin`` instead of raising when
        the module is absent. Observed this test fail on the
        ``MonitorPinError`` it expects, and the version-mismatch and
        unreleased cases pass unchanged, because neither reaches this branch.
        Restored; passes.
        """
        with pytest.raises(MonitorPinError) as refused:
            read_pin(None, _TARGET, _RELEASED)

        assert refused.value.error == MONITOR_UNPINNED

    def test_a_development_pin_never_admits_a_monitor_in_a_release(
        self, tmp_path: Path
    ) -> None:
        """The guard that keeps a workstation digest out of a published artifact.

        Mutation: dropped the provenance half of the admissibility check, so
        only the version was compared. Observed this test fail on the
        ``monitor_pin_unreleased`` code, with the pin returned instead -
        the versions match here deliberately, so the version check cannot
        stand in for this one. Restored; passes.
        """
        pins = _written(tmp_path, _DEVELOPMENT_PINS)

        with pytest.raises(MonitorPinError) as refused:
            read_pin(pins, _TARGET, _RELEASED)

        assert refused.value.error == MONITOR_PIN_UNRELEASED

    @pytest.mark.parametrize(
        "version",
        [
            pytest.param("9.9.9", id="another major"),
            # The patch release before this one: a comparison loosened to a
            # major or a minor would accept it, and it is a different build
            # of the monitor.
            pytest.param("1.2.2", id="the previous patch"),
        ],
    )
    def test_a_pin_from_another_release_admits_nothing(
        self, tmp_path: Path, version: str
    ) -> None:
        """Version coupling: no cross-version fallback, no newest lookup.

        Mutation: compared only the major version. Observed the "previous
        patch" case fail on the ``monitor_pin_version_mismatch`` code, with
        the pin returned instead. Restored; passes.
        """
        another = replace(
            _RELEASE_PINS, version=version, tag=f"vaultspec-rag-v{version}"
        )
        pins = _written(tmp_path, another)

        with pytest.raises(MonitorPinError) as refused:
            read_pin(pins, _TARGET, _RELEASED)

        assert refused.value.error == MONITOR_PIN_VERSION_MISMATCH

    def test_a_target_this_release_published_no_monitor_for_admits_nothing(
        self, tmp_path: Path
    ) -> None:
        """An unpublished target is never served another target's build."""
        with pytest.raises(MonitorPinError) as refused:
            read_pin(_written(tmp_path, _RELEASE_PINS), _OTHER_TARGET, _RELEASED)

        assert refused.value.error == MONITOR_TARGET_UNPINNED

    @pytest.mark.parametrize(
        ("body", "id"),
        [
            pytest.param(
                "PROVENANCE = 'homegrown'\n"
                "RELEASE_VERSION = '1.2.3'\n"
                "ARCHIVE_SHA256 = {'x86_64-pc-windows-msvc': 'a' * 64}\n"
                "EXECUTABLE_SHA256 = {'x86_64-pc-windows-msvc': 'b' * 64}\n",
                "an unknown provenance",
                id="unknown provenance",
            ),
            pytest.param(
                "RELEASE_VERSION = '1.2.3'\n"
                "ARCHIVE_SHA256 = {'x86_64-pc-windows-msvc': 'a' * 64}\n"
                "EXECUTABLE_SHA256 = {'x86_64-pc-windows-msvc': 'b' * 64}\n",
                "no provenance",
                id="no provenance",
            ),
            pytest.param(
                "PROVENANCE = 'release'\n"
                "ARCHIVE_SHA256 = {'x86_64-pc-windows-msvc': 'a' * 64}\n"
                "EXECUTABLE_SHA256 = {'x86_64-pc-windows-msvc': 'b' * 64}\n",
                "no version",
                id="no version",
            ),
            pytest.param(
                "PROVENANCE = 'release'\n"
                "RELEASE_VERSION = '1.2.3'\n"
                "ARCHIVE_SHA256 = {'x86_64-pc-windows-msvc': 'not a digest'}\n"
                "EXECUTABLE_SHA256 = {'x86_64-pc-windows-msvc': 'b' * 64}\n",
                "a value that is not a digest",
                id="not a digest",
            ),
            pytest.param(
                "PROVENANCE = 'release'\n"
                "RELEASE_VERSION = '1.2.3'\n"
                "ARCHIVE_SHA256 = {'x86_64-pc-windows-msvc': 'A' * 64}\n"
                "EXECUTABLE_SHA256 = {'x86_64-pc-windows-msvc': 'b' * 64}\n",
                "a digest that is not lower case",
                id="upper-case digest",
            ),
            pytest.param(
                "PROVENANCE = 'release'\n"
                "RELEASE_VERSION = '1.2.3'\n"
                "ARCHIVE_SHA256 = {}\n"
                "EXECUTABLE_SHA256 = {}\n",
                "no digests at all",
                id="empty mappings",
            ),
            pytest.param(
                "PROVENANCE = 'release'\n"
                "RELEASE_VERSION = '1.2.3'\n"
                "ARCHIVE_SHA256 = {'x86_64-pc-windows-msvc': 'a' * 64}\n"
                "EXECUTABLE_SHA256 = {'aarch64-apple-darwin': 'b' * 64}\n",
                "an archive digest with no executable digest beside it",
                id="mismatched targets",
            ),
        ],
    )
    def test_pins_that_cannot_be_read_as_pins_admit_nothing(
        self, tmp_path: Path, body: str, id: str
    ) -> None:
        """A tampered or half-written module is refused, never half-trusted.

        Mutation: accepted any string as a digest, dropping the SHA256 shape
        check. Observed the "not a digest" and "upper-case digest" cases fail
        on the ``monitor_pin_invalid`` code; the others pass unchanged,
        because each is refused by a check of its own. Restored; passes.
        """
        with pytest.raises(MonitorPinError) as refused:
            read_pin(_handwritten(tmp_path, body), _TARGET, _RELEASED)

        assert refused.value.error == MONITOR_PIN_INVALID, id


class TestWhereThePinsAreReadFrom:
    def test_the_pins_module_is_inside_the_package(self) -> None:
        """Nothing outside the installed package can answer for the digests."""
        assert PINS_MODULE == "vaultspec_rag.monitor_runtime._generated_pins"

    def test_pins_on_the_import_path_are_not_this_installation_s(
        self, tmp_path: Path
    ) -> None:
        """A module of that name elsewhere on the path admits no monitor.

        The analogue of never searching PATH for an executable: a digest
        table found next to whatever the process was started from would
        decide what runs.

        The installation is a release that carries no digests of its own, in a
        fresh interpreter whose import path starts at a module named for the
        generated one and holding the digests of that very release, so nothing
        but where it sits can be what refuses it. The program reports that the
        module is findable, or the refusal would prove nothing.

        Mutation: looked the module up by its bare name instead of its
        dotted package name. Observed this test fail on the answer it
        compares, a pin returned because the planted module answered.
        Restored; passes.
        """
        installed = build_installation(
            tmp_path, version=_VERSION, direct_url=INSTALLED_FROM_A_WHEEL
        )
        write(installed.root / "_generated_pins.py", _RELEASE_PINS)

        answer = installed.run(_ASK_FOR_THE_PIN, _TARGET)

        assert answer == {"findable": True, "error": MONITOR_UNPINNED}


class TestWhatThisInstallationIs:
    """How an installation is judged, over real distribution metadata."""

    @pytest.mark.parametrize(
        ("direct_url", "development"),
        [
            pytest.param(None, False, id="installed from an index"),
            pytest.param(
                '{"url": "file:///tmp/vaultspec_rag-1.2.3-py3-none-any.whl",'
                ' "archive_info": {}}',
                False,
                id="installed from a wheel file",
            ),
            pytest.param(
                '{"url": "file:///src/vaultspec-rag", "dir_info": {}}',
                True,
                id="installed from a directory",
            ),
            pytest.param(
                '{"url": "file:///src/vaultspec-rag", "dir_info": {"editable": true}}',
                True,
                id="installed editable",
            ),
            pytest.param("{not json", False, id="an unreadable record"),
        ],
    )
    def test_how_an_install_was_made_decides_what_it_may_accept(
        self, tmp_path: Path, direct_url: str | None, development: bool
    ) -> None:
        """Only a local-directory install counts as a development one.

        Each case is an installation of its own, with the record an installer
        would leave, judged by a fresh interpreter running in it: the metadata
        is found the way the import system finds it, not handed over.

        Mutation: treated an absent direct-URL record as a development
        install. Observed the "installed from an index" case fail on the
        judgement it compares, which is the case every published wheel is.
        Restored; passes.
        """
        installed = build_installation(tmp_path, version="1.2.3", direct_url=direct_url)

        judged = installed.run(_JUDGE_THIS_INSTALLATION)

        assert judged == {"version": "1.2.3", "development": development}

    def test_this_checkout_is_a_development_installation(self) -> None:
        """The judgement over the real environment this suite runs in.

        A checkout is either imported directly or installed from its own
        directory, so the suite's own installation must never be one that
        would accept a release pin only.
        """
        assert this_installation().development is True

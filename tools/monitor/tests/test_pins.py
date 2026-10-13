"""The monitor digest generator, and the build configuration that ships it.

The generated module is the whole trust anchor for the monitor: it says which
bytes a release may run. Two things therefore have to hold outside the
reader's own checks. The generator must refuse to write a module the reader
would refuse to read, so a bad release step fails where it happened rather
than on an operator's first start. And the build backend must put the module
into the wheel and the sdist even though version control ignores it, because
an artifact without it provisions no monitor at all.
"""

from __future__ import annotations

import tomllib
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, cast

import pytest

from tools.monitor.pins import PINS_PATH, GeneratedPins, digests_for, render, write
from vaultspec_rag.monitor_runtime._pins import PINS_MODULE, PinProvenance

if TYPE_CHECKING:
    from collections.abc import Iterator

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[3]
_TARGET = "x86_64-pc-windows-msvc"
_SECOND_TARGET = "aarch64-apple-darwin"


#: A well-formed release pin set. Each case varies one field of it.
_RELEASE = GeneratedPins(
    provenance=PinProvenance.RELEASE,
    version="1.2.3",
    tag="vaultspec-rag-v1.2.3",
    archives={_TARGET: "a" * 64},
    executables={_TARGET: "b" * 64},
)


class TestTheGeneratorRefusesWhatTheReaderWould:
    @pytest.mark.parametrize(
        "pins",
        [
            pytest.param(
                replace(_RELEASE, archives={}, executables={}), id="no targets"
            ),
            pytest.param(
                replace(_RELEASE, executables={_SECOND_TARGET: "b" * 64}),
                id="different target sets",
            ),
            pytest.param(
                replace(_RELEASE, archives={_TARGET: "not a digest"}), id="not a digest"
            ),
            pytest.param(
                replace(_RELEASE, archives={_TARGET: "A" * 64}), id="upper case"
            ),
            pytest.param(replace(_RELEASE, version=""), id="no version"),
        ],
    )
    def test_a_module_the_reader_would_refuse_is_never_written(
        self, tmp_path: Path, pins: GeneratedPins
    ) -> None:
        """Refused before the file exists, so no half-pinned artifact is built.

        Mutation: made ``write`` create the file before calling ``render``.
        Observed every case fail on the "nothing was written" assertion.
        Restored; passes.
        """
        destination = tmp_path / "nested" / "_generated_pins.py"

        with pytest.raises(ValueError):
            write(destination, pins)

        assert not destination.exists()
        assert not destination.parent.exists()


class TestWhatIsGenerated:
    def test_the_module_states_every_name_the_reader_reads(self) -> None:
        source = render(
            replace(
                _RELEASE,
                archives={_TARGET: "a" * 64, _SECOND_TARGET: "c" * 64},
                executables={_TARGET: "b" * 64, _SECOND_TARGET: "d" * 64},
            )
        )

        assert "PROVENANCE: Final[str] = 'release'" in source
        assert "RELEASE_VERSION: Final[str] = '1.2.3'" in source
        assert "RELEASE_TAG: Final[str] = 'vaultspec-rag-v1.2.3'" in source
        assert "ARCHIVE_SHA256: Final[dict[str, str]]" in source
        assert "EXECUTABLE_SHA256: Final[dict[str, str]]" in source
        # Sorted, so two runs over the same release produce the same file.
        assert source.index(f"'{_SECOND_TARGET}'") < source.index(f"'{_TARGET}'")

    def test_the_digests_are_the_bytes_the_build_left_behind(
        self, tmp_path: Path
    ) -> None:
        """Hashed where they lie, not restated from anything about them."""
        archive = tmp_path / "monitor.zip"
        executable = tmp_path / "monitor.exe"
        archive.write_bytes(b"archive bytes")
        executable.write_bytes(b"executable bytes")

        archive_digest, executable_digest = digests_for(archive, executable)

        source = render(
            replace(
                _RELEASE,
                archives={_TARGET: archive_digest},
                executables={_TARGET: executable_digest},
            )
        )
        assert archive_digest in source
        assert executable_digest in source
        assert archive_digest != executable_digest


class TestTheGeneratedModuleReachesTheArtifacts:
    """The build configuration, which no built artifact can correct later."""

    def _declared_artifacts(self) -> Iterator[tuple[str, list[str]]]:
        """Yield each build target's name and the artifacts it names."""
        configuration = tomllib.loads(
            (_ROOT / "pyproject.toml").read_text(encoding="utf-8")
        )
        targets = cast(
            "dict[str, dict[str, list[str]]]",
            configuration["tool"]["hatch"]["build"]["targets"],
        )
        for name in ("wheel", "sdist"):
            # Read with a default, so a target that names nothing fails the
            # assertion below rather than the lookup here.
            yield name, targets.get(name, {}).get("artifacts", [])

    def test_the_generator_writes_where_the_reader_reads(self) -> None:
        """One path, stated twice, held equal here.

        The reader imports a dotted name inside the package; the generator
        writes a file. Nothing but this makes them the same module.
        """
        expected = Path("src", *PINS_MODULE.split(".")).with_suffix(".py")

        assert expected == PINS_PATH

    def test_version_control_ignores_the_generated_module(self) -> None:
        """A digest in version control would outlive its artifact."""
        ignored = (_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()

        assert f"/{PINS_PATH.as_posix()}" in ignored

    def test_the_wheel_and_the_sdist_carry_it_anyway(self) -> None:
        """Both artifacts name it, because the ignore would otherwise win.

        Mutation: removed the wheel target's ``artifacts`` entry. Observed
        this test fail on the membership assertion for the wheel; the ignore
        test passed unchanged, which is the pair that matters - an ignored
        file nothing names is an artifact with no pin.
        Restored; passes. Built with ``uv build --wheel --sdist`` against a
        generated module and confirmed both carry
        ``vaultspec_rag/monitor_runtime/_generated_pins.py``.
        """
        for name, artifacts in self._declared_artifacts():
            assert PINS_PATH.as_posix() in artifacts, name

"""Generate the monitor digest module the package verifies against.

Run by the release pipeline once every target's monitor is finalized and
before the wheel is built, so the wheel and the sdist carry the digests of
the monitors that release publishes. Run by this repository's development
setup for the monitor it compiles here, which is how a development checkout
starts the service without anyone exporting anything.

The module is written, never hand-edited, and is not committed: a digest in
version control would outlive the artifact it describes. The wheel and the
sdist pick it up through the build backend's artifact inclusion.

A development pin says it is one. The reader refuses a development pin
inside an installed release, so what this writes for a local build can never
widen what a published artifact will run.
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import cast

from tools.packaging.products import MONITOR_EXECUTABLE, VAULTSPEC_RAG
from vaultspec_rag.monitor_runtime._assets import monitor_archive_name
from vaultspec_rag.monitor_runtime._pins import PinProvenance
from vaultspec_rag.native_binary._install import file_sha256

#: Where the generated module lands, relative to the repository root. The
#: reader imports it from inside the installed package, so this is the only
#: place writing it has any effect.
PINS_PATH = Path("src/vaultspec_rag/monitor_runtime/_generated_pins.py")

#: The same module's name inside a built wheel, where the source root is gone.
#: Read rather than imported: a release's wheel is inspected by the pipeline
#: that produced it, which must not execute the artifact it is checking.
WHEEL_PINS_MEMBER = PINS_PATH.relative_to("src").as_posix()

_SHA256 = re.compile(r"\A[0-9a-f]{64}\Z")

#: Named rather than escaped, because every string in this module is Python
#: source being written and an escape in one reads as part of that source.
_NEWLINE = chr(10)

_HEADER = '''"""Monitor digests generated for one release. Do not edit; not committed.

Written by the release pipeline before the wheel is built, and by this
repository's development setup for a monitor compiled here. The reader is
``vaultspec_rag.monitor_runtime._pins``, which states what each name means
and what it refuses.
"""

from __future__ import annotations

from typing import Final

'''


@dataclass(frozen=True)
class GeneratedPins:
    """One release's monitor digests, as the generated module will state them.

    Attributes:
        provenance: Whether a release pipeline or a local development build
            produced these digests.
        version: The release version the monitors were built for.
        tag: The release tag publishing them, empty for a development build.
        archives: Target triple to monitor-only archive SHA256.
        executables: Target triple to monitor executable SHA256.
    """

    provenance: PinProvenance
    version: str
    tag: str = ""
    archives: dict[str, str] = field(default_factory=dict[str, str])
    executables: dict[str, str] = field(default_factory=dict[str, str])


def render(pins: GeneratedPins) -> str:
    """Return the source of the generated module.

    Raises:
        ValueError: When the two mappings do not cover the same targets, when
            either is empty, when any value is not a lower-case hexadecimal
            SHA256, or when no version is named. The reader refuses each of
            those; failing here means a bad release step is caught where it
            happened.
    """
    if not pins.archives or pins.archives.keys() != pins.executables.keys():
        raise ValueError(
            "The archive and executable digests must cover the same "
            f"non-empty set of targets: {sorted(pins.archives)} against "
            f"{sorted(pins.executables)}"
        )
    for mapping in (pins.archives, pins.executables):
        for target, digest in mapping.items():
            if not _SHA256.match(digest):
                raise ValueError(f"{target} has no SHA256 digest: {digest!r}")
    if not pins.version:
        raise ValueError("A pin must name the release version it was built for")
    return "".join(
        [
            _HEADER,
            _assignment("PROVENANCE", str(pins.provenance)),
            _assignment("RELEASE_VERSION", pins.version),
            _assignment("RELEASE_TAG", pins.tag),
            _mapping("ARCHIVE_SHA256", pins.archives),
            _mapping("EXECUTABLE_SHA256", pins.executables),
        ]
    )


def _assignment(name: str, value: str) -> str:
    """Render one string constant of the generated module."""
    return f"{name}: Final[str] = {value!r}" + _NEWLINE


def _mapping(name: str, digests: dict[str, str]) -> str:
    """Render one target-to-digest mapping, sorted so the output is stable."""
    rows = "".join(
        f"    {target!r}: {digests[target]!r}," + _NEWLINE for target in sorted(digests)
    )
    opened = f"{name}: Final[dict[str, str]] = {{" + _NEWLINE
    return _NEWLINE + opened + rows + "}" + _NEWLINE


def write(destination: Path, pins: GeneratedPins) -> Path:
    """Write the generated module to *destination* and return its path.

    Raises:
        ValueError: As :func:`render` does, before anything is written.
    """
    source = render(pins)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(source, encoding="utf-8")
    return destination


class WheelPinsError(ValueError):
    """A built wheel carries no monitor pins, or none that could be written."""


def read_wheel_pins(wheel: Path) -> GeneratedPins:
    """Return the monitor pins *wheel* carries.

    The module is parsed, never imported or executed: whoever checks a built
    artifact must not run it. Anything the generator would have refused to
    write is refused here too, so a wheel that could not provision a monitor
    is never treated as one that could.

    Raises:
        WheelPinsError: When the wheel cannot be read, carries no generated
            module, or carries one whose fields are not the pins the reader
            inside the package expects.
    """
    try:
        with zipfile.ZipFile(wheel) as archive:
            source = archive.read(WHEEL_PINS_MEMBER).decode("utf-8")
    except KeyError as exc:
        raise WheelPinsError(
            f"{wheel.name} carries no {WHEEL_PINS_MEMBER}, so it names no "
            "monitor it could obtain or verify"
        ) from exc
    except (OSError, UnicodeDecodeError, zipfile.BadZipFile) as exc:
        raise WheelPinsError(f"cannot read {wheel.name}: {exc}") from exc
    pins = _pins_from_source(source, wheel)
    try:
        render(pins)
    except ValueError as exc:
        raise WheelPinsError(f"{wheel.name} carries unusable pins: {exc}") from exc
    return pins


def _pins_from_source(source: str, wheel: Path) -> GeneratedPins:
    """Read the generated module's constants out of its source text.

    Raises:
        WheelPinsError: When a field is absent or is not the literal shape the
            generated module states it in.
    """
    constants: dict[str, object] = {}
    try:
        body = ast.parse(source).body
    except SyntaxError as exc:
        raise WheelPinsError(f"{wheel.name} carries unparsable pins: {exc}") from exc
    for node in body:
        if (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.value is not None
        ):
            try:
                constants[node.target.id] = ast.literal_eval(node.value)
            except (TypeError, ValueError):
                continue
    try:
        provenance = PinProvenance(_text_constant(constants, "PROVENANCE", wheel))
    except ValueError as exc:
        raise WheelPinsError(
            f"{wheel.name} declares a monitor pin provenance that is not one "
            "this pipeline knows how to judge"
        ) from exc
    return GeneratedPins(
        provenance=provenance,
        version=_text_constant(constants, "RELEASE_VERSION", wheel),
        tag=_text_constant(constants, "RELEASE_TAG", wheel, required=False),
        archives=_mapping_constant(constants, "ARCHIVE_SHA256", wheel),
        executables=_mapping_constant(constants, "EXECUTABLE_SHA256", wheel),
    )


def _text_constant(
    constants: dict[str, object], name: str, wheel: Path, *, required: bool = True
) -> str:
    """Return one string constant of a wheel's generated module."""
    value = constants.get(name)
    if value is None and not required:
        return ""
    if not isinstance(value, str):
        raise WheelPinsError(f"{wheel.name} states no monitor pin {name}")
    return value


def _mapping_constant(
    constants: dict[str, object], name: str, wheel: Path
) -> dict[str, str]:
    """Return one target-to-digest mapping of a wheel's generated module."""
    value = constants.get(name)
    if not isinstance(value, dict):
        raise WheelPinsError(f"{wheel.name} states no monitor pin {name} mapping")
    entries = cast("dict[object, object]", value)
    return {str(target): str(digest) for target, digest in entries.items()}


def digests_for(archive: Path, executable: Path) -> tuple[str, str]:
    """Return the archive and executable digests of one finalized target.

    The files are hashed as they are, where the build left them, so the
    digests describe the bytes that were published rather than anything
    restated about them.
    """
    return file_sha256(archive), file_sha256(executable)


def staged_digests(
    directory: Path, version: str
) -> tuple[dict[str, str], dict[str, str]]:
    """Return the digests of every shipped target's monitor staged in *directory*.

    A release pins every target it ships or none: a wheel missing one target's
    digests cannot provision a monitor there, and nothing later supplies it.
    So an absent artifact is an error rather than a smaller pin set.

    Args:
        directory: Where the finalized archives and executables were staged.
        version: The release version their names carry.

    Returns:
        The archive and executable digest mappings, keyed by target triple.

    Raises:
        FileNotFoundError: When a shipped target has no finalized archive or
            no finalized executable in *directory*.
    """
    archives: dict[str, str] = {}
    executables: dict[str, str] = {}
    for target in VAULTSPEC_RAG.supported_targets:
        archive = directory / monitor_archive_name(version, target)
        executable = directory / VAULTSPEC_RAG.asset_name(MONITOR_EXECUTABLE, target)
        missing = [path for path in (archive, executable) if not path.is_file()]
        if missing:
            raise FileNotFoundError(
                f"{target} has no finalized monitor in {directory}: "
                + ", ".join(path.name for path in missing)
            )
        archives[target], executables[target] = digests_for(archive, executable)
    return archives, executables


def main(argv: list[str] | None = None) -> int:
    """Generate the pin module from finalized per-target monitor artifacts."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--version", default="", help="release version; derived from --tag when absent"
    )
    parser.add_argument("--tag", default="", help="release tag, if one publishes it")
    parser.add_argument(
        "--provenance",
        required=True,
        choices=[str(member) for member in PinProvenance],
        help="whether a release pipeline or a local build produced these",
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument(
        "--target",
        action="append",
        metavar="TRIPLE=ARCHIVE=EXECUTABLE",
        help=(
            "one target's finalized artifacts, as "
            "'<triple>=<archive path>=<executable path>'; repeatable"
        ),
    )
    source.add_argument(
        "--directory",
        type=Path,
        help=(
            "a directory holding every shipped target's finalized monitor "
            "archive and executable, named as the release publishes them"
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help=f"where to write the module (default {PINS_PATH})",
    )
    args = parser.parse_args(argv)
    # A release names its artifacts by version and publishes them under a
    # tag, and the tag is what the pipeline has in hand. Taking the version
    # from it keeps one spelling of the release in the generated module.
    version = args.version or VAULTSPEC_RAG.version_from_tag(args.tag)
    if not version:
        parser.error("Pins must name the release version, or the tag naming it")

    archives: dict[str, str] = {}
    executables: dict[str, str] = {}
    if args.directory is not None:
        try:
            archives, executables = staged_digests(args.directory, version)
        except FileNotFoundError as exc:
            print(f"monitor pins: {exc}", file=sys.stderr)
            return 1
    for entry in args.target or []:
        triple, _, paths = entry.partition("=")
        archive, _, executable = paths.partition("=")
        if not triple or not archive or not executable:
            parser.error(f"--target {entry!r} is not 'triple=archive=executable'")
        archives[triple], executables[triple] = digests_for(
            Path(archive), Path(executable)
        )
    destination = args.output or PINS_PATH
    try:
        written = write(
            destination,
            GeneratedPins(
                provenance=PinProvenance(args.provenance),
                version=version,
                tag=args.tag,
                archives=archives,
                executables=executables,
            ),
        )
    except ValueError as exc:
        print(f"monitor pins: {exc}", file=sys.stderr)
        return 1
    print(f"monitor pins: wrote {len(archives)} target(s) to {written}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

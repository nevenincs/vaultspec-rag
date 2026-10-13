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
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

from vaultspec_rag.monitor_runtime._pins import PinProvenance
from vaultspec_rag.native_binary._install import file_sha256

#: Where the generated module lands, relative to the repository root. The
#: reader imports it from inside the installed package, so this is the only
#: place writing it has any effect.
PINS_PATH = Path("src/vaultspec_rag/monitor_runtime/_generated_pins.py")

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


def digests_for(archive: Path, executable: Path) -> tuple[str, str]:
    """Return the archive and executable digests of one finalized target.

    The files are hashed as they are, where the build left them, so the
    digests describe the bytes that were published rather than anything
    restated about them.
    """
    return file_sha256(archive), file_sha256(executable)


def main(argv: list[str] | None = None) -> int:
    """Generate the pin module from finalized per-target monitor artifacts."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True, help="release version")
    parser.add_argument("--tag", default="", help="release tag, if one publishes it")
    parser.add_argument(
        "--provenance",
        required=True,
        choices=[str(member) for member in PinProvenance],
        help="whether a release pipeline or a local build produced these",
    )
    parser.add_argument(
        "--target",
        required=True,
        action="append",
        metavar="TRIPLE=ARCHIVE=EXECUTABLE",
        help=(
            "one target's finalized artifacts, as "
            "'<triple>=<archive path>=<executable path>'; repeatable"
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help=f"where to write the module (default {PINS_PATH})",
    )
    args = parser.parse_args(argv)

    archives: dict[str, str] = {}
    executables: dict[str, str] = {}
    for entry in args.target:
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
                version=args.version,
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

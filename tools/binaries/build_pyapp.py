#!/usr/bin/env python
"""Build the standalone ``vaultspec-rag`` and ``vaultspec-search-mcp`` binaries.

PyApp (https://ofek.dev/pyapp) is a Rust bootstrapper from the Hatch
ecosystem. It is configured entirely through ``PYAPP_*`` environment
variables read at ``cargo`` build time; there is no project-side config
file. This script encodes the decided build model once so the release
workflow (and a maintainer reproducing a release locally) can invoke it
identically on every target.

Two binaries are produced from the same PyPI distribution, differing only
in their execution entry point:

- ``vaultspec-rag`` runs ``python -m vaultspec_rag`` (PYAPP_EXEC_MODULE).
- ``vaultspec-search-mcp`` runs the object reference ``vaultspec_rag.server:main``
  (PYAPP_EXEC_SPEC), matching the ``vaultspec-search-mcp`` console script.

The MCP server lives behind the ``mcp`` extra, so the binary installs
``vaultspec-rag[mcp]``: a bare install omits the ``mcp`` dependency and the
server binary would fail to import at first launch.

Torch is pinned to the accelerated build on every target that publishes one,
because the bootstrap's default - plain PyPI - is CPU-only on Windows and is
not the build this project resolves on Linux. See
``tools.binaries.torch_channel`` for how the pin is derived from ``uv.lock``
and why it is a direct wheel reference rather than an extra index.

The distribution source is the published PyPI package pinned to the release
version: PyApp installs it into a per-user data directory on first launch
(PYAPP_PROJECT_NAME + PYAPP_PROJECT_VERSION), while the CPython runtime is
embedded into the binary itself (PYAPP_DISTRIBUTION_EMBED). The binary
therefore needs no Python on the user's machine, but does resolve
``vaultspec-rag==<version>`` from PyPI on first run - so the release must
be published to PyPI for the binary to bootstrap.

Usage::

    uv run --no-project --python 3.13 python tools/binaries/build_pyapp.py \
        --tag vaultspec-rag-v0.4.6 --outdir dist-bin [--target <triple>]

``--target`` cross-compiles for a Rust target triple other than the host
(the CI matrix uses it to build the macOS x86_64 binary on an Apple Silicon
runner); the matching ``rustup target`` must already be installed. Only the
Python standard library is used, so any Python 3.13 interpreter can run it.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import struct
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from tools.binaries.torch_channel import pip_extra_args

# Pinned PyApp crate version. Bumping this changes the bootstrapper and the
# embedded python-build-standalone distributions it selects, so it is an
# explicit, reviewable dependency rather than "whatever is latest".
PYAPP_VERSION = "0.29.0"

# The PyPI distribution both binaries install from.
PROJECT_NAME = "vaultspec-rag"

# Embedded CPython series. Must satisfy the package's requires-python.
PYTHON_VERSION = "3.13"


@dataclass(frozen=True)
class Binary:
    """One console entry point rendered as a standalone binary."""

    name: str
    # Exactly one of exec_module / exec_spec is set (PyApp execution modes
    # are mutually exclusive).
    exec_module: str | None = None
    exec_spec: str | None = None

    def pyapp_exec_env(self) -> dict[str, str]:
        if self.exec_module is not None:
            return {"PYAPP_EXEC_MODULE": self.exec_module}
        assert self.exec_spec is not None
        return {"PYAPP_EXEC_SPEC": self.exec_spec}


BINARIES = (
    Binary(name="vaultspec-rag", exec_module="vaultspec_rag"),
    Binary(name="vaultspec-search-mcp", exec_spec="vaultspec_rag.server:main"),
)

#: PyPI extras the bootstrap must install. The MCP server is an opt-in extra
#: in this project, so a bare `vaultspec-rag` install produces a binary that
#: cannot import `mcp` on first launch.
PROJECT_FEATURES = "mcp"


def version_from_tag(tag: str) -> str:
    """Derive the PyPI version from a release tag.

    Release tags are ``vaultspec-rag-v<version>`` (see publish.yml); a bare
    ``v<version>`` or ``<version>`` is also accepted for local invocation.
    """
    for prefix in (f"{PROJECT_NAME}-v", "v"):
        if tag.startswith(prefix):
            return tag[len(prefix) :]
    return tag


def host_target_triple() -> str:
    """Return the host Rust target triple as reported by ``rustc``."""
    out = subprocess.run(
        ["rustc", "-vV"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    for line in out.splitlines():
        if line.startswith("host:"):
            return line.split(":", 1)[1].strip()
    raise RuntimeError("could not determine host target triple from `rustc -vV`")


def build_one(binary: Binary, version: str, target: str, workdir: Path) -> Path:
    """Build a single PyApp binary and return the path to the raw executable."""
    root = workdir / binary.name
    env = os.environ.copy()
    env.update(
        {
            "PYAPP_PROJECT_NAME": PROJECT_NAME,
            "PYAPP_PROJECT_VERSION": version,
            # Installs `vaultspec-rag[mcp]` rather than the bare distribution.
            "PYAPP_PROJECT_FEATURES": PROJECT_FEATURES,
            "PYAPP_PYTHON_VERSION": PYTHON_VERSION,
            # Install the project with uv rather than pip on first launch.
            "PYAPP_UV_ENABLED": "1",
            # Bake the CPython distribution into the binary so the target
            # machine needs no interpreter.
            "PYAPP_DISTRIBUTION_EMBED": "1",
        }
    )
    env.update(binary.pyapp_exec_env())
    # Bootstrap the accelerated torch build on every target that has one.
    # Without this the first launch resolves torch from default PyPI, which on
    # Windows is CPU-only - a GPU product delivered with the GPU absent.
    extra_args = pip_extra_args(target, PYTHON_VERSION)
    if extra_args is not None:
        env["PYAPP_PIP_EXTRA_ARGS"] = extra_args

    cmd = [
        "cargo",
        "install",
        "pyapp",
        "--version",
        PYAPP_VERSION,
        "--locked",
        "--force",
        "--root",
        str(root),
        "--target",
        target,
    ]
    print(f"::group::cargo install pyapp ({binary.name}, {target})", flush=True)
    subprocess.run(cmd, check=True, env=env)
    print("::endgroup::", flush=True)

    exe = "pyapp.exe" if target.endswith("windows-msvc") else "pyapp"
    produced = root / "bin" / exe
    if not produced.is_file():
        raise FileNotFoundError(f"pyapp did not produce {produced}")
    return produced


def asset_name(binary: Binary, target: str) -> str:
    suffix = ".exe" if target.endswith("windows-msvc") else ""
    return f"{binary.name}-{target}{suffix}"



# --- platform floor ---------------------------------------------------------
#
# Ported from vaultspec-core's dev/binaries/build_pyapp.py, which settled this
# for that product. rag had no floor check at all, and the consequence is
# measurable: vaultspec-rag#409 read `.gnu.version_r` off the PUBLISHED v0.4.11
# artifacts and found both Linux binaries require GLIBC_2.39 - Ubuntu 24.04 and
# newer. They do not start on Debian 12 (2.36), Ubuntu 22.04 (2.35), RHEL 9 or
# Amazon Linux 2023 (2.34), while docs/installation.md promises "Linux" with no
# floor stated, and neither the Homebrew formula nor the Scoop manifest declares
# one either.
#
# The cause is that the Linux legs built directly on their runners, so each
# artifact inherited whatever glibc its build host happened to have. The
# container pins in binaries.yml fix that; this check is what stops it
# returning silently the next time a runner is upgraded or an image is bumped.
#
# Verified against the real published v0.4.14 x86_64 asset before this landed:
# reports GLIBC_2.39 and refuses it against the 2.28 floor.

GLIBC_FLOOR: dict[str, tuple[int, ...]] = {
    # Built inside a digest-pinned manylinux_2_28 image, so this is a promise
    # the build environment enforces rather than one the build host happens to
    # satisfy. Verified on v0.4.15.
    "x86_64-unknown-linux-gnu": (2, 28),
    # 2.39, NOT 2.28, and the difference is a host constraint rather than a
    # choice. The ARM64 runner is itself a colima container with no reachable
    # docker daemon, so it cannot start the pinned manylinux image - the leg
    # dies in `Initialize containers`. It therefore builds natively and inherits
    # the guest's glibc.
    #
    # Declared at what it can actually meet so the check still BINDS: at 2.28
    # this target would fail every build, which is a check that cries wolf, and
    # at "unlisted" it would assert nothing at all. 2.39 catches a regression
    # above the current line while stating the real requirement.
    #
    # This is a DIVERGENCE from x86_64 and should not be permanent. It closes
    # when an ARM64 Linux host that can run containers exists; that change moves
    # this line to (2, 28) and restores the image pin in binaries.yml together.
    #
    # docs/installation.md states this per-platform rather than promising a bare
    # "Linux" - the actual user-facing complaint in vaultspec-rag#409.
    "aarch64-unknown-linux-gnu": (2, 39),
}

# Section type of the GNU version-requirements table (``.gnu.version_r``).
SHT_GNU_VERNEED = 0x6FFFFFFE


class PlatformFloorError(RuntimeError):
    """An artifact requires a platform newer than its target triple declares."""



def _cstring(blob: bytes, offset: int) -> str:
    """Read the NUL-terminated string starting at *offset*."""
    end = blob.index(b"\x00", offset)
    return blob[offset:end].decode("utf-8")


def required_symbol_versions(asset: Path) -> set[str]:
    """Return every versioned symbol requirement recorded in an ELF binary.

    Read from the binary's own ``.gnu.version_r`` table, which is what the
    dynamic loader consults. A requirement recorded there is fatal at load time
    when the host's libc does not define that version, whether or not the
    symbols naming it are weak - so this, not the symbol bindings, is the thing
    that decides where an artifact can run.

    Parsed here rather than shelled out to ``readelf`` so the check needs
    nothing on the build machine but the standard library, and runs identically
    on a maintainer's laptop.
    """
    blob = asset.read_bytes()
    if blob[:4] != b"\x7fELF":
        raise PlatformFloorError(f"{asset.name} is not an ELF binary")
    if (blob[4], blob[5]) != (2, 1):
        raise PlatformFloorError(
            f"{asset.name} is not little-endian ELF64; "
            "every Linux target this builder produces is"
        )

    (section_table,) = struct.unpack_from("<Q", blob, 0x28)
    entry_size, count = struct.unpack_from("<HH", blob, 0x3A)

    versions: set[str] = set()
    for index in range(count):
        header = section_table + index * entry_size
        (kind,) = struct.unpack_from("<I", blob, header + 0x04)
        if kind != SHT_GNU_VERNEED:
            continue
        (offset,) = struct.unpack_from("<Q", blob, header + 0x18)
        strings, entries = struct.unpack_from("<II", blob, header + 0x28)
        # sh_link names the string table the version names live in; sh_info
        # counts the top-level entries, one per needed shared object.
        (string_table,) = struct.unpack_from(
            "<Q", blob, section_table + strings * entry_size + 0x18
        )
        versions |= _verneed_names(blob, offset, entries, string_table)
    return versions


def _verneed_names(
    blob: bytes, offset: int, entries: int, string_table: int
) -> set[str]:
    """Walk one ``.gnu.version_r`` table, returning the versions it requires."""
    names: set[str] = set()
    for _ in range(entries):
        auxiliary, next_entry = struct.unpack_from("<II", blob, offset + 0x08)
        cursor = offset + auxiliary
        (auxiliary_count,) = struct.unpack_from("<H", blob, offset + 0x02)
        for _ in range(auxiliary_count):
            name, next_auxiliary = struct.unpack_from("<II", blob, cursor + 0x08)
            names.add(_cstring(blob, string_table + name))
            if not next_auxiliary:
                break
            cursor += next_auxiliary
        if not next_entry:
            break
        offset += next_entry
    return names


def glibc_version(requirement: str) -> tuple[int, ...] | None:
    """Return the numeric version of a ``GLIBC_x.y`` requirement, else None."""
    prefix = "GLIBC_"
    if not requirement.startswith(prefix):
        return None
    parts = requirement[len(prefix) :].split(".")
    if not all(part.isdigit() for part in parts):
        return None
    return tuple(int(part) for part in parts)


def check_platform_floor(asset: Path, target: str) -> None:
    """Fail the build when *asset* requires a libc newer than *target* allows.

    The build machine's glibc is what an unpinned Linux build ends up
    advertising, so this runs on the produced artifact rather than on the
    toolchain: it is the artifact, not the builder, that a user downloads.
    """
    floor = GLIBC_FLOOR.get(target)
    if floor is None:
        return
    exceeded = sorted(
        requirement
        for requirement in required_symbol_versions(asset)
        if (version := glibc_version(requirement)) is not None and version > floor
    )
    if exceeded:
        declared = ".".join(str(part) for part in floor)
        raise PlatformFloorError(
            f"{asset.name} requires {', '.join(exceeded)} but {target} declares a "
            f"floor of GLIBC_{declared}. The binary will not load on any host "
            f"below the versions it requires. Build this target against a libc "
            f"at or below the declared floor rather than the build machine's."
        )




def write_checksum(asset: Path) -> Path:
    """Write ``<asset>.sha256`` in ``sha256sum``-compatible format.

    ``newline=""`` is load-bearing, not cosmetic. Without it Python's text
    layer rewrites the trailing newline to the host line ending, so the
    Windows leg of the release matrix emits CRLF while every other leg emits
    LF. The aggregated ``SHA256SUMS`` then carries mixed endings and both
    downstream readers break on exactly the Windows rows: ``sha256sum -c``
    refuses to verify them, and a field-splitting reader sees the asset name
    with a trailing carriage return, so a lookup by name finds nothing. That
    is how vaultspec-core-v0.1.60 published a Scoop manifest with empty
    hashes out of a green run.
    """
    digest = hashlib.sha256(asset.read_bytes()).hexdigest()
    checksum = asset.with_name(asset.name + ".sha256")
    checksum.write_text(f"{digest}  {asset.name}\n", encoding="utf-8", newline="")
    return checksum


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--tag", help="release tag, e.g. vaultspec-rag-v0.4.6")
    source.add_argument("--version", help="PyPI version directly, e.g. 0.1.48")
    parser.add_argument(
        "--outdir",
        type=Path,
        default=Path("dist-bin"),
        help="directory to place the renamed binaries and checksums in",
    )
    parser.add_argument(
        "--target",
        help="Rust target triple to (cross-)build for; defaults to the host",
    )
    args = parser.parse_args()

    version = args.version if args.version else version_from_tag(args.tag)
    target = args.target if args.target else host_target_triple()

    outdir: Path = args.outdir
    outdir.mkdir(parents=True, exist_ok=True)

    produced: list[Path] = []
    with tempfile.TemporaryDirectory(prefix="pyapp-build-") as tmp:
        workdir = Path(tmp)
        for binary in BINARIES:
            raw = build_one(binary, version, target, workdir)
            asset = outdir / asset_name(binary, target)
            shutil.copy2(raw, asset)
            if not target.endswith("windows-msvc"):
                asset.chmod(0o755)
            # Refuse the artifact HERE, before it is renamed into place and
            # long before anything uploads it. A floor violation found after
            # publication is a user's loader error, not a build failure.
            check_platform_floor(asset, target)
            checksum = write_checksum(asset)
            produced.extend((asset, checksum))
            print(f"built {asset} ({asset.stat().st_size} bytes)", flush=True)

    print(f"\n{PROJECT_NAME} {version} binaries for {target}:")
    for path in produced:
        print(f"  {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

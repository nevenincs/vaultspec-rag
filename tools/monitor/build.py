"""Build Vite once, then embed those exact bytes with a verified native Bun."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import tempfile
import tomllib
from pathlib import Path
from urllib.parse import quote

from tools.binaries.build_pyapp import (
    APPLICATION_ICON,
    check_platform_floor,
    version_from_tag,
    write_checksum,
)
from tools.binaries.bun_pins import BUN_EXECUTABLES, BUN_VERSION
from tools.binaries.bun_toolchain import provision_bun
from tools.binaries.windows_icon import product_version_info, stamp_icon_and_version
from tools.monitor.frontend import (
    MANIFEST,
    Frontend,
    prepare_frontend,
    validate_frontend,
)
from tools.monitor.pins import PINS_PATH, GeneratedPins, digests_for, write
from tools.packaging.bundles import BundleSpec, build_monitor_archive
from tools.packaging.products import (
    MONITOR_EXECUTABLE,
    VAULTSPEC_RAG,
    is_windows_target,
)
from vaultspec_rag._atomic_write import replace_atomically
from vaultspec_rag.monitor_runtime._pins import PinProvenance
from vaultspec_rag.native_binary._install import (
    extract_verified_archive,
    file_sha256,
    mark_executable,
    verify_native_binary,
)
from vaultspec_rag.native_binary._targets import host_target

ROOT = Path(__file__).resolve().parents[2]


def checkout_revision() -> str:
    """Read the producer identity from this checkout."""
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        timeout=15,
    ).stdout.strip()


def release_identity(tag: str, revision: str, *, development: bool = False) -> Frontend:
    """Bind the frontend handoff to the same producer and lock as native jobs."""
    actual = checkout_revision()
    if actual != revision:
        raise ValueError(f"Release checkout is {actual}, expected {revision}")
    dirty = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=all"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        timeout=15,
    ).stdout.strip()
    if dirty and not development:
        raise ValueError(
            "A release monitor requires a clean producer checkout. "
            "Use --development for an explicitly marked local build."
        )
    return Frontend(
        version_from_tag(tag),
        revision,
        file_sha256(ROOT / "package-lock.json"),
        {},
        development=development,
    )


def generated_entry(directory: Path, frontend: Path, identity: Frontend) -> Path:
    """Use file imports so Bun preserves Vite output instead of compiling it again."""
    lines = [
        'import { readFileSync } from "node:fs";',
        "import { startMonitor } from "
        + json.dumps((ROOT / "src/monitor/server/standalone.ts").as_posix())
        + ";",
    ]
    entries: list[str] = []
    for index, (name, asset) in enumerate(identity.assets.items()):
        lines.append(
            f"import file{index} from {json.dumps((frontend / name).as_posix())}"
            ' with { type: "file" };'
        )
        entries.append(
            "["
            + json.dumps("/" + quote(name, safe="/"))
            + f", {{ body: readFileSync(file{index}), content_type: "
            + json.dumps(asset.content_type)
            + ", sha256: "
            + json.dumps(asset.sha256)
            + " }]"
        )
    build = {
        "version": identity.version,
        "source_revision": identity.source_revision,
        "lock_sha256": identity.lock_sha256,
        "frontend_sha256": file_sha256(frontend / MANIFEST),
        "bun_version": BUN_VERSION,
        "development": identity.development,
    }
    lines.append(
        "await startMonitor(new Map(["
        + ",\n".join(entries)
        + "]), "
        + json.dumps(build)
        + ").catch(error => {"
        + "console.error(error.code ? error.code + ': ' + error.message "
        + ": error.message);"
        + "process.exit(1);});"
    )
    path = directory / "entry.ts"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def finalize(binary: Path, version: str, target: str) -> None:
    """Finish resources, signing and modes before any executable checksum."""
    if is_windows_target(target):
        stamp_icon_and_version(
            binary,
            APPLICATION_ICON,
            product_version_info(VAULTSPEC_RAG, MONITOR_EXECUTABLE, version, target),
        )
    else:
        binary.chmod(0o755)
        if target.endswith("apple-darwin"):
            subprocess.run(
                [
                    "codesign",
                    "--force",
                    "--sign",
                    "-",
                    "--entitlements",
                    str(Path(__file__).with_name("entitlements.plist")),
                    str(binary),
                ],
                check=True,
                timeout=60,
            )
            subprocess.run(
                ["codesign", "--verify", "--strict", str(binary)],
                check=True,
                timeout=30,
            )
    check_platform_floor(binary, target)


def compile_monitor(
    frontend: Path,
    outdir: Path,
    cache: Path,
    identity: Frontend,
    frontend_sha256: str,
) -> Path:
    target = host_target()
    if target not in VAULTSPEC_RAG.supported_targets:
        raise ValueError(f"Unsupported native monitor host: {target}")
    identity = validate_frontend(frontend, identity, manifest_sha256=frontend_sha256)
    binary = (outdir / VAULTSPEC_RAG.asset_name(MONITOR_EXECUTABLE, target)).resolve()
    binary.parent.mkdir(parents=True, exist_ok=True)
    bun = provision_bun(cache, target)
    with tempfile.TemporaryDirectory(prefix="monitor-compile-") as scratch:
        entry = generated_entry(Path(scratch), frontend.resolve(), identity)
        verify_native_binary(bun, BUN_EXECUTABLES[target])
        environment = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith("BUN_")
        }
        subprocess.run(
            [
                str(bun),
                "build",
                str(entry),
                "--compile",
                "--minify",
                "--define",
                "MONITOR_COMPILED=true",
                "--no-compile-autoload-dotenv",
                "--no-compile-autoload-bunfig",
                "--outfile",
                str(binary),
            ],
            cwd=ROOT,
            env=environment,
            check=True,
            timeout=300,
        )
    finalize(binary, identity.version, target)
    write_checksum(binary)
    return binary


def build_frontend(outdir: Path, identity: Frontend) -> None:
    """Produce the canonical npm/Vite handoff for release or local tests."""
    npm = shutil.which("npm")
    if npm is None:
        raise RuntimeError("Restore the pinned npm toolchain before the Vite build")
    subprocess.run([npm, "run", "build"], cwd=ROOT, check=True, timeout=300)
    prepare_frontend(ROOT / "src/monitor/dist", outdir, identity)


def checkout_version() -> str:
    """Return the version this checkout builds, as the package declares it."""
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return str(project["project"]["version"])


def build_development_monitor(outdir: Path, cache: Path) -> Path:
    """Use the release compiler for explicitly marked local/CI development bytes."""
    identity = release_identity(
        f"vaultspec-rag-v{checkout_version()}",
        checkout_revision(),
        development=True,
    )
    with tempfile.TemporaryDirectory(prefix="monitor-development-frontend-") as scratch:
        frontend = Path(scratch) / "frontend"
        build_frontend(frontend, identity)
        return compile_monitor(
            frontend, outdir, cache, identity, file_sha256(frontend / MANIFEST)
        )


def install_development_monitor(binary: Path, version: str, programs: Path) -> Path:
    """Admit the monitor compiled here and install it where this checkout looks.

    The whole of what a checkout needs so that starting the service finds its
    monitor: the compiled executable is packed into the same provisioning
    archive a release publishes, its digests are generated into the package as
    a development pin, and the executable the archive carries is installed
    beside this environment's own programs, which is where resolution looks
    for a monitor an installation brought with it. Nobody exports anything and
    nobody is asked to.

    The install goes through the verification a release install goes through:
    the archive is hashed before anything is extracted from it, and what comes
    out is hashed again before it lands. The pin is written last, so a failure
    anywhere leaves the previous one admitting the monitor that is still
    installed.

    Args:
        binary: The finalized, target-qualified monitor this checkout compiled.
        version: The version this checkout builds, which the pin is bound to.
        programs: Where this installation's own programs are, which is where
            the executable is installed.

    Returns:
        The installed executable.

    Raises:
        BundleError: When the compiled monitor or the archive packed from it is
            not the single-member provisioning archive a release publishes.
        ChecksumMismatchError: When the archive does not hash to the digest
            taken from it, which is a file changing underneath the build.
        RuntimeError: When the extracted or installed executable does not hash
            to the digest the pin will carry, so nothing unadmitted is left
            installed.
    """
    target = host_target()
    spec = BundleSpec(VAULTSPEC_RAG, version, target)
    installed = programs / spec.monitor_member
    with tempfile.TemporaryDirectory(prefix="monitor-archive-") as scratch:
        archive = build_monitor_archive(spec, binary.parent, Path(scratch))
        archive_sha256, executable_sha256 = digests_for(archive, binary)
        programs.mkdir(parents=True, exist_ok=True)
        # Staged inside the destination directory: the install is one rename,
        # and a rename is only atomic within one filesystem.
        with tempfile.TemporaryDirectory(
            prefix=".monitor-install-", dir=programs
        ) as landing:
            extracted, _ = extract_verified_archive(
                archive,
                archive_sha256,
                Path(landing),
                binary_name=spec.monitor_member,
            )
            verify_native_binary(extracted, executable_sha256)
            mark_executable(extracted)
            replace_atomically(extracted, installed)
    verify_native_binary(installed, executable_sha256)
    write(
        ROOT / PINS_PATH,
        GeneratedPins(
            provenance=PinProvenance.DEVELOPMENT,
            version=version,
            archives={target: archive_sha256},
            executables={target: executable_sha256},
        ),
    )
    return installed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("frontend", "compile", "develop"))
    parser.add_argument("--tag")
    parser.add_argument("--source-revision")
    parser.add_argument("--development", action="store_true")
    parser.add_argument("--outdir", type=Path, required=True)
    parser.add_argument("--frontend", type=Path)
    parser.add_argument("--frontend-sha256")
    parser.add_argument(
        "--cache", type=Path, default=Path(tempfile.gettempdir()) / "vaultspec-bun"
    )
    args = parser.parse_args()
    if args.operation == "develop":
        # Function-local: this names where the package looks for a program of
        # its own, and reaching it loads the package's settings. The release
        # operations below run under an interpreter with no site packages,
        # where that import cannot resolve and is not wanted; a development
        # build runs in the project environment, where it can.
        from vaultspec_rag._program_lookup import installation_programs

        version = checkout_version()
        binary = build_development_monitor(args.outdir, args.cache)
        print(
            install_development_monitor(
                binary, version, Path(installation_programs()[0])
            )
        )
        return
    if not args.tag or not args.source_revision:
        parser.error("Release builds require --tag and --source-revision")
    identity = release_identity(
        args.tag, args.source_revision, development=args.development
    )
    if args.operation == "frontend":
        build_frontend(args.outdir, identity)
        print(args.outdir)
    else:
        if args.frontend is None or not args.frontend_sha256:
            parser.error("Native compilation requires --frontend and --frontend-sha256")
        print(
            compile_monitor(
                args.frontend, args.outdir, args.cache, identity, args.frontend_sha256
            )
        )


if __name__ == "__main__":
    main()

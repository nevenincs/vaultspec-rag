"""Build Vite once, then embed those exact bytes with a verified native Bun."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import tempfile
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
from tools.binaries.native import host_target_triple
from tools.binaries.windows_icon import product_version_info, stamp_icon_and_version
from tools.monitor.frontend import (
    MANIFEST,
    Frontend,
    prepare_frontend,
    validate_frontend,
)
from tools.packaging.products import (
    MONITOR_EXECUTABLE,
    VAULTSPEC_RAG,
    is_windows_target,
)
from vaultspec_rag.qdrant_runtime._provision import file_sha256, verify_native_binary

ROOT = Path(__file__).resolve().parents[2]


def release_identity(tag: str, revision: str, *, development: bool = False) -> Frontend:
    """Bind the frontend handoff to the same producer and lock as native jobs."""
    actual = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        timeout=15,
    ).stdout.strip()
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
    entries = []
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
    target = host_target_triple()
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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("frontend", "compile"))
    parser.add_argument("--tag", required=True)
    parser.add_argument("--source-revision", required=True)
    parser.add_argument("--development", action="store_true")
    parser.add_argument("--outdir", type=Path, required=True)
    parser.add_argument("--frontend", type=Path)
    parser.add_argument("--frontend-sha256")
    parser.add_argument(
        "--cache", type=Path, default=Path(tempfile.gettempdir()) / "vaultspec-bun"
    )
    args = parser.parse_args()
    identity = release_identity(
        args.tag, args.source_revision, development=args.development
    )
    if args.operation == "frontend":
        npm = shutil.which("npm")
        if npm is None:
            parser.error("Restore the pinned npm toolchain before the Vite build")
        subprocess.run([npm, "run", "build"], cwd=ROOT, check=True, timeout=300)
        prepare_frontend(ROOT / "src/monitor/dist", args.outdir, identity)
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

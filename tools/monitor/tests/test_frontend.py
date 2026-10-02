"""The native jobs receive immutable Vite bytes and producer identity."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from tools.monitor.frontend import (
    Frontend,
    inventory,
    prepare_frontend,
    validate_frontend,
)

pytestmark = pytest.mark.unit


def test_release_tools_run_with_no_site_packages() -> None:
    root = Path(__file__).resolve().parents[3]
    environment = dict(os.environ, PYTHONPATH="")
    result = subprocess.run(
        [sys.executable, "-S", "-c", "import tools.monitor.build, tools.monitor.smoke"],
        cwd=root,
        env=environment,
        capture_output=True,
        text=True,
        timeout=15,
    )
    # Eagerly importing service configuration in the native artifact owner
    # fails this boundary assertion in the bare interpreter.
    assert result.returncode == 0, result.stderr


def handoff(tmp_path: Path) -> tuple[Path, Frontend]:
    source = tmp_path / "vite"
    (source / "assets").mkdir(parents=True)
    (source / "index.html").write_text(
        '<script src="./assets/app.js"></script>', encoding="utf-8"
    )
    (source / "assets/app.js").write_text("console.log('built');", encoding="utf-8")
    (source / "assets/font.woff2").write_bytes(b"font fixture")
    identity = Frontend("1.2.3", "a" * 40, "b" * 64, {})
    destination = tmp_path / "handoff"
    return destination, prepare_frontend(source, destination, identity)


def test_handoff_preserves_assets_fonts_and_mime_types(tmp_path: Path) -> None:
    directory, identity = handoff(tmp_path)
    checked = validate_frontend(directory, identity)
    assert set(checked.assets) == {"index.html", "assets/app.js", "assets/font.woff2"}
    assert checked.assets["assets/font.woff2"].content_type == "font/woff2"
    assert (
        checked.assets["assets/app.js"].content_type == "text/javascript; charset=utf-8"
    )
    assert (directory / "assets/font.woff2").read_bytes() == b"font fixture"


@pytest.mark.parametrize("change", ["asset", "extra", "producer"])
def test_handoff_rejects_changed_bytes_or_identity(tmp_path: Path, change: str) -> None:
    directory, identity = handoff(tmp_path)
    if change == "asset":
        (directory / "assets/app.js").write_text("different", encoding="utf-8")
    elif change == "extra":
        (directory / "assets/untracked.js").write_text("extra", encoding="utf-8")
    else:
        identity = Frontend(identity.version, "c" * 40, identity.lock_sha256, {})
    # Bypassing the metadata comparison admits these mutations and fails here.
    with pytest.raises(ValueError, match="handoff identity or asset digest mismatch"):
        validate_frontend(directory, identity)


def test_rehashed_frontend_must_match_common_producer_digest(tmp_path: Path) -> None:
    import json

    from tools.monitor.frontend import MANIFEST
    from vaultspec_rag.qdrant_runtime._provision import file_sha256

    directory, identity = handoff(tmp_path)
    manifest = directory / MANIFEST
    digest = file_sha256(manifest)
    asset = directory / "assets/app.js"
    asset.write_bytes(b"different bytes")
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["assets"]["assets/app.js"].update(
        sha256=file_sha256(asset), size=asset.stat().st_size
    )
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    # Bypassing the common producer digest admits internally consistent changed bytes.
    with pytest.raises(ValueError, match="digest differs from the handoff"):
        validate_frontend(directory, identity, manifest_sha256=digest)


@pytest.mark.parametrize(
    "reference",
    ["missing.woff2", "../../outside.woff2", "https://cdn.invalid/font.woff2"],
)
def test_css_references_must_be_embedded(tmp_path: Path, reference: str) -> None:
    directory, _ = handoff(tmp_path)
    (directory / "assets/style.css").write_text(
        f"@font-face {{src: url('{reference}')}}", encoding="utf-8"
    )
    # Skipping reference validation must fail this named missing-asset assertion.
    with pytest.raises(ValueError, match="asset reference is not embedded"):
        inventory(directory)

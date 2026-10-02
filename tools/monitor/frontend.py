"""Exact Vite asset handoff, keyed by release identity and the npm lock."""

from __future__ import annotations

import json
import posixpath
import re
import shutil
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING
from urllib.parse import unquote, urlsplit

from vaultspec_rag.qdrant_runtime._provision import file_sha256

if TYPE_CHECKING:
    from pathlib import Path

MANIFEST = "frontend.json"
SCHEMA = "vaultspec.monitor.frontend.v1"
CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
    ".ttf": "font/ttf",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ico": "image/x-icon",
    ".json": "application/json; charset=utf-8",
}


@dataclass(frozen=True)
class Asset:
    sha256: str
    size: int
    content_type: str


@dataclass(frozen=True)
class Frontend:
    version: str
    source_revision: str
    lock_sha256: str
    assets: dict[str, Asset]
    schema: str = SCHEMA
    development: bool = False


def inventory(directory: Path) -> dict[str, Asset]:
    """Include every regular file, with no symlink or unknown MIME fallback."""
    assets: dict[str, Asset] = {}
    for path in sorted(directory.rglob("*")):
        if path.is_symlink():
            raise ValueError(f"Frontend handoff contains a symlink: {path}")
        if path.is_dir() or path == directory / MANIFEST:
            continue
        content_type = CONTENT_TYPES.get(path.suffix)
        if content_type is None or not path.is_file():
            raise ValueError(f"Unsupported frontend asset: {path}")
        assets[path.relative_to(directory).as_posix()] = Asset(
            file_sha256(path), path.stat().st_size, content_type
        )
    if "index.html" not in assets or not any(name.endswith(".js") for name in assets):
        raise ValueError("The Vite handoff requires its HTML and JavaScript assets")
    validate_asset_references(directory, assets)
    return assets


def validate_asset_references(directory: Path, assets: dict[str, Asset]) -> None:
    """Require local HTML, CSS and literal module references to be embedded."""
    patterns = {
        ".html": r"(?:src|href)=[\"\x27]([^\"\x27]+)",
        ".css": r"url\(\s*[\"\x27]?([^\s)\"\x27]+)",
        ".js": r"\b(?:import\s*\(\s*|from\s*)[\"\x27]([^\"\x27]+)",
    }
    for name in assets:
        pattern = patterns.get(posixpath.splitext(name)[1])
        if pattern is None:
            continue
        content = (directory / name).read_text(encoding="utf-8")
        for reference in re.findall(pattern, content):
            url = urlsplit(reference)
            if url.scheme in {"data", "blob"} or not url.path:
                continue
            resolved = posixpath.normpath(
                unquote(url.path).lstrip("/")
                if url.path.startswith("/")
                else posixpath.join(posixpath.dirname(name), unquote(url.path))
            )
            if url.scheme or url.netloc or resolved not in assets:
                raise ValueError(
                    f"Frontend asset reference is not embedded: {name}: {reference}"
                )


def prepare_frontend(source: Path, destination: Path, identity: Frontend) -> Frontend:
    """Publish one immutable asset inventory; compilation never rebuilds Vite."""
    if destination.exists():
        raise ValueError(f"The frontend handoff already exists: {destination}")
    assets = inventory(source)
    shutil.copytree(source, destination)
    result = Frontend(
        identity.version,
        identity.source_revision,
        identity.lock_sha256,
        assets,
        development=identity.development,
    )
    (destination / MANIFEST).write_text(
        json.dumps(asdict(result), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return result


def validate_frontend(
    directory: Path, expected: Frontend, *, manifest_sha256: str | None = None
) -> Frontend:
    """Reject changed, missing or extra assets and mismatched producer identities."""
    if not re.fullmatch(r"[0-9a-f]{40}", expected.source_revision):
        raise ValueError("Frontend producer revision must be a full commit ID")
    if (
        manifest_sha256 is not None
        and file_sha256(directory / MANIFEST) != manifest_sha256
    ):
        raise ValueError("The common frontend manifest digest differs from the handoff")
    assets = inventory(directory)
    actual = Frontend(
        expected.version,
        expected.source_revision,
        expected.lock_sha256,
        assets,
        development=expected.development,
    )
    payload = json.loads((directory / MANIFEST).read_text(encoding="utf-8"))
    if payload != asdict(actual):
        raise ValueError("Frontend handoff identity or asset digest mismatch")
    return actual

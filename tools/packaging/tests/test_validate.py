"""The channel-pointer validator, exercised on real generator output.

The fixtures here are not hand-written manifests. Each test generates a real
pointer pair with the real generator, then breaks exactly one invariant, so a
change to the rendering that silently stops satisfying an assertion shows up
here rather than at install time.

That distinction matters for this guard in particular: the failure it exists to
catch is a manifest that looks entirely correct except for two empty strings.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from tools.binaries.build_pyapp import BINARIES, asset_name
from tools.packaging import products
from tools.packaging.generate import formula_path, generate, scoop_path
from tools.packaging.products import VAULTSPEC_RAG
from tools.packaging.validate import validate

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.unit

TAG = "vaultspec-rag-v9.9.9"
_DIGEST = "a" * 64


@pytest.fixture
def channel_root(tmp_path: Path) -> Path:
    """A generated, well-formed pair of channel pointers in a scratch root."""
    lines = [
        f"{_DIGEST}  {asset_name(binary, target)}"
        for target in (*products.HOMEBREW_TARGETS, products.WINDOWS_X86_64)
        if VAULTSPEC_RAG.serves(target)
        for binary in BINARIES
    ]
    checksums = tmp_path / "SHA256SUMS"
    # newline="" so Windows does not translate to CRLF: the checksum reader
    # rejects a carriage return outright, and correctly so.
    checksums.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="")

    root = tmp_path / "tap"
    root.mkdir()
    generate(tag=TAG, checksums=checksums, product=VAULTSPEC_RAG, root=root)
    return root


def test_generated_pointers_validate_clean(channel_root: Path) -> None:
    """The generator's own output is publishable. Everything else is a delta."""
    assert validate(channel_root, VAULTSPEC_RAG) == []


def test_blank_scoop_hashes_are_refused(channel_root: Path) -> None:
    """The empty-hash failure, reproduced exactly.

    The manifest keeps its correct version and URLs; only the digests are
    emptied. Scoop cannot install this, and the release that shipped this shape
    in a sibling repository was green from end to end.
    """
    path = scoop_path(channel_root, VAULTSPEC_RAG)
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["hash"] = [""] * len(manifest["hash"])
    path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    problems = validate(channel_root, VAULTSPEC_RAG)
    assert problems
    assert all("not a sha256 digest" in problem for problem in problems)


def test_a_truncated_digest_is_refused(channel_root: Path) -> None:
    """Not merely non-empty - a digest must be a full sha256."""
    path = scoop_path(channel_root, VAULTSPEC_RAG)
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["hash"][0] = _DIGEST[:32]
    path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    assert any(
        "not a sha256 digest" in problem
        for problem in validate(channel_root, VAULTSPEC_RAG)
    )


def test_a_blank_formula_digest_is_refused(channel_root: Path) -> None:
    """The Homebrew side of the same failure."""
    path = formula_path(channel_root, VAULTSPEC_RAG)
    path.write_text(
        path.read_text(encoding="utf-8").replace(f'sha256 "{_DIGEST}"', 'sha256 ""', 1),
        encoding="utf-8",
    )

    assert any(
        "not a sha256 digest" in problem
        for problem in validate(channel_root, VAULTSPEC_RAG)
    )


def test_channels_disagreeing_about_the_version_are_refused(
    channel_root: Path,
) -> None:
    """Both are generated from one aggregate, so a divergence is a half-failure."""
    path = formula_path(channel_root, VAULTSPEC_RAG)
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            'version "9.9.9"', 'version "9.9.8"', 1
        ),
        encoding="utf-8",
    )

    assert any(
        "channels disagree" in problem
        for problem in validate(channel_root, VAULTSPEC_RAG)
    )


def test_an_asset_no_build_produces_is_refused(channel_root: Path) -> None:
    """A pointer at a nonexistent asset is a 404 at install time and nowhere else."""
    path = scoop_path(channel_root, VAULTSPEC_RAG)
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["url"][0] = (
        "https://github.com/nevenincs/vaultspec-rag/releases/download/"
        f"{TAG}/vaultspec-rag-0.1.2-x86_64-pc-windows-msvc.msi"
    )
    path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    assert any(
        "names an asset no build produces" in problem
        for problem in validate(channel_root, VAULTSPEC_RAG)
    )


def test_a_missing_pointer_is_refused_rather_than_passing_vacuously(
    tmp_path: Path,
) -> None:
    """An empty root must fail. A validator that passes on nothing guards nothing."""
    problems = validate(tmp_path, VAULTSPEC_RAG)
    assert problems
    assert all("does not exist" in problem for problem in problems)

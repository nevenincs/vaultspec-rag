"""Refuse to publish a channel pointer that a package manager cannot install.

The generators are unit-tested against synthetic input. What that leaves
untested is the REAL pointer, at the moment it is produced - and that is where
the failure lives. vaultspec-core shipped a Scoop manifest carrying the right
version and the right URLs alongside ``"hash": ["", ""]``: the release job was
green, the unit tests were green, and nothing looked at what had been written.

This repository is exposed to the same class of failure and had no equivalent
check at all.

It runs between GENERATING the pointers and COMMITTING them, which is the only
point where a bad pointer can still be stopped rather than reported after it
has shipped. It validates whatever root the release generated into - the
``nevenincs/homebrew-tap`` checkout - rather than anything in this repository,
because a channel root is per-account rather than per-product and the copies
that used to sit in ``bucket/`` and ``Formula/`` here were three releases stale
while the live tap moved on.

Offline by construction. Verifying a digest against the release would need the
network; what is checked is internal consistency - well-formed digests,
agreement between the two channels, and agreement with the asset names the
build matrix can actually produce.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from tools.binaries.build_pyapp import BINARIES, asset_name
from tools.packaging import products
from tools.packaging.generate import formula_path, scoop_path
from tools.packaging.pointer import existing_homebrew_version, existing_scoop_version

if TYPE_CHECKING:
    from tools.packaging.products import Product

SHA256 = re.compile(r"^[0-9a-f]{64}$")

#: This repository (``tools/packaging/`` -> ``tools/`` -> repo), where the build
#: matrix lives. Distinct from the CHANNEL root, which is a tap checkout.
REPO_ROOT = Path(__file__).resolve().parents[2]

#: The workflow whose matrix decides what this repository can actually build.
_WORKFLOW = Path(".github") / "workflows" / "binaries.yml"

#: A matrix row's `target: <triple>`.
_MATRIX_TARGET = re.compile(r"^\s+target:\s+(\S+)\s*$", re.MULTILINE)


class UnknownTargetsError(RuntimeError):
    """The build matrix could not be read, so nothing can be called buildable."""


def buildable_targets(repo_root: Path) -> tuple[str, ...]:
    """The triples the build matrix declares, read from the matrix itself.

    This started as a hand-written list of every triple the products module
    knows, which made the check weaker than it looks: this product serves three
    targets and the module names five, so a pointer at a macOS asset - a
    platform this product does not support at all - validated clean.

    Derived instead, like the release guard's target list (#422) and for the
    same reason: a second copy of the matrix drifts from it, and every instance
    of that in this fleet was invisible until something shipped broken.
    """
    try:
        text = (repo_root / _WORKFLOW).read_text(encoding="utf-8")
    except OSError as exc:
        raise UnknownTargetsError(f"cannot read {_WORKFLOW}: {exc}") from exc
    targets = tuple(sorted(set(_MATRIX_TARGET.findall(text))))
    if not targets:
        raise UnknownTargetsError(
            f"{_WORKFLOW} declares no build target; refusing to treat every "
            f"asset name as unbuildable on the strength of a parse failure",
        )
    return targets


def _buildable_asset_names(repo_root: Path) -> set[str]:
    return {
        asset_name(binary, target)
        for binary in BINARIES
        for target in buildable_targets(repo_root)
    }


def validate(root: Path, product: Product, repo_root: Path | None = None) -> list[str]:
    """Return every reason these channel pointers are unfit to publish.

    ``root`` is the CHANNEL root - a checkout of the account tap. ``repo_root``
    is this repository, where the build matrix lives; the two are different
    trees, and conflating them is what left a stale copy of the pointers here.

    A list rather than an exception: a half-generated pair usually breaks in
    more than one way, and reporting only the first sends the maintainer round
    the loop again.
    """
    repo_root = REPO_ROOT if repo_root is None else repo_root
    problems: list[str] = []
    manifest_path = scoop_path(root, product)
    formula_file = formula_path(root, product)

    for path in (manifest_path, formula_file):
        if not path.is_file():
            problems.append(f"{path} does not exist")
    if problems:
        return problems

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    formula = formula_file.read_text(encoding="utf-8")

    # (a) the empty-hash failure - a pointer that installs nothing.
    hashes = manifest.get("hash") or []
    if not hashes:
        problems.append(f"{manifest_path}: pins no hashes")
    if len(hashes) != len(manifest.get("url") or []):
        problems.append(
            f"{manifest_path}: {len(hashes)} hash(es) for "
            f"{len(manifest.get('url') or [])} url(s)",
        )
    problems.extend(
        f"{manifest_path}: not a sha256 digest: {digest!r}"
        for digest in hashes
        if not SHA256.match(str(digest))
    )

    digests = re.findall(r'sha256 "([^"]*)"', formula)
    if not digests:
        problems.append(f"{formula_file}: pins no digests")
    problems.extend(
        f"{formula_file}: not a sha256 digest: {digest!r}"
        for digest in digests
        if not SHA256.match(digest)
    )

    # (b) both channels come from one aggregate, so a divergence means one was
    #     hand-edited or a generation half-failed.
    scoop_version = existing_scoop_version(manifest_path)
    brew_version = existing_homebrew_version(formula_file)
    if scoop_version is None:
        problems.append(f"{manifest_path}: names no version")
    if brew_version is None:
        problems.append(f"{formula_file}: names no version")
    if scoop_version is not None and scoop_version != brew_version:
        problems.append(
            f"channels disagree: scoop={scoop_version} homebrew={brew_version}",
        )

    # (c) every asset pointed at is one the builder can emit. A typo here is a
    #     404 at install time and nowhere earlier.
    referenced = {str(url).rsplit("/", 1)[-1] for url in manifest.get("url") or []}
    referenced |= set(re.findall(r'url "[^"]*/([^"/]+)"', formula))
    try:
        buildable = _buildable_asset_names(repo_root)
    except UnknownTargetsError as exc:
        # Not "assume everything is fine". An unreadable matrix means the
        # question cannot be answered, and answering it anyway - in either
        # direction - is how a check starts lying.
        problems.append(f"cannot determine what this repository builds: {exc}")
    else:
        unbuildable = sorted(referenced - buildable)
        problems.extend(
            f"names an asset no build produces: {name}" for name in unbuildable
        )

    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        required=True,
        type=Path,
        help="the channel root to validate (the tap checkout, not this repo)",
    )
    parser.add_argument(
        "--product",
        default=products.VAULTSPEC_RAG.name,
        choices=sorted(products.PRODUCTS),
        help="which product's channels to validate",
    )
    args = parser.parse_args()
    product = products.PRODUCTS[args.product]

    try:
        targets = buildable_targets(REPO_ROOT)
    except UnknownTargetsError as exc:
        print(f"::error::{exc}", file=sys.stderr, flush=True)
        return 1
    print(f"matrix builds: {', '.join(targets)}", flush=True)

    problems = validate(args.root, product)
    if problems:
        for problem in problems:
            print(f"::error::{problem}", file=sys.stderr, flush=True)
        print(
            f"::error::refusing to publish {product.name} channel pointers "
            f"from {args.root}",
            file=sys.stderr,
            flush=True,
        )
        return 1
    print(f"channel pointers for {product.name} are well-formed", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

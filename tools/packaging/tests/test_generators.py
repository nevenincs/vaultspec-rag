"""Guards for the Scoop manifest and Homebrew formula generators.

The contracts asserted here are the ones a package manager enforces at
install time on a user's machine, where a mistake is a failed install rather
than a failed build: the manifest names assets the release actually attached,
every pinned digest is the release's own, an unbuilt platform is absent
rather than invented, and a pointer never moves backward.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, cast

import pytest

from tools.binaries.build_pyapp import GLIBC_FLOOR
from tools.packaging import homebrew, products, scoop
from tools.packaging.checksums import ChecksumError
from tools.packaging.generate import _parser, available_targets, generate
from tools.packaging.pointer import PointerError, check_forward
from tools.packaging.products import VAULTSPEC_RAG

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.unit

VERSION = "0.4.6"
TAG = f"vaultspec-rag-v{VERSION}"

#: Every triple the release matrix attaches. macOS is absent because this
#: product is CUDA-only and does not build there - see products.py.
ALL_TARGETS = (
    products.WINDOWS_X86_64,
    products.LINUX_X86_64,
    products.LINUX_ARM64,
)


def digests_for(targets: tuple[str, ...] = ALL_TARGETS) -> dict[str, str]:
    """Return a synthetic but well-formed digest map for the given triples."""
    return {
        VAULTSPEC_RAG.bundle_name(VERSION, target): f"{index:064x}"
        for index, target in enumerate(targets, start=1)
    }


def write_aggregate(path: Path, digests: dict[str, str]) -> Path:
    """Write a ``SHA256SUMS`` file for the given digest map."""
    body = "".join(f"{digest}  {name}\n" for name, digest in digests.items())
    path.write_text(body, encoding="utf-8", newline="")
    return path


def test_generator_asset_names_match_the_bundle_contract() -> None:
    """The channel names the exact archive emitted for each target."""
    for target in ALL_TARGETS:
        asset = VAULTSPEC_RAG.bundle_name(VERSION, target)
        assert asset.startswith(f"vaultspec-rag-v{VERSION}-{target}")
        assert asset.endswith(
            ".zip" if target == products.WINDOWS_X86_64 else ".tar.gz"
        )


def test_scoop_manifest_pins_the_release_digests() -> None:
    """Every hash in the manifest comes from the aggregate, in URL order."""
    digests = digests_for()

    manifest = scoop.render_manifest(VAULTSPEC_RAG, VERSION, digests)

    urls = manifest["url"]
    hashes = manifest["hash"]
    assert isinstance(urls, list)
    assert isinstance(hashes, list)
    assert len(urls) == len(hashes) == 1
    asset = VAULTSPEC_RAG.bundle_name(VERSION, products.WINDOWS_X86_64)
    assert urls == [f"{VAULTSPEC_RAG.release_base_url(VERSION)}/{asset}"]
    assert hashes == [digests[asset]]
    assert manifest["bin"] == [
        ["vaultspec-rag.exe", "vaultspec-rag"],
        ["vaultspec-search-mcp.exe", "vaultspec-search-mcp"],
    ]
    autoupdate = cast("dict[str, object]", manifest["autoupdate"])
    assert autoupdate["url"] == [
        f"{VAULTSPEC_RAG.homepage}/releases/download/"
        f"{VAULTSPEC_RAG.tag_prefix}$version/"
        f"{VAULTSPEC_RAG.bundle_name('$version', products.WINDOWS_X86_64)}"
    ]


def test_scoop_manifest_never_emits_an_empty_hash() -> None:
    """The 0.4.6 failure mode, asserted directly.

    A missing digest must raise where it is looked up, not survive into a
    committed manifest that Scoop will refuse on the user's machine.
    """
    incomplete = digests_for()
    del incomplete[VAULTSPEC_RAG.bundle_name(VERSION, products.WINDOWS_X86_64)]

    with pytest.raises(ChecksumError, match="no entry for"):
        scoop.render_manifest(VAULTSPEC_RAG, VERSION, incomplete)


def test_scoop_manifest_is_valid_json_scoop_can_read() -> None:
    """The committed bytes round-trip, and name the version being installed."""
    rendered = scoop.render(VAULTSPEC_RAG, VERSION, digests_for())

    assert rendered.endswith("\n")
    assert json.loads(rendered)["version"] == VERSION


def test_homebrew_formula_pins_every_covered_platform() -> None:
    """Each built platform gets one bundle URL and digest."""
    digests = digests_for()

    formula = homebrew.render(VAULTSPEC_RAG, VERSION, digests, (products.LINUX_X86_64,))

    for target in (products.LINUX_X86_64,):
        asset = VAULTSPEC_RAG.bundle_name(VERSION, target)
        assert f"/{asset}" in formula
        assert f'sha256 "{digests[asset]}"' in formula
    assert formula.count('url "') == 1
    assert 'bin.install "vaultspec-rag"' in formula
    assert 'bin.install "vaultspec-search-mcp"' in formula


def test_homebrew_formula_uses_one_archive_for_both_commands() -> None:
    """The second command comes from the same archive, never a resource URL.

    Mutation proof: adding a second ``url`` line to the platform block made
    the exact URL-count assertion fail; the duplicate line was restored before
    the passing run.
    """
    formula = homebrew.render(
        VAULTSPEC_RAG, VERSION, digests_for(), (products.LINUX_X86_64,)
    )

    assert formula.count('url "') == 1
    assert formula.count('sha256 "') == 1
    assert formula.count("bin.install ") == len(VAULTSPEC_RAG.executables)
    assert "resource" not in formula


def test_homebrew_formula_omits_an_unbuilt_platform() -> None:
    """A gap in the build matrix is absent from the formula, not faked.

    Homebrew then reports an unsupported platform, which is true, instead of
    failing a checksum against an asset that was never published.
    """
    formula = homebrew.render(
        VAULTSPEC_RAG, VERSION, digests_for(), (products.LINUX_X86_64,)
    )

    assert products.LINUX_ARM64 not in formula
    assert "on_linux do" in formula


def test_homebrew_formula_declares_the_expected_ruby_surface() -> None:
    """The formula names its class, version, licence, and both executables."""
    formula = homebrew.render(
        VAULTSPEC_RAG,
        VERSION,
        digests_for(),
        (products.LINUX_X86_64,),
    )

    assert formula.startswith("class VaultspecRag < Formula\n")
    assert f'version "{VERSION}"' in formula
    assert 'license "MIT"' in formula
    assert 'bin.install "vaultspec-rag"' in formula
    assert 'bin.install "vaultspec-search-mcp"' in formula
    assert "resource(" not in formula
    assert formula.endswith("end\n")


def test_available_targets_requires_the_complete_bundle_on_a_platform() -> None:
    """A missing target bundle is not Homebrew coverage.

    Mutation proof: inverting the bundle-membership check made the exact
    target assertion fail; the check was restored before the passing run.
    """
    digests = digests_for()
    del digests[VAULTSPEC_RAG.bundle_name(VERSION, products.LINUX_X86_64)]

    assert products.LINUX_X86_64 not in available_targets(
        VAULTSPEC_RAG, VERSION, digests
    )
    assert products.LINUX_ARM64 in available_targets(VAULTSPEC_RAG, VERSION, digests)


def test_an_unsupported_platform_is_never_offered() -> None:
    """macOS is excluded even when assets for it exist.

    Homebrew runs on macOS, so nothing but the product's own
    supported_targets stops the formula offering an install there - and this
    product raises at startup without CUDA, which macOS never has.
    """
    digests = digests_for((products.MACOS_ARM64, products.LINUX_X86_64))

    resolved = available_targets(VAULTSPEC_RAG, VERSION, digests)

    assert products.MACOS_ARM64 not in resolved
    assert products.LINUX_X86_64 in resolved


@pytest.mark.parametrize(
    ("current", "incoming"),
    [("0.4.6", "0.4.5"), ("0.2.0", "0.1.99"), ("1.0.0", "0.9.9")],
)
def test_pointer_guard_refuses_a_backward_bump(current: str, incoming: str) -> None:
    """A stale re-run must not un-publish the current release."""
    with pytest.raises(PointerError, match="backward"):
        check_forward(current, incoming)


@pytest.mark.parametrize(
    ("current", "incoming"),
    [(None, "0.4.6"), ("0.4.6", "0.4.6"), ("0.4.5", "0.4.6")],
    ids=["first-publication", "converging-rerun", "forward"],
)
def test_pointer_guard_allows_first_equal_and_forward(
    current: str | None,
    incoming: str,
) -> None:
    """Publishing anew, converging a partial release, and bumping all pass."""
    check_forward(current, incoming)


def test_generate_writes_both_channels_and_guards_the_second_run(
    tmp_path: Path,
) -> None:
    """One invocation produces both pointers; an older tag is then refused."""
    aggregate = write_aggregate(tmp_path / "SHA256SUMS", digests_for())

    written = generate(tmp_path, VAULTSPEC_RAG, TAG, aggregate)

    assert [path.name for path in written] == [
        "vaultspec-rag.json",
        "vaultspec-rag.rb",
    ]
    assert json.loads(written[0].read_text(encoding="utf-8"))["version"] == VERSION

    with pytest.raises(PointerError, match="backward"):
        generate(tmp_path, VAULTSPEC_RAG, "vaultspec-rag-v0.4.5", aggregate)


def test_generate_writes_lf_line_endings(tmp_path: Path) -> None:
    """Committed channel files are LF on every host that generates them."""
    aggregate = write_aggregate(tmp_path / "SHA256SUMS", digests_for())

    for path in generate(tmp_path, VAULTSPEC_RAG, TAG, aggregate):
        assert b"\r" not in path.read_bytes()


def test_the_cli_default_product_is_one_it_can_resolve() -> None:
    """The parser's default product must be a product the CLI actually holds.

    A default naming something ``PRODUCTS`` does not carry fails while the
    parser is being built, so every invocation dies before it reads an
    argument - ``--help`` included, and the release job's call with it. The
    other tests here all reach ``generate`` directly and never build the
    parser, which is how a dangling default sat in ``main`` unnoticed.

    Mutation: pointed the default at a name ``PRODUCTS`` does not carry; this
    fails on parser construction, naming the missing member. Restored, it
    passes.
    """
    parsed = _parser().parse_args(
        ["--tag", "vaultspec-rag-v0.0.0", "--checksums", "SHA256SUMS"]
    )
    assert parsed.product in products.PRODUCTS


def test_homebrew_formula_states_the_shared_linux_glibc_floor() -> None:
    """A Linux install must be told the floor its loader will enforce.

    Homebrew serves Linux, so this formula's reader can install a binary whose
    dynamic loader then refuses it with a missing-symbol-version error. The
    floor is read from the table the build enforces after linking, so the two
    cannot drift apart.
    """
    targets = (products.WINDOWS_X86_64, products.LINUX_X86_64, products.LINUX_ARM64)
    formula = homebrew.render(
        VAULTSPEC_RAG, VERSION, digests_for(targets), available=targets
    )
    floor = ".".join(str(part) for part in GLIBC_FLOOR[products.LINUX_X86_64])
    assert f"Linux builds require glibc {floor} or newer." in formula


def test_homebrew_formula_states_each_floor_when_targets_disagree(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Divergent floors are stated per target, never collapsed into one.

    Naming a single floor across targets that do not share it either
    understates the requirement on one architecture or overstates it on the
    other, and both send a user to the wrong conclusion.
    """
    monkeypatch.setattr(
        homebrew,
        "GLIBC_FLOOR",
        {products.LINUX_X86_64: (2, 28), products.LINUX_ARM64: (2, 39)},
    )
    targets = (products.WINDOWS_X86_64, products.LINUX_X86_64, products.LINUX_ARM64)
    formula = homebrew.render(
        VAULTSPEC_RAG, VERSION, digests_for(targets), available=targets
    )
    assert f"{products.LINUX_X86_64} requires glibc 2.28 or newer." in formula
    assert f"{products.LINUX_ARM64} requires glibc 2.39 or newer." in formula
    assert "Linux builds require glibc" not in formula


def test_scoop_manifest_carries_no_glibc_caveat() -> None:
    """Scoop is Windows-only, so a glibc floor there is a caveat for nobody.

    The two channels deliberately share their notes; this one line is the
    exception, and it belongs only to the channel that serves the assets it
    constrains.
    """
    manifest = scoop.render(VAULTSPEC_RAG, VERSION, digests_for())
    assert "glibc" not in manifest.lower()

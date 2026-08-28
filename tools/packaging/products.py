"""The product identity every release channel renders from.

A channel manifest repeats the same handful of facts - the distribution name,
the binaries it places, the release tag scheme, the licence - in four
different syntaxes. Declaring them once here is what lets one generator serve
every product in the family, and what keeps a Scoop manifest and a Homebrew
formula cut from the same release from disagreeing about what the product is.

This module is the ONLY per-product file in the package. Everything beside it
is shared verbatim with vaultspec-core, which is what makes the delivery
idiom identical across the family rather than merely similar.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Rust target triples the delivery matrix builds, mapped to the channel that
#: consumes each one. A triple absent here is not deliverable: it may exist as
#: a release asset, but no package manager will point at it.
WINDOWS_X86_64 = "x86_64-pc-windows-msvc"
MACOS_ARM64 = "aarch64-apple-darwin"
MACOS_X86_64 = "x86_64-apple-darwin"
LINUX_X86_64 = "x86_64-unknown-linux-gnu"
LINUX_ARM64 = "aarch64-unknown-linux-gnu"

#: The triples Scoop serves. Scoop is Windows-only by construction.
SCOOP_TARGETS = (WINDOWS_X86_64,)

#: The triples Homebrew serves. Homebrew runs on macOS and on Linux, so a
#: formula covers both - which is why the absence of a Linux ARM64 build is a
#: delivery gap and not merely a missing convenience: Homebrew on Linux ARM64
#: is a supported platform this product cannot currently be installed on.
HOMEBREW_TARGETS = (MACOS_ARM64, MACOS_X86_64, LINUX_X86_64, LINUX_ARM64)


@dataclass(frozen=True)
class Executable:
    """One console entry point published as a standalone binary asset."""

    #: The name the binary is installed as, and the stem of its release asset.
    name: str
    #: Short description used where a channel labels the individual command.
    summary: str


@dataclass(frozen=True)
class Product:
    """One deliverable product and the identity its channels repeat."""

    #: PyPI distribution name; also the manifest and formula file stem.
    name: str
    #: Ruby class name for the Homebrew formula, e.g. ``VaultspecRag``.
    formula_class: str
    description: str
    homepage: str
    license: str
    #: Release tags are ``<tag_prefix><version>``.
    tag_prefix: str
    #: The binaries the release attaches, in installation order. The first is
    #: the formula's primary ``url``; the rest become Homebrew ``resource``
    #: blocks, because a formula has exactly one primary download.
    executables: tuple[Executable, ...]
    #: Channel-specific caveats surfaced to whoever installs from a manifest.
    notes: tuple[str, ...] = ()
    #: The triples this product can actually RUN on. Distinct from what a
    #: package manager serves: Homebrew runs on macOS, but a CUDA-only
    #: product cannot, and offering an install there ships a binary that
    #: raises at startup. Empty means "every target the channel serves".
    supported_targets: tuple[str, ...] = ()

    def serves(self, target: str) -> bool:
        """Return whether this product may be offered on ``target``."""
        return not self.supported_targets or target in self.supported_targets

    def version_from_tag(self, tag: str) -> str:
        """Return the version a release tag names.

        Accepts the canonical ``<prefix><version>`` tag and the bare ``v``
        and unprefixed forms a maintainer may pass when reproducing a
        release locally.
        """
        for prefix in (self.tag_prefix, "v"):
            if tag.startswith(prefix):
                return tag[len(prefix) :]
        return tag

    def tag_for(self, version: str) -> str:
        """Return the release tag that publishes ``version``."""
        return f"{self.tag_prefix}{version}"

    def asset_name(self, executable: Executable, target: str) -> str:
        """Return the release asset filename for one binary on one target.

        Must agree byte-for-byte with ``tools.binaries.build_pyapp.asset_name``;
        a channel manifest that names an asset the build never produced is a
        404 the user meets, not a build failure the maintainer meets.
        """
        suffix = ".exe" if target.endswith("windows-msvc") else ""
        return f"{executable.name}-{target}{suffix}"

    def release_base_url(self, version: str) -> str:
        """Return the immutable download base for one release."""
        return f"{self.homepage}/releases/download/{self.tag_for(version)}"


VAULTSPEC_RAG = Product(
    name="vaultspec-rag",
    formula_class="VaultspecRag",
    # Homebrew's audit caps `desc` at 80 characters and rejects one that opens
    # with the formula name, so this is a trimmed form of the PyPI summary
    # rather than a copy of it.
    description="Hybrid dense and sparse semantic search for your docs and source code",
    homepage="https://github.com/nevenincs/vaultspec-rag",
    license="MIT",
    tag_prefix="vaultspec-rag-v",
    executables=(
        Executable(name="vaultspec-rag", summary="the vaultspec-rag CLI"),
        Executable(
            name="vaultspec-search-mcp",
            summary="the semantic-search MCP server",
        ),
    ),
    # CUDA-ONLY. This is not a preference to soften in a channel manifest:
    # `embeddings.py`, `search/_searcher.py` and `server/_lifespan.py` each
    # raise RuntimeError when `torch.cuda.is_available()` is false, and
    # docs/installation.md states macOS and Apple Silicon are unsupported.
    # Homebrew runs on macOS, so without this the formula would offer an
    # install that places a binary raising at startup - a worse outcome than
    # not being installable, because it looks like a product defect.
    # Windows and Linux x86_64 only, which is exactly what binaries.yml builds.
    # Declaring a target the matrix does not build is not a promise of future
    # coverage: the generator warns and omits it on every single release, and
    # the formula silently lacks a platform the product claims to support.
    # aarch64-unknown-linux-gnu belongs here the moment a leg builds it - the
    # runner and its container already exist, matched to the sibling project's
    # pattern - but the host it runs on stands down on battery, so the leg is
    # commented out in binaries.yml and this list matches that reality.
    supported_targets=(WINDOWS_X86_64, LINUX_X86_64, LINUX_ARM64),
    notes=(
        # The binaries bootstrap the SAME accelerated torch build the project
        # resolves: `tools.binaries.torch_channel` pins the cu130 wheel from
        # uv.lock for every target built. Without it the bootstrap resolves
        # plain PyPI torch, which on Windows carries no CUDA at all.
        "Requires an NVIDIA GPU with a working CUDA driver; there is no CPU mode.",
        "First launch downloads the CUDA runtime; needs network once, and space.",
        "Same GPU torch build uv installs, pinned from this project's lock.",
        "Verify with: vaultspec-rag --version",
    ),
)

#: Every product this checkout generates channel manifests for, keyed by name.
PRODUCTS = {VAULTSPEC_RAG.name: VAULTSPEC_RAG}

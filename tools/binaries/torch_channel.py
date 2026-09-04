"""Resolve the accelerated torch wheel a release binary must bootstrap.

PyApp installs the published PyPI distribution on first launch. That install
resolves ``torch`` from default PyPI, and default PyPI is not what this
project ships against:

- On **Windows**, the PyPI wheel is CPU-only. It declares no ``nvidia-*`` or
  ``cuda-*`` dependency at all, so a binary that bootstraps it can never use a
  GPU. For a product whose headline capability is GPU-accelerated search, that
  is not a caveat to document - it is the capability being absent.
- On **Linux**, the PyPI wheel does carry the CUDA stack, but it is not the
  build this project resolves. ``pyproject.toml`` routes torch to the
  ``pytorch-cu130`` index for ``sys_platform == 'linux' or 'win32'``, and
  ``uv.lock`` pins ``2.13.0+cu130`` there.
- On **macOS**, no wheel is correct, because no macOS binary is built. The
  runtime is CUDA-only and raises without a CUDA device, and there is no CUDA
  build for macOS at any version. The mapping below therefore has no darwin
  entry, and the build matrix has no darwin leg.

``tool.uv.sources`` is a workspace setting, not wheel metadata, so none of it
survives into a ``uv pip install vaultspec-rag`` from PyPI. This module
reconstructs the same intent for the bootstrap.

Why a direct wheel reference rather than ``--extra-index-url``: the cu130
index mirrors 118 distributions, including ``numpy``, ``jinja2``, ``certifi``,
``filelock`` and other dependencies of this project. uv gives an extra index
priority over the default one, so passing the index as a flag would silently
source those from download.pytorch.org too. That is precisely why the project
marks the index ``explicit = true``, and a direct reference is the only way to
express "this one distribution, from there" on a bare ``uv pip install``
command line. It is also the pattern ``docs/installation.md`` already
prescribes for the ``uv tool install`` path.

Both the version and the index URL are read from the project's own lock and
config, so the pin cannot drift away from what the project resolves.
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from urllib.parse import quote

from vaultspec_rag.torch_config._lockfile import locked_torch_version

#: Rust target triple -> the wheel platform tag torch publishes for it.
#: A target absent here bootstraps from default PyPI. No such target is
#: currently built: the matrix covers exactly the CUDA platforms.
TORCH_PLATFORM_TAGS = {
    "x86_64-pc-windows-msvc": "win_amd64",
    "x86_64-unknown-linux-gnu": "manylinux_2_28_x86_64",
    "aarch64-unknown-linux-gnu": "manylinux_2_28_aarch64",
}

#: The uv index name the project routes torch through.
INDEX_NAME = "pytorch-cu130"


class TorchChannelError(RuntimeError):
    """The accelerated torch wheel cannot be resolved from project config."""


def _project_root() -> Path:
    """Return the repository root (``tools/binaries/`` -> ``tools/`` -> repo)."""
    return Path(__file__).resolve().parents[2]


def index_url(root: Path | None = None) -> str:
    """Return the accelerated index URL declared in ``pyproject.toml``."""
    root = root or _project_root()
    config = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    indexes = config.get("tool", {}).get("uv", {}).get("index", [])
    for index in indexes:
        if index.get("name") == INDEX_NAME:
            url = str(index["url"]).rstrip("/")
            if not url.startswith("https://"):
                raise TorchChannelError(f"{INDEX_NAME} index must be https: {url!r}")
            return url
    raise TorchChannelError(
        f"pyproject.toml declares no [[tool.uv.index]] named {INDEX_NAME!r}",
    )


def wheel_url(target: str, python_version: str, root: Path | None = None) -> str | None:
    """Return the accelerated torch wheel URL for one Rust target triple.

    Returns ``None`` for a target the accelerated index does not publish. No
    such target is currently in the build matrix; the branch is kept so that
    adding one fails open to PyPI rather than to a fabricated wheel URL.
    """
    tag = TORCH_PLATFORM_TAGS.get(target)
    if tag is None:
        return None
    root = root or _project_root()
    # cp313 for "3.13": torch wheels use the CPython ABI tag, and PyApp pins
    # the embedded interpreter to this same series.
    major, _, minor = python_version.partition(".")
    abi = f"cp{major}{minor}"
    version = quote(locked_torch_version(root, index_url(root)), safe="")
    return f"{index_url(root)}/torch-{version}-{abi}-{abi}-{tag}.whl"


def pip_extra_args(
    target: str,
    python_version: str,
    root: Path | None = None,
) -> str | None:
    """Return ``PYAPP_PIP_EXTRA_ARGS`` for one target, or ``None`` if unneeded.

    The value adds one direct requirement to the bootstrap's install command.
    It names no index, so every other distribution still resolves from PyPI.
    """
    url = wheel_url(target, python_version, root)
    if url is None:
        return None
    return f"torch @ {url}"

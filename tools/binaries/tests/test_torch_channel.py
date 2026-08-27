"""Guards on the accelerated torch pin the release binaries bootstrap.

The defect these exist for is not a crash. It is a binary that installs,
launches, runs every command correctly, and cannot use a GPU - on a product
whose headline capability is GPU-accelerated search. Nothing downstream
reports that; the first symptom is a user wondering why search is slow.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from tools.binaries.build_pyapp import PYTHON_VERSION
from tools.binaries.torch_channel import (
    INDEX_NAME,
    TORCH_PLATFORM_TAGS,
    TorchChannelError,
    index_url,
    locked_version,
    pip_extra_args,
    wheel_url,
)

pytestmark = pytest.mark.unit

ACCELERATED = (
    "x86_64-pc-windows-msvc",
    "x86_64-unknown-linux-gnu",
    "aarch64-unknown-linux-gnu",
)
MACOS = ("aarch64-apple-darwin", "x86_64-apple-darwin")


def test_windows_is_pinned_because_pypi_ships_no_gpu_build_there() -> None:
    """The core of the defect: default PyPI torch on Windows is CPU-only.

    Asserted as its own case rather than folded into the loop below, because
    Windows is the target where the absence of this pin removes the product's
    headline capability outright rather than merely selecting a different
    build of it.
    """
    args = pip_extra_args("x86_64-pc-windows-msvc", PYTHON_VERSION)

    assert args is not None
    assert args.startswith("torch @ https://download.pytorch.org/whl/cu130/")
    assert "win_amd64" in args


@pytest.mark.parametrize("target", ACCELERATED)
def test_every_accelerated_target_pins_the_locked_build(target: str) -> None:
    """Each pin names the exact version uv.lock resolves, not a floating one."""
    url = wheel_url(target, PYTHON_VERSION)

    assert url is not None
    # `+` is URL-encoded in a PEP 427 filename served over HTTP.
    assert locked_version().replace("+", "%2B") in url
    assert url.endswith(f"-{TORCH_PLATFORM_TAGS[target]}.whl")


@pytest.mark.parametrize("target", MACOS)
def test_macos_is_never_pinned(target: str) -> None:
    """No darwin wheel is invented, because no darwin binary is built.

    The runtime is CUDA-only and there is no CUDA build for macOS at any
    version. Returning a URL here would fabricate a wheel that does not
    exist; the build matrix has no darwin leg to request one.
    """
    assert wheel_url(target, PYTHON_VERSION) is None
    assert pip_extra_args(target, PYTHON_VERSION) is None


def test_the_pin_names_no_index_so_nothing_else_moves_off_pypi() -> None:
    """A direct reference, never ``--extra-index-url``.

    The cu130 index mirrors numpy, jinja2, certifi, filelock and other
    dependencies of this project, and uv gives an extra index priority over
    the default. Passing the index as a flag would silently source those from
    download.pytorch.org - which is why the project marks the index
    ``explicit = true`` in the first place.
    """
    for target in ACCELERATED:
        args = pip_extra_args(target, PYTHON_VERSION)
        assert args is not None
        assert "--extra-index-url" not in args
        assert "--index-url" not in args
        assert "--index-strategy" not in args
        assert args.count(" @ ") == 1


def test_the_pin_tracks_the_project_config_rather_than_restating_it() -> None:
    """Version and index come from uv.lock and pyproject, so they cannot drift."""
    root = Path(__file__).resolve().parents[3]
    config = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    declared = [
        index for index in config["tool"]["uv"]["index"] if index["name"] == INDEX_NAME
    ]

    assert len(declared) == 1
    assert index_url() == str(declared[0]["url"]).rstrip("/")

    lock = tomllib.loads((root / "uv.lock").read_text(encoding="utf-8"))
    accelerated = {
        package["version"]
        for package in lock["package"]
        if package["name"] == "torch"
        and package.get("source", {}).get("registry") == index_url()
    }
    assert accelerated == {locked_version()}


def test_the_pinned_targets_match_the_projects_own_platform_markers() -> None:
    """The binary bootstraps accelerated torch exactly where the project does.

    ``pyproject.toml`` routes torch to the accelerated index for
    ``sys_platform == 'linux' or sys_platform == 'win32'``. The build targets
    pinned here must be that same set expressed as Rust triples - no more, so
    macOS is not handed a wheel that does not exist, and no fewer, so no
    supported platform silently loses the GPU.
    """
    root = Path(__file__).resolve().parents[3]
    config = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    marker = config["tool"]["uv"]["sources"]["torch"][0]["marker"]

    assert "linux" in marker
    assert "win32" in marker
    assert "darwin" not in marker

    pinned_platforms = {
        "windows" if "windows" in target else "linux" for target in TORCH_PLATFORM_TAGS
    }
    assert pinned_platforms == {"windows", "linux"}


def test_a_missing_index_declaration_is_an_error_not_a_silent_fallback(
    tmp_path: Path,
) -> None:
    """Losing the index from pyproject must fail the build, not ship CPU torch."""
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")

    with pytest.raises(TorchChannelError, match=r"no \[\[tool\.uv\.index\]\]"):
        index_url(tmp_path)

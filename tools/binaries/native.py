"""Native build identity shared by the Python and frontend compilers."""

from __future__ import annotations

import platform


def host_target_triple() -> str:
    """Return a Rust-style target triple without launching another compiler."""
    architectures = {
        "amd64": "x86_64",
        "x86_64": "x86_64",
        "arm64": "aarch64",
        "aarch64": "aarch64",
    }
    systems = {
        "Windows": "pc-windows-msvc",
        "Linux": "unknown-linux-gnu",
        "Darwin": "apple-darwin",
    }
    try:
        return (
            f"{architectures[platform.machine().lower()]}-{systems[platform.system()]}"
        )
    except KeyError as exc:
        raise RuntimeError("The native build platform is unsupported") from exc

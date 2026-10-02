"""Reviewed native Bun release archives; build hosts never resolve latest."""

BUN_VERSION = "1.4.2"
BUN_RELEASE = f"https://github.com/oven-sh/bun/releases/download/bun-v{BUN_VERSION}"

# Release-authoring metadata is checked in here, outside the download trust path.
BUN_ARCHIVES: dict[str, tuple[str, str]] = {
    "aarch64-apple-darwin": (
        "bun-darwin-aarch64.zip",
        "90987a3a16d7db556d886ac3d551e7b6d3edf0a1cf43acaed622e8676be1d12f",
    ),
    "aarch64-unknown-linux-gnu": (
        "bun-linux-aarch64.zip",
        "54328bbc2d9c8e0c9f892c544d66c57a83b84139e34909e5ee81758f1ac8fda7",
    ),
    "x86_64-unknown-linux-gnu": (
        "bun-linux-x64.zip",
        "36368faef7527875d5ffa52e53cd48021741f2a83eb6208a8dd64068d422a913",
    ),
    "x86_64-pc-windows-msvc": (
        "bun-windows-x64.zip",
        "ce4c17497b2f29712a99d3d53f028de28cd42e3bacb8589599e7f000e49b6405",
    ),
}

# Derived only after verifying the archives above, without executing Bun.
BUN_EXECUTABLES: dict[str, str] = {
    "aarch64-apple-darwin": (
        "35d20dd0263e5c950194434b925454fdfa9ba6e4467da960410fa05b08a7a5b5"
    ),
    "aarch64-unknown-linux-gnu": (
        "616f267a34278ff5ac282df37ffdfba1d7141f4f6926bca99af2cd6ef3ad32b1"
    ),
    "x86_64-unknown-linux-gnu": (
        "a83d263767d839e4d2649ca8e35d07159c7afc99afdc96d731ced29e056dda0c"
    ),
    "x86_64-pc-windows-msvc": (
        "15277c59ccd6c6c20f8dc9716c2b59c1776320d606b6a8658f70be8799519ca4"
    ),
}

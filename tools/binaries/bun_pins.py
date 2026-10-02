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

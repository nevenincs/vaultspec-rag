"""One shared operator-facing unit vocabulary.

Byte counts reach operators from several surfaces - the storage survey, the
store write floor, and index admission refusals - and every one of them
divides by 1024. Rendering them from a single helper keeps those surfaces
from drifting into separate vocabularies, and keeps raw integers (a
``68719476736`` an operator has to convert by hand) out of human text.

Torch-free, qdrant-free, and CLI-free: the domain modules and the CLI
adapters both reach it.
"""

from __future__ import annotations

from typing import Final

__all__ = ["bytes_to_mib", "human_bytes", "mib_to_bytes"]

#: Binary magnitudes, labelled with the IEC units the 1024 divisor actually
#: produces. Labelling a 1024-divided value "GB" understates it by ~7%.
_UNITS: Final = ("B", "KiB", "MiB", "GiB", "TiB")

#: One mebibyte. Every megabyte-denominated reading in the codebase - the RSS
#: and CUDA probes, the memory ceilings, the GPU diagnostics - divides by this,
#: so it is spelled once and named rather than restated as a bare literal.
_BYTES_PER_MIB: Final = 1024.0 * 1024.0


def bytes_to_mib(num_bytes: float) -> float:
    """Convert a raw byte count to mebibytes.

    The ``_mb`` suffixes throughout the memory probe, the budget ceilings, and
    the GPU diagnostics all denote this unit; the conversion lives here so a
    reading cannot pick up a decimal-megabyte divisor by accident.
    """
    return float(num_bytes) / _BYTES_PER_MIB


def mib_to_bytes(num_mib: float) -> int:
    """Convert a mebibyte reading back to whole bytes.

    The inverse direction exists because the corpus-support limits are
    denominated in bytes while every memory reading is denominated in
    mebibytes, so a projection between them crosses the unit boundary twice.
    Truncating rather than rounding keeps a projected high-water at or below
    the reading it came from, so a conversion can never invent headroom a
    ceiling check would then honour.
    """
    return int(float(num_mib) * _BYTES_PER_MIB)


def human_bytes(num_bytes: float) -> str:
    """Render a byte count in the largest binary unit that keeps it above 1.

    Args:
        num_bytes: The count to render. Negative values keep their sign.

    Returns:
        The count and its unit, e.g. ``"64.0 GiB"``. Whole bytes render
        without a fraction, because "0.0 B" reads as an unset field where
        "0 B" reads as a measurement.
    """
    size = float(num_bytes)
    sign = "-" if size < 0 else ""
    size = abs(size)
    for unit in _UNITS:
        if size < 1024.0 or unit == _UNITS[-1]:
            if unit == "B":
                return f"{sign}{size:.0f} B"
            return f"{sign}{size:.1f} {unit}"
        size /= 1024.0
    raise AssertionError("unreachable: the last unit always terminates the loop")

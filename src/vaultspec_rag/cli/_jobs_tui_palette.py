"""The jobs interface's colour palette: one published specification, verbatim.

Every colour this interface paints comes from the scales below, copied
byte-for-byte from the published Radix Colors specification
(https://www.radix-ui.com/colors - package ``@radix-ui/colors`` version
3.0.0, the ``slate``, ``green``, ``amber``, ``red`` and ``blue`` scale CSS
files, light and dark). Nothing here is tuned, approximated, or invented;
a value that needs to change is re-copied from the specification, never
edited in place.

The step semantics are the specification's own: steps 1-2 are backgrounds,
3-5 component states, 6-8 borders, 9-10 solid fills, 11 low-contrast text,
12 high-contrast text. The semantic tokens below name a scale and a step
per those semantics, and the light and dark variants are the same tokens
resolved against the specification's published light and dark scales - the
pairing the specification itself keeps readable.

This module is the single source of colour for the interface. Status text
styles resolve through :func:`semantic_tones` and :func:`tone_style`;
window chrome resolves through the two theme objects
:func:`build_themes` returns. A colour literal anywhere else in the
interface is a defect, and a guard test scans the interface's modules for
exactly that.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual.theme import Theme

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = [
    "DARK_THEME_NAME",
    "LIGHT_THEME_NAME",
    "build_themes",
    "pill_fill",
    "semantic_tones",
    "tone_style",
]

# Scale values, steps 1 through 12 (index 0 through 11), exactly as
# published. Dark scales from the ``*-dark.css`` files, light from the
# ``*.css`` files, of the package version named in the module docstring.
_SLATE_DARK = (
    "#111113",
    "#18191b",
    "#212225",
    "#272a2d",
    "#2e3135",
    "#363a3f",
    "#43484e",
    "#5a6169",
    "#696e77",
    "#777b84",
    "#b0b4ba",
    "#edeef0",
)
_SLATE_LIGHT = (
    "#fcfcfd",
    "#f9f9fb",
    "#f0f0f3",
    "#e8e8ec",
    "#e0e1e6",
    "#d9d9e0",
    "#cdced6",
    "#b9bbc6",
    "#8b8d98",
    "#80838d",
    "#60646c",
    "#1c2024",
)
_GREEN_DARK = (
    "#0e1512",
    "#121b17",
    "#132d21",
    "#113b29",
    "#174933",
    "#20573e",
    "#28684a",
    "#2f7c57",
    "#30a46c",
    "#33b074",
    "#3dd68c",
    "#b1f1cb",
)
_GREEN_LIGHT = (
    "#fbfefc",
    "#f4fbf6",
    "#e6f6eb",
    "#d6f1df",
    "#c4e8d1",
    "#adddc0",
    "#8eceaa",
    "#5bb98b",
    "#30a46c",
    "#2b9a66",
    "#218358",
    "#193b2d",
)
_AMBER_DARK = (
    "#16120c",
    "#1d180f",
    "#302008",
    "#3f2700",
    "#4d3000",
    "#5c3d05",
    "#714f19",
    "#8f6424",
    "#ffc53d",
    "#ffd60a",
    "#ffca16",
    "#ffe7b3",
)
_AMBER_LIGHT = (
    "#fefdfb",
    "#fefbe9",
    "#fff7c2",
    "#ffee9c",
    "#fbe577",
    "#f3d673",
    "#e9c162",
    "#e2a336",
    "#ffc53d",
    "#ffba18",
    "#ab6400",
    "#4f3422",
)
_RED_DARK = (
    "#191111",
    "#201314",
    "#3b1219",
    "#500f1c",
    "#611623",
    "#72232d",
    "#8c333a",
    "#b54548",
    "#e5484d",
    "#ec5d5e",
    "#ff9592",
    "#ffd1d9",
)
_RED_LIGHT = (
    "#fffcfc",
    "#fff7f7",
    "#feebec",
    "#ffdbdc",
    "#ffcdce",
    "#fdbdbe",
    "#f4a9aa",
    "#eb8e90",
    "#e5484d",
    "#dc3e42",
    "#ce2c31",
    "#641723",
)
_BLUE_DARK = (
    "#0d1520",
    "#111927",
    "#0d2847",
    "#003362",
    "#004074",
    "#104d87",
    "#205d9e",
    "#2870bd",
    "#0090ff",
    "#3b9eff",
    "#70b8ff",
    "#c2e6ff",
)
_BLUE_LIGHT = (
    "#fbfdff",
    "#f4faff",
    "#e6f4fe",
    "#d5efff",
    "#c2e5ff",
    "#acd8fc",
    "#8ec8f6",
    "#5eb1ef",
    "#0090ff",
    "#0588f0",
    "#0d74ce",
    "#113264",
)

_SCALES: dict[str, dict[str, tuple[str, ...]]] = {
    "dark": {
        "slate": _SLATE_DARK,
        "green": _GREEN_DARK,
        "amber": _AMBER_DARK,
        "red": _RED_DARK,
        "blue": _BLUE_DARK,
    },
    "light": {
        "slate": _SLATE_LIGHT,
        "green": _GREEN_LIGHT,
        "amber": _AMBER_LIGHT,
        "red": _RED_LIGHT,
        "blue": _BLUE_LIGHT,
    },
}

# Semantic token -> (scale, step). Status text uses the specification's
# low-contrast text step (11), which its scale system keeps readable on the
# step 1-2 backgrounds the themes below use. The same tokens resolve
# against either variant's scales; nothing but the variant ever changes.
_TONE_STEPS: dict[str, tuple[str, int]] = {
    "good": ("green", 11),
    "attention": ("amber", 11),
    "bad": ("red", 11),
    "neutral": ("blue", 11),
    "muted": ("slate", 11),
}

# Internal registration names for the two variants of the one palette.
# They name the product's own themes and nothing else; no scheme name is
# ever surfaced to an operator.
DARK_THEME_NAME = "vaultspec-rag-dark"
LIGHT_THEME_NAME = "vaultspec-rag-light"


def _step(variant: str, scale: str, step: int) -> str:
    """Return the published value of *scale*'s *step* in *variant*."""
    return _SCALES[variant][scale][step - 1]


def semantic_tones(theme_name: str) -> dict[str, str]:
    """Resolve the semantic status tones for the variant *theme_name* names.

    The single seam every status colour resolves through: ``good``,
    ``attention``, ``bad``, ``neutral`` and ``muted``, each the documented
    text step of its scale. A name that is not the light variant resolves
    to the dark one - the interface's default surface.
    """
    variant = "light" if theme_name == LIGHT_THEME_NAME else "dark"
    return {
        token: _step(variant, scale, step)
        for token, (scale, step) in _TONE_STEPS.items()
    }


# The spec pairs its solid steps (9-10) with a contrast foreground: most
# solids take light text, and the bright amber solid is one of the scales
# the spec documents as taking dark text. Both foregrounds are in-scale
# values - the slate scales' own high-contrast text steps - never colours
# invented here. The solid steps are published identical across the light
# and dark scales for these hues, so a solid pill reads the same in both
# variants; only the muted pill follows the variant, as the component
# background (step 3) behind low-contrast text (step 11).
_SOLID_TEXT_LIGHT = _SLATE_DARK[11]
_SOLID_TEXT_DARK = _SLATE_LIGHT[11]


def pill_fill(theme_name: str) -> dict[str, tuple[str, str]]:
    """Resolve each semantic token's pill fill as ``(background, text)``.

    Solid fills per the specification's solid-step semantics; the muted
    token is the quiet component-background pairing so an empty or unknown
    pill recedes instead of shouting.
    """
    variant = "light" if theme_name == LIGHT_THEME_NAME else "dark"
    return {
        "good": (_step(variant, "green", 9), _SOLID_TEXT_LIGHT),
        "attention": (_step(variant, "amber", 9), _SOLID_TEXT_DARK),
        "bad": (_step(variant, "red", 9), _SOLID_TEXT_LIGHT),
        "neutral": (_step(variant, "blue", 9), _SOLID_TEXT_LIGHT),
        "muted": (_step(variant, "slate", 3), _step(variant, "slate", 11)),
    }


def tone_style(
    tones: Mapping[str, str],
    token: str,
    *,
    bold: bool = False,
    italic: bool = False,
) -> str:
    """Compose one style string from a resolved tone and its weight.

    Hierarchy on this surface is carried by weight and dimming more than
    hue, so the composition points are named here rather than restated at
    every call site.
    """
    parts = [name for flag, name in ((bold, "bold"), (italic, "italic")) if flag]
    colour = tones.get(token, "")
    if colour:
        parts.append(colour)
    return " ".join(parts)


def _theme(name: str, variant: str, *, dark: bool) -> Theme:
    """Build one variant's chrome from the same scales, per step semantics."""
    return Theme(
        name=name,
        primary=_step(variant, "blue", 9),
        secondary=_step(variant, "slate", 11),
        accent=_step(variant, "blue", 9),
        foreground=_step(variant, "slate", 12),
        background=_step(variant, "slate", 1),
        surface=_step(variant, "slate", 2),
        panel=_step(variant, "slate", 3),
        success=_step(variant, "green", 9),
        warning=_step(variant, "amber", 9),
        error=_step(variant, "red", 9),
        dark=dark,
    )


def build_themes() -> tuple[Theme, Theme]:
    """The palette's dark and light theme objects, in that order."""
    return (
        _theme(DARK_THEME_NAME, "dark", dark=True),
        _theme(LIGHT_THEME_NAME, "light", dark=False),
    )

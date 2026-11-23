"""Release instruments: the standalone binary builder and channel generators.

This file is load-bearing for the test suite, not just documentation. Without
it, ``tools`` is not a package, so pytest's ``prepend`` import mode resolves
``tools/conftest.py`` by inserting ``tools/`` itself at the head of
``sys.path`` - and ``tools/packaging/`` then shadows the ``packaging``
distribution for the whole session. Every module the root ``conftest.py``
reaches that imports ``packaging.requirements`` dies at collection with an
INTERNALERROR. Keeping ``tools`` a real package makes pytest insert the
repository root instead, which is also the path the ``tools.binaries.*``
imports in these tests already assume.

It is load-bearing for the release too. Every instrument here is spawned on a
bare interpreter with no project environment, and several read constants the
package owns rather than keeping a second copy of them. The checkout's own
source tree is therefore put on the path here, once, for whichever instrument
is imported first: done in one subpackage instead, an instrument that never
imported that subpackage could not find the package at all.
"""

import sys
from pathlib import Path

_SOURCE = str(Path(__file__).resolve().parent.parent / "src")
if _SOURCE not in sys.path:
    sys.path.insert(0, _SOURCE)

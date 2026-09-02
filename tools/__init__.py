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
"""

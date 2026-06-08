"""Package entry point for ``python -m vaultspec_rag.server``.

The resident service daemon is spawned as
``python -m vaultspec_rag.server --port N`` (see the CLI service
spawn). When ``server`` became a package (module-split ADR), the
``-m`` invocation stopped working because a package needs a
``__main__`` module to be directly executable. This thin module
restores it by delegating to ``main``, which parses ``--port`` /
``--help`` from ``sys.argv``.
"""

from __future__ import annotations

from ._main import main

if __name__ == "__main__":
    main()

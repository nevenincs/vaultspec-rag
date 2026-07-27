"""CLI application for vaultspec-rag.

VaultSpec RAG is a GPU-accelerated Retrieval-Augmented Generation (RAG) engine
that provides unified hybrid search over project documentation and source code.
It uses dense embeddings (Qwen3), sparse embeddings (SPLADE), and learned
reranking (CrossEncoder) to find the most relevant context for code generation,
code review, and documentation discovery.

Import order is load-bearing, but it is enforced by dependency rather than by
the order of the statements below: every command submodule imports the app or
sub-app it decorates from ``_app``, so ``_app`` has finished creating and
nesting them before any ``@*.command()`` decorator fires.

The command submodules are imported for that decorator side effect ALONE. They
contribute no names to this package - a command handler is reached by running
the CLI, never by importing its function - so importing them by name here would
be a re-export with no caller. They are named in ``__all__`` because the import
exists for its effect rather than for a symbol, and that is the difference
between a deliberate side-effect import and one a later reader deletes as unused.

What this package exports is only what its own consumers reach through the
package namespace rather than from the module that defines them: ``console``
and ``TerminationResult``, both read at call time through
``import vaultspec_rag.cli as _cli``. Reading them at call time keeps the
command modules from importing ``_core`` and the process module at their own
import time, which is what would put them in the decorator-registration cycle
described above.

Everything else is imported from the module that owns it. That sentence used
to be aspirational: twenty private names were re-exported here, and not one
had a production reader by any route - no from-import, no attribute access.
Production already reached each of them from its owning module, so the entry
here existed for tests alone. A name kept alive that way proves nothing about
the code that ships, and it makes this file look like the home of behaviour
that lives elsewhere.
"""

from __future__ import annotations

# Command submodules, imported purely so their decorators register against the
# apps ``_app`` nests. Nothing here is re-exported.
from . import (
    _index,
    _install,
    _preprocess,
    _service_doctor,
    _service_jobs,
    _service_lifecycle,
    _service_logs,
    _service_projects,
    _service_qdrant,
    _service_quiesce,
    _service_reconcile,
    _service_start,
    _service_stop,
    _service_storage,
    _service_watcher,
    _status,
    _status_render,
    _store,
)
from ._app import app, run_cli
from ._core import console
from ._process import TerminationResult

__all__ = [
    "TerminationResult",
    "_index",
    "_install",
    "_preprocess",
    "_service_doctor",
    "_service_jobs",
    "_service_lifecycle",
    "_service_logs",
    "_service_projects",
    "_service_qdrant",
    "_service_quiesce",
    "_service_reconcile",
    "_service_start",
    "_service_stop",
    "_service_storage",
    "_service_watcher",
    "_status",
    "_status_render",
    "_store",
    "app",
    "console",
    "run_cli",
]

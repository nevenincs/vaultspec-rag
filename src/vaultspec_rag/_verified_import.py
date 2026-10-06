"""Import Python source only after its bytes match a committed digest.

One model this package ships builds itself from a source file in its own
repository. Checking that file and then asking the model library to import it
checks one thing and runs another: the library does not import from the
snapshot. It copies the file into a modules cache of its own, and when a copy
is already there it imports that copy without comparing it to anything. A
stale or planted file in that cache is what would run, however carefully the
snapshot was verified.

So the library's route is not used. The source is read into memory once, that
buffer is hashed, and that same buffer is compiled and executed. There is no
second read and no copy on disk between the check and the execution, and no
bytecode cache is consulted or written, because a cached ``.pyc`` beside the
source would be a third thing that could run instead.
"""

from __future__ import annotations

import hashlib
import importlib.abc
import importlib.util
import sys
import threading
from typing import TYPE_CHECKING, override

if TYPE_CHECKING:
    from types import ModuleType

__all__ = ["UnverifiedSourceError", "import_verified_source"]

#: Where verified modules are registered. Keyed by digest, so the name says
#: which bytes a module was built from and a second import of the same bytes
#: finds the first.
_MODULE_PREFIX = "vaultspec_rag._verified_source_"

_import_lock = threading.Lock()


class UnverifiedSourceError(RuntimeError):
    """Source offered for import does not match its committed digest."""


class _VerifiedSourceLoader(importlib.abc.SourceLoader):
    """Serve one already-verified buffer as a module's source.

    ``get_data`` returns the buffer that was hashed and nothing else, whatever
    path it is asked for. ``path_stats`` is deliberately left undefined: the
    import machinery reads and writes bytecode caches only when it can stat
    the source, so leaving it out is what keeps every ``.pyc`` out of the
    picture.
    """

    def __init__(self, filename: str, source: bytes) -> None:
        self._filename = filename
        self._source = source

    @override
    def get_filename(self, fullname: str) -> str:
        """Return the name tracebacks show for this source."""
        del fullname
        return self._filename

    @override
    def get_data(self, path: str) -> bytes:
        """Return the verified buffer; the path is never opened."""
        del path
        return self._source


def import_verified_source(
    source: bytes, *, expected_sha256: str, filename: str
) -> ModuleType:
    """Execute *source* as a module, only if it hashes to *expected_sha256*.

    Args:
        source: The file's whole content, as read. This buffer is what is
            hashed and what is compiled.
        expected_sha256: The committed lower-case hex SHA256 of the file.
        filename: Where the source came from, for tracebacks and messages. It
            is not read.

    Returns:
        The module. Importing the same bytes again returns the same module.

    Raises:
        UnverifiedSourceError: If the buffer does not match the digest.
            Nothing from it has been compiled or executed.
    """
    actual = hashlib.sha256(source).hexdigest()
    if actual != expected_sha256:
        raise UnverifiedSourceError(
            f"{filename} does not match its committed SHA256 "
            f"(expected {expected_sha256}, got {actual}); it was not imported"
        )
    name = _MODULE_PREFIX + actual
    with _import_lock:
        existing = sys.modules.get(name)
        if existing is not None:
            return existing
        loader = _VerifiedSourceLoader(filename, source)
        spec = importlib.util.spec_from_loader(name, loader, origin=filename)
        if spec is None:
            raise UnverifiedSourceError(f"{filename} could not be prepared for import")
        module = importlib.util.module_from_spec(spec)
        # Registered before execution, as the import system does, because
        # class machinery run by the module body looks its own module up by
        # name. Removed again if the body fails, so a half-built module is
        # never found by the next caller.
        sys.modules[name] = module
        try:
            loader.exec_module(module)
        except BaseException:
            sys.modules.pop(name, None)
            raise
        return module

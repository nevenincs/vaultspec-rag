"""The one constructor for a client of a qdrant server.

Seven sites built this client from a URL, and only one of them passed a key.
The other six worked for as long as the server asked for none, which is how a
credential ends up enforced on the path someone looked at and absent on the
paths they did not. Resolving the key here, and nowhere else, means a server
client cannot be added without it.

The embedded on-disk store is not built here: it has no endpoint and no key.
"""

from __future__ import annotations

import warnings
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

from .qdrant_runtime._credential import server_api_key

if TYPE_CHECKING:
    from qdrant_client import QdrantClient

__all__ = ["open_server_client"]

_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1"})


def _is_loopback_literal(url: str) -> bool:
    try:
        return urlsplit(url).hostname in _LOOPBACK_HOSTS
    except ValueError:
        return False


def open_server_client(url: str, *, timeout: int | None = None) -> QdrantClient:
    """Open a client of the qdrant server at *url*, presenting its key.

    Args:
        url: The server's base URL.
        timeout: Per-request bound in seconds; ``None`` keeps the client's own.
    """
    from qdrant_client import QdrantClient as _QdrantClient

    api_key = server_api_key(url)
    with warnings.catch_warnings():
        if _is_loopback_literal(url):
            # The client warns whenever a key travels without TLS. To a
            # loopback literal the bytes never leave this host, so the warning
            # would fire on every store open and describe no exposure. To any
            # other host it is accurate and is left to be seen.
            warnings.filterwarnings(
                "ignore",
                message=".*Api key is used with an insecure connection.*",
                category=UserWarning,
            )
        return _QdrantClient(url=url, api_key=api_key, timeout=timeout)

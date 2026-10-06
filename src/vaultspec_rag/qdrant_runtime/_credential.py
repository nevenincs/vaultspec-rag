"""The managed qdrant child's credential: creation, publication, resolution.

The supervised child binds loopback TCP, and loopback separates hosts, not
operating-system accounts: without a credential every local user reaches the
collections directly, past the token the service in front of them demands. So
the child is started with an API key, which the server enforces on REST and
gRPC alike, and everything here exists to get that one key to the processes
entitled to it and to nobody else.

- **Published as an owner-only file**, beside the identity sidecar. More than
  one process is a client - the daemon, a second daemon attaching to a running
  child, the storage commands in a CLI process of their own - and a file only
  the owning account can read is how the service credential already travels.
  The process environment would not reach the CLI and would reach every
  subprocess the daemon starts.
- **Released to the managed endpoint only.** A configured key is the
  operator's and goes wherever the operator pointed the store. The managed key
  goes to the literal loopback address at the managed port and nowhere else:
  a name is resolved by something this process does not control, and whatever
  answered for it would be handed the key.
- **Verified, not assumed.** A binary that ignores the setting serves an open
  store while every signal reads healthy, so the data plane is asked both
  questions after readiness: an anonymous request must be refused and the key
  must be accepted.

Readiness and version probes stay anonymous: the server answers them without
a key by design, which is what lets a start decide what holds the port before
it knows whose server it is.
"""

from __future__ import annotations

import json
import logging
import secrets
import urllib.error
import urllib.request
from pathlib import Path
from typing import TYPE_CHECKING, cast
from urllib.parse import urlsplit

from .._atomic_write import JsonWriteOptions, write_json_atomically
from .._loopback_http import LOOPBACK_OPENER
from ..config._settings import get_config

if TYPE_CHECKING:
    from http.client import HTTPResponse

logger = logging.getLogger(__name__)

__all__ = [
    "data_plane_auth_fault",
    "generate_api_key",
    "is_managed_endpoint",
    "read_managed_api_key",
    "server_api_key",
    "write_managed_api_key",
]

_CREDENTIAL_FILENAME = "credential.json"
_API_KEY_FIELD = "api_key"
_API_KEY_HEADER = "api-key"
#: Bytes of secure randomness behind a generated key: 256 bits.
_API_KEY_BYTES = 32
_MANAGED_HOST = "127.0.0.1"
#: Bound on each request of the post-readiness check. Generous on purpose: the
#: check runs once per start, a healthy server answers in milliseconds, and a
#: false fault stops a child that may have taken minutes to load its store.
_AUTH_PROBE_TIMEOUT_SECONDS = 10.0
#: The statuses with which the server refuses a request for its credential.
_CREDENTIAL_REFUSALS = frozenset({401, 403})


def generate_api_key() -> str:
    """Return a fresh key from the operating system's secure random source."""
    return secrets.token_urlsafe(_API_KEY_BYTES)


def _credential_path(storage_dir: Path) -> Path:
    return storage_dir.parent / _CREDENTIAL_FILENAME


def write_managed_api_key(storage_dir: Path, api_key: str) -> Path:
    """Publish *api_key* for the child serving *storage_dir*, owner-only.

    The file is created already protected, so the key is never on disk under
    permissions another account could read.

    Returns:
        The path the credential was written to.
    """
    path = _credential_path(storage_dir)
    write_json_atomically(
        path, {_API_KEY_FIELD: api_key}, JsonWriteOptions(private=True)
    )
    return path


def read_managed_api_key(storage_dir: Path) -> str | None:
    """Read the key published for the child serving *storage_dir*.

    Returns:
        The key, or ``None`` when no child has published one or the record is
        unusable. An unusable record is logged, never raised: the caller then
        sends no key and the server's refusal names the real problem.
    """
    path = _credential_path(storage_dir)
    try:
        data = cast("object", json.loads(path.read_text(encoding="utf-8")))
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as exc:
        logger.debug("qdrant credential unreadable at %s: %s", path, exc)
        return None
    if not isinstance(data, dict):
        logger.debug("qdrant credential at %s is not an object", path)
        return None
    api_key = cast("dict[str, object]", data).get(_API_KEY_FIELD)
    if not isinstance(api_key, str) or not api_key:
        logger.debug("qdrant credential at %s carries no key", path)
        return None
    return api_key


def is_managed_endpoint(url: str) -> bool:
    """Whether *url* addresses the managed loopback child and nothing else."""
    try:
        endpoint = urlsplit(url)
        return (
            endpoint.scheme == "http"
            and endpoint.hostname == _MANAGED_HOST
            and endpoint.port == get_config().qdrant_port
            and endpoint.path in {"", "/"}
            and not endpoint.query
            and not endpoint.fragment
        )
    except ValueError:
        return False


def server_api_key(url: str) -> str | None:
    """Resolve the key a client of the qdrant server at *url* must present.

    Returns:
        The operator-configured key when one is set; otherwise the managed
        child's published key when *url* is the managed endpoint; otherwise
        ``None``.
    """
    cfg = get_config()
    configured = cfg.qdrant_api_key
    if configured:
        return configured
    if is_managed_endpoint(url):
        return read_managed_api_key(Path(cfg.qdrant_storage_dir).expanduser())
    return None


def _collections_status(url: str, api_key: str | None, timeout: float) -> int | None:
    """Ask the server at *url* to list collections; return the HTTP status.

    Listing collections is the cheapest request the server gates behind its
    key. ``None`` means no answer arrived at all.
    """
    request = urllib.request.Request(f"{url}/collections", method="GET")
    if api_key is not None:
        request.add_header(_API_KEY_HEADER, api_key)
    try:
        with cast(
            "HTTPResponse", LOOPBACK_OPENER.open(request, timeout=timeout)
        ) as resp:
            return resp.status
    except urllib.error.HTTPError as exc:
        return exc.code
    except (urllib.error.URLError, OSError, ValueError) as exc:
        logger.debug("qdrant data-plane probe on %s failed: %s", url, exc)
        return None


def data_plane_auth_fault(
    url: str, api_key: str, *, timeout: float = _AUTH_PROBE_TIMEOUT_SECONDS
) -> str | None:
    """Return why the server at *url* is not protected by *api_key*.

    Returns:
        ``None`` when an anonymous data request is refused and *api_key* is
        accepted; otherwise a reason fit for an operator-facing message. The
        key itself never appears in it.
    """
    anonymous = _collections_status(url, None, timeout)
    if anonymous == 200:
        return "it accepts data requests that carry no credential"
    if anonymous not in _CREDENTIAL_REFUSALS:
        answer = "nothing" if anonymous is None else f"HTTP {anonymous}"
        return (
            f"an anonymous data request was answered with {answer} instead of "
            "a credential refusal"
        )
    keyed = _collections_status(url, api_key, timeout)
    if keyed != 200:
        answer = "nothing" if keyed is None else f"HTTP {keyed}"
        return f"it answered the managed credential with {answer}"
    return None

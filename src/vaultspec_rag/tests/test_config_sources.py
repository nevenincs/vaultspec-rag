"""Unit tests for the settings that name a download source.

The managed Qdrant binary is fetched and then executed, so where it comes from
is a security setting rather than a tuning knob. Three properties hold it:

- the shipped default is the official release channel, and an operator can
  move it to a mirror through this package's own prefixed variable;
- a source that is not HTTPS, or a host pin that could match nothing, stops
  the process with every other unusable setting, before any download begins;
- nothing in a project can supply one: not a workspace ``.env``, not the
  project store. Repository content must never choose the server a host
  downloads an executable from.

Every case drives the real settings object over the real process environment.
"""

from __future__ import annotations

import os
from contextlib import chdir
from typing import TYPE_CHECKING

import pytest

from ..config._registry import entry
from ..config._schema import checked_setting, comma_separated
from ..config._settings import collect_environment_problems, get_config, rag_default
from ..config._types import EnvVar
from ._config_fixtures import reset_config
from ._scaffold import restore_env

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

pytestmark = [pytest.mark.unit]

_OFFICIAL_BASE_URL = "https://github.com/qdrant/qdrant/releases/download"
_OFFICIAL_HOSTS = frozenset(
    {
        "github.com",
        "release-assets.githubusercontent.com",
        "objects.githubusercontent.com",
    }
)

#: The settings that decide whether and from where a binary is downloaded.
_SOURCE_VARS = (
    EnvVar.QDRANT_AUTO_PROVISION,
    EnvVar.QDRANT_RELEASE_BASE_URL,
    EnvVar.QDRANT_DOWNLOAD_HOSTS,
)

_URL_SHAPE = "an https URL with a host and no credentials, query or fragment"
_HOSTS_SHAPE = (
    "a comma-separated list of host names, each without a scheme, port or path"
)


@pytest.fixture
def clean_sources() -> Iterator[None]:
    """Run from an environment that sets none of the source variables."""
    saved = {var: os.environ.pop(var.value, None) for var in _SOURCE_VARS}
    reset_config()
    try:
        yield
    finally:
        for var, previous in saved.items():
            restore_env(var, previous)
        reset_config()


def _configure(var: EnvVar, raw: str) -> None:
    """Set one source variable and drop the cached settings built before it."""
    os.environ[var.value] = raw
    reset_config()


@pytest.mark.usefixtures("clean_sources")
def test_the_defaults_are_the_official_release_channel() -> None:
    """Unset, the source is upstream's release channel and provisioning is on.

    The host set is the download path and nothing wider: the release API host
    is never contacted by a download, so pinning it would only widen where a
    redirect may land. Mutation: adding ``api.github.com`` to the shipped
    default failed the exact-set assertion; restoring it passed.
    """
    cfg = get_config()

    assert cfg.qdrant_auto_provision is True
    assert cfg.qdrant_release_base_url == _OFFICIAL_BASE_URL
    assert cfg.qdrant_download_hosts == _OFFICIAL_HOSTS


@pytest.mark.usefixtures("clean_sources")
def test_a_mirror_base_url_overrides_the_default() -> None:
    """A mirror is a different base: any host, a port and a path prefix.

    The trailing slash is dropped so the consumer's ``{base}/v{version}/{asset}``
    never doubles a separator.
    """
    _configure(
        EnvVar.QDRANT_RELEASE_BASE_URL,
        "  https://mirror.example:8443/artifactory/github-qdrant/  ",
    )

    assert (
        get_config().qdrant_release_base_url
        == "https://mirror.example:8443/artifactory/github-qdrant"
    )


@pytest.mark.usefixtures("clean_sources")
def test_a_host_list_override_replaces_the_default_and_is_normalised() -> None:
    """The list is what the operator wrote, case-folded, and nothing else.

    Replacing rather than extending is what lets a mirror deployment drop the
    upstream hosts it never talks to.
    """
    _configure(
        EnvVar.QDRANT_DOWNLOAD_HOSTS, " Mirror.Example , storage.mirror.example,, "
    )

    assert get_config().qdrant_download_hosts == frozenset(
        {"mirror.example", "storage.mirror.example"}
    )


@pytest.mark.parametrize("raw", ["0", "false", "no", "off"])
@pytest.mark.usefixtures("clean_sources")
def test_the_auto_provision_switch_turns_off(raw: str) -> None:
    _configure(EnvVar.QDRANT_AUTO_PROVISION, raw)

    assert get_config().qdrant_auto_provision is False


@pytest.mark.usefixtures("clean_sources")
def test_an_invocation_override_outranks_the_environment() -> None:
    """A flag for this run beats the session's standing choice, either way."""
    _configure(EnvVar.QDRANT_AUTO_PROVISION, "1")
    assert get_config({"qdrant_auto_provision": False}).qdrant_auto_provision is False

    _configure(EnvVar.QDRANT_AUTO_PROVISION, "0")
    assert get_config({"qdrant_auto_provision": True}).qdrant_auto_provision is True


@pytest.mark.parametrize(
    "raw",
    [
        "http://github.com/qdrant/qdrant/releases/download",
        "ftp://mirror.example/qdrant",
        "mirror.example/qdrant",
        "https:///qdrant/releases",
        "https://user:secret@mirror.example/qdrant",
        "https://user@mirror.example/qdrant",
        "https://mirror.example/qdrant?token=abc",
        "https://mirror.example/qdrant#latest",
        "https://mirror.example:notaport/qdrant",
        "https://mirror.example/qdrant releases",
    ],
    ids=[
        "plain-http",
        "other-scheme",
        "no-scheme",
        "no-host",
        "credentials",
        "username-only",
        "query",
        "fragment",
        "bad-port",
        "inner-whitespace",
    ],
)
@pytest.mark.usefixtures("clean_sources")
def test_an_unusable_base_url_is_refused_at_construction(raw: str) -> None:
    """A source that is not a plain HTTPS URL never reaches a download.

    The message names the variable, the key and the accepted shape, which is
    the refusal every other unusable setting gets. Mutations, each run against
    its own case: admitting the ``http`` scheme turned ``plain-http`` into
    DID NOT RAISE; dropping the credentials clause did the same to
    ``credentials``; dropping the query and fragment clauses to ``query``.
    Restoring each passed.
    """
    _configure(EnvVar.QDRANT_RELEASE_BASE_URL, raw)

    with pytest.raises(ValueError) as excinfo:
        get_config()

    message = str(excinfo.value)
    assert EnvVar.QDRANT_RELEASE_BASE_URL.value in message
    assert "qdrant_release_base_url" in message
    assert _URL_SHAPE in message


_URL_KEYS = ("qdrant_release_base_url", "hf_endpoint")


@pytest.mark.parametrize(
    "raw",
    [
        "https://mirror\x00.example/qdrant",
        "https://mirror\x01.example/qdrant",
        "https://mirror\x7f.example/qdrant",
        "https://mir\tror.example/qdrant",
        "https://mirror.example/qd\x01rant",
        "https://mirror.example:0/qdrant",
        "https://mirror_.example/qdrant",
        "https://-mirror.example/qdrant",
        "https://mirror..example.com/qdrant",
        "https://" + "a" * 64 + ".example/qdrant",
        "https://" + ".".join(["a" * 60] * 5) + ".example/qdrant",
    ],
    ids=[
        "nul-in-host",
        "control-in-host",
        "delete-in-host",
        "tab-in-host",
        "control-in-path",
        "port-zero",
        "underscore-in-host",
        "leading-hyphen",
        "empty-label",
        "label-over-63",
        "name-over-253",
    ],
)
@pytest.mark.parametrize("key", _URL_KEYS)
def test_a_url_no_connection_could_be_opened_to_is_refused(key: str, raw: str) -> None:
    """A host or port that could never reach a server is refused as a setting.

    None of these could be connected to, so nothing would be fetched from
    them; the point is where the failure lands. Refused here it names the
    setting and the accepted shape. Left alone it would surface later as a
    connection error that names neither.

    Checked through the validation every source reaches, because a null
    character cannot be placed in a process environment to drive it from
    there. Two tests overlap on a bad host, so each has a case only it
    catches. Mutations: with the character test removed, ``tab-in-host`` and
    ``control-in-path`` failed DID NOT RAISE, the other control cases still
    being refused by the host test; with the host test reduced to "a host is
    present", ``underscore-in-host`` and ``leading-hyphen`` failed the same
    way; with the port test removed, ``port-zero`` did. Restored after each,
    all passed.

    The last three are host names the URL parser accepts and the encoder a
    connection goes through does not: an empty label, a label over 63
    characters, a name over 253. Each is held by its own part of the host
    name pattern. Mutations: with a run of dots admitted between labels only
    ``empty-label`` failed DID NOT RAISE; with the first label's length limit
    removed only ``label-over-63`` did; with the whole-name limit removed
    only ``name-over-253`` did. Restored after each, all passed.
    """
    with pytest.raises(ValueError) as excinfo:
        checked_setting(key, raw, None)

    assert key in str(excinfo.value)
    assert _URL_SHAPE in str(excinfo.value)


@pytest.mark.parametrize(
    "raw",
    [
        "https://localhost/qdrant",
        "https://127.0.0.1:8443/qdrant",
        "https://[::1]:8443/qdrant",
        "https://Mirror.Example:443/a/b/",
    ],
    ids=["localhost", "ipv4-literal", "ipv6-literal", "mixed-case-with-port"],
)
@pytest.mark.parametrize("key", _URL_KEYS)
def test_a_url_a_connection_could_be_opened_to_is_still_admitted(
    key: str, raw: str
) -> None:
    """Tightening the host test must not refuse an address literal or a port."""
    assert checked_setting(key, raw, None) == raw.rstrip("/")


@pytest.mark.usefixtures("clean_sources")
def test_an_unusable_base_url_stops_the_process_at_the_startup_check() -> None:
    """The shared startup refusal reports it, so no process kind starts on it.

    The probe builds a throwaway settings object, so the refusal must not
    leave one cached for a later reader.
    """
    from ..config import _settings

    _configure(
        EnvVar.QDRANT_RELEASE_BASE_URL,
        "http://github.com/qdrant/qdrant/releases/download",
    )

    problems = collect_environment_problems(None)

    assert len(problems) == 1
    assert EnvVar.QDRANT_RELEASE_BASE_URL.value in problems[0]
    assert _URL_SHAPE in problems[0]
    assert _settings._cached_config is None


@pytest.mark.parametrize(
    "raw",
    [
        "https://github.com",
        "github.com:443",
        "github.com/qdrant",
        "*.githubusercontent.com",
        "github.com, not a host",
        "-leading.example",
        ",",
    ],
    ids=[
        "scheme",
        "port",
        "path",
        "wildcard",
        "inner-whitespace",
        "leading-hyphen",
        "no-entries",
    ],
)
@pytest.mark.usefixtures("clean_sources")
def test_an_unusable_host_list_is_refused_at_construction(raw: str) -> None:
    """An entry that could never equal a URL's host is refused, not ignored.

    Dropping a malformed entry silently would leave a pin that looks wider
    than it is; an empty list would look like a pin and admit nothing.
    Mutations: skipping the per-entry host-name check turned ``scheme`` into
    DID NOT RAISE, and skipping the non-empty check did the same to
    ``no-entries``. Restoring each passed.
    """
    _configure(EnvVar.QDRANT_DOWNLOAD_HOSTS, raw)

    with pytest.raises(ValueError) as excinfo:
        get_config()

    message = str(excinfo.value)
    assert EnvVar.QDRANT_DOWNLOAD_HOSTS.value in message
    assert "qdrant_download_hosts" in message
    assert _HOSTS_SHAPE in message


def test_comma_separated_strips_folds_case_and_drops_empty_entries() -> None:
    """One tokeniser for every list-valued setting, order preserved."""
    assert comma_separated(" A.example ,b.example,, C ,") == (
        "a.example",
        "b.example",
        "c",
    )
    assert comma_separated("") == ()
    assert comma_separated(" , ,") == ()


def test_the_shipped_host_default_parses_to_the_official_set() -> None:
    """The raw default and the resolved set are one list, read two ways.

    A tool that must ignore operator overrides reads the raw default; it has
    to get the same hosts the settings object resolves to.
    """
    raw = rag_default("qdrant_download_hosts")

    assert isinstance(raw, str)
    assert frozenset(comma_separated(raw)) == _OFFICIAL_HOSTS
    assert rag_default("qdrant_release_base_url") == _OFFICIAL_BASE_URL


@pytest.mark.parametrize("var", _SOURCE_VARS, ids=lambda v: v.value)
def test_no_source_setting_may_be_supplied_by_a_workspace_file(var: EnvVar) -> None:
    """Neither a workspace ``.env`` nor the project store may name a source.

    Two declarations open a file to a variable: eligibility for the workspace
    ``.env``, and being persistable into the project store. A source setting
    carries neither, and is not a credential, which is the only kind of entry
    the framework lets a workspace ``.env`` supply at all.

    Mutations. Adding the base-URL variable to the workspace-dotenv set alone
    never reaches this test: the framework refuses to build a non-secret entry
    marked eligible, so the registry fails to import. Adding it to the
    credential set as well builds, and then failed the first assertion here.
    Declaring it persistable in the registry failed the second. Restoring
    each passed.
    """
    declared = entry(var)

    assert not declared.workspace_dotenv
    assert not declared.persistable
    assert not declared.secret


def test_no_variable_of_this_package_is_persistable() -> None:
    """The project store supplies none of this package's settings.

    The store lives inside a workspace, so a persistable setting is one a
    project directory can supply. That is wrong for a download source and
    just as wrong for the operator binary path, which names a file to run.
    Mutation: declaring one entry persistable in the registry failed this
    assertion naming it; restoring it passed.
    """
    persistable = sorted(var.name for var in EnvVar if entry(var).persistable)

    assert not persistable


@pytest.mark.usefixtures("clean_sources")
def test_a_dotenv_in_the_working_directory_does_not_move_a_source(
    tmp_path: Path,
) -> None:
    """A directory whose ``.env`` assigns all three changes nothing.

    The resolver is run from inside a directory carrying a ``.env`` that
    assigns every source variable, with none set in the process environment.
    The resolved values are still the shipped ones: no reader of that file
    exists for a setting, and this is the end-to-end statement of it.
    """
    (tmp_path / ".env").write_text(
        f"{EnvVar.QDRANT_AUTO_PROVISION.value}=0\n"
        f"{EnvVar.QDRANT_RELEASE_BASE_URL.value}=https://attacker.example/qdrant\n"
        f"{EnvVar.QDRANT_DOWNLOAD_HOSTS.value}=attacker.example\n",
        encoding="utf-8",
    )

    with chdir(tmp_path):
        reset_config()
        cfg = get_config()
        resolved = (
            cfg.qdrant_auto_provision,
            cfg.qdrant_release_base_url,
            cfg.qdrant_download_hosts,
        )

    assert resolved == (True, _OFFICIAL_BASE_URL, _OFFICIAL_HOSTS)

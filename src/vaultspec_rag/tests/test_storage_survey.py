"""Unit tests for storage-namespace survey classification.

Mostly pure logic: no GPU, no Qdrant, no service. Exercises grouping by
prefix and live/orphaned/unknown classification against a synthetic
manifest.

The last class is the exception and reaches a whole maintenance cycle,
because what it has to observe is not a classification but a continuation:
the survey is the first thing the cycle does and every namespace's fate is
behind it, so a survey that fails on one collection is the cheapest way to
destroy a cycle. Proving it does not takes a second namespace to still
arrive at an outcome.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from qdrant_client.http.exceptions import ResponseHandlingException

from ..storage_manifest import ManifestEntry
from ..storage_survey import classify_namespaces
from .test_storage_ops import (
    _NOW,
    _collection_of,
    _CycleClient,
    _orphaned_namespace,
    _outcome_for,
    _run_cycle,
)

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = [pytest.mark.unit]


def _entry(prefix: str, root: str) -> ManifestEntry:
    return ManifestEntry(prefix=prefix, root=root, backend="server")


def test_live_orphaned_unknown(tmp_path: Path) -> None:
    live_root = tmp_path / "live"
    live_root.mkdir()
    gone_root = tmp_path / "gone"  # never created -> orphaned

    manifest = {
        "raaaaaaaaaaaa_": _entry("raaaaaaaaaaaa_", str(live_root)),
        "rbbbbbbbbbbbb_": _entry("rbbbbbbbbbbbb_", str(gone_root)),
    }
    names = [
        "raaaaaaaaaaaa_vault_docs",
        "raaaaaaaaaaaa_codebase_docs",
        "rbbbbbbbbbbbb_vault_docs",
        "rcccccccccccc_codebase_docs",  # not in manifest -> unknown
    ]
    surveys = classify_namespaces(names, manifest)
    by_prefix = {s.prefix: s for s in surveys}

    assert by_prefix["raaaaaaaaaaaa_"].status == "live"
    assert by_prefix["raaaaaaaaaaaa_"].root == str(live_root)
    assert by_prefix["raaaaaaaaaaaa_"].collections == [
        "raaaaaaaaaaaa_codebase_docs",
        "raaaaaaaaaaaa_vault_docs",
    ]
    assert by_prefix["rbbbbbbbbbbbb_"].status == "orphaned"
    assert by_prefix["rcccccccccccc_"].status == "unknown"
    assert by_prefix["rcccccccccccc_"].root is None


def test_actionable_states_sort_first(tmp_path: Path) -> None:
    live_root = tmp_path / "live"
    live_root.mkdir()
    manifest = {"raaaaaaaaaaaa_": _entry("raaaaaaaaaaaa_", str(live_root))}
    names = [
        "raaaaaaaaaaaa_vault_docs",  # live
        "rdddddddddddd_vault_docs",  # unknown
    ]
    surveys = classify_namespaces(names, manifest)
    # Unknown (actionable) must come before live.
    assert surveys[0].status == "unknown"
    assert surveys[-1].status == "live"


def test_counts_and_footprint_aggregate(tmp_path: Path) -> None:
    root = tmp_path / "r"
    root.mkdir()
    manifest = {"raaaaaaaaaaaa_": _entry("raaaaaaaaaaaa_", str(root))}
    names = ["raaaaaaaaaaaa_vault_docs", "raaaaaaaaaaaa_codebase_docs"]
    counts = {"raaaaaaaaaaaa_vault_docs": 10, "raaaaaaaaaaaa_codebase_docs": 32}
    sizes = {"raaaaaaaaaaaa_vault_docs": 1000, "raaaaaaaaaaaa_codebase_docs": 2048}
    survey = classify_namespaces(
        names, manifest, point_counts=counts, footprints=sizes
    )[0]
    assert survey.points == 42
    assert survey.footprint_bytes == 3048


def test_non_namespaced_name_is_unknown() -> None:
    # A bare (non-prefixed) name surfaces as its own unknown entry, never dropped.
    surveys = classify_namespaces(["vault_docs"], {})
    assert len(surveys) == 1
    assert surveys[0].status == "unknown"
    assert surveys[0].prefix == "vault_docs"


def test_empty_input() -> None:
    assert classify_namespaces([], {}) == []


# -- extended-length alias normalization and temp-root flagging --


def test_extended_length_alias_hashes_to_same_prefix(tmp_path: Path) -> None:
    r"""A ``\\?\``-prefixed spelling of a root must not mint a second namespace."""
    import sys

    from .._store_models import root_collection_prefix

    if sys.platform != "win32":
        pytest.skip("extended-length path prefixes are Windows-only")
    plain = root_collection_prefix(tmp_path)
    aliased = root_collection_prefix("\\\\?\\" + str(tmp_path))
    assert aliased == plain


def test_unc_extended_length_alias_normalizes() -> None:
    r"""The ``\\?\UNC\`` form reduces to the plain UNC spelling before hashing.

    The host is in the reserved ``.invalid`` domain, so hashing a UNC root
    cannot depend on whether some host really answers to that name: a
    resolvable host makes the underlying ``resolve()`` reach the network,
    where an unreachable share raises rather than falling back lexically.
    """
    import sys

    from .._store_models import root_collection_prefix

    if sys.platform != "win32":
        pytest.skip("extended-length path prefixes are Windows-only")
    plain = root_collection_prefix(r"\\fileserver.invalid\share\proj")
    aliased = root_collection_prefix(r"\\?\UNC\fileserver.invalid\share\proj")
    assert aliased == plain


def test_unreachable_root_still_hashes() -> None:
    r"""A root that cannot be reached names a namespace lexically, never raises.

    An offline share or unplugged drive is not an absent path: Windows
    reports it as a network or device error, which ``Path.resolve()``
    propagates instead of degrading to its lexical result.
    """
    import pathlib
    import sys

    from .._store_models import ROOT_COLLECTION_PREFIX_RE, root_collection_prefix

    if sys.platform != "win32":
        pytest.skip("UNC roots and device errors are Windows-only")
    # A raw device path stands in for the offline share: it is the input that
    # makes resolve() raise on any Windows host, where an unreachable share
    # only raises while the network is in the state that provokes it. The
    # precondition is asserted so the fallback branch cannot go unexercised.
    device = r"\\.\PhysicalDrive0\proj"
    with pytest.raises(OSError):
        pathlib.Path(device).resolve()
    assert ROOT_COLLECTION_PREFIX_RE.match(root_collection_prefix(device))
    assert ROOT_COLLECTION_PREFIX_RE.match(
        root_collection_prefix(r"\\fileserver.invalid\share\proj")
    )


def test_temp_rooted_flags_tempdir_descendants(tmp_path: Path) -> None:
    import pathlib
    import tempfile

    from ..storage_survey import is_temp_rooted

    inside = pathlib.Path(tempfile.gettempdir()) / "vaultspec-livetest-xyz"
    assert is_temp_rooted(str(inside)) is True
    assert is_temp_rooted(str(inside / "nested" / "deeper")) is True
    # tmp_path is pytest's basetemp, itself under the OS temp dir.
    assert is_temp_rooted(str(tmp_path)) is True


def test_temp_rooted_false_for_project_roots_and_none() -> None:
    from ..storage_survey import is_temp_rooted

    assert is_temp_rooted(None) is False
    assert is_temp_rooted(r"C:\projects\real-project") is False


class _SurveyTimeoutClient(_CycleClient):
    """A cycle client whose point count times out for one named collection.

    It times out on every call for that collection, the survey's and any
    later gate's alike. A stand-in that answered the second time would let a
    broken survey guard be rescued downstream, and the survey is what is
    under test here.
    """

    def __init__(
        self,
        counts: dict[str, int],
        *,
        snapshots_dir: Path,
        times_out: str,
    ) -> None:
        super().__init__(counts, snapshots_dir=snapshots_dir)
        self._times_out = times_out

    def count(self, *, collection_name: str) -> object:
        if collection_name == self._times_out:
            # The real client wraps every transport failure in this type,
            # which is a plain Exception and a subclass of neither builtin -
            # the whole reason a guard naming only the builtins let a read
            # timeout past it.
            raise ResponseHandlingException(TimeoutError("timed out"))
        return super().count(collection_name=collection_name)


@pytest.mark.usefixtures("isolated_status_dir")
class TestSurveyTimeoutDoesNotUnwindTheCycle:
    """One uncountable collection costs its own namespace a cycle, nothing more.

    The grace clocks these carry live in the machine-global manifest, so the
    class relocates it. The classification tests above need no such thing.
    """

    def test_a_timed_out_count_leaves_the_cycle_running_and_the_namespace_held(
        self, tmp_path: Path
    ) -> None:
        """The survey skips past it, and the next namespace still gets a verdict.

        Two mutations, each run alone against this test and each observed to
        fail on the assertion named beside it.

        Narrowing the survey's count guard back to the two builtin types
        fails ``pytest.fail("the survey's transport timeout unwound ...")``:
        the client's wrapper is a subclass of neither, so it walks out of
        ``gather_survey`` and takes the cycle with it before any namespace
        has a decision.

        Swallowing the timeout broadly - keeping the widened guard but
        recording the uncountable collection as zero points, which is what
        this path did before - fails
        ``assert held.action == "pending"``. That mutation passes every test
        that only asserts nothing escaped and nothing was deleted: the cycle
        does continue, and the pre-drop re-count does catch the namespace on
        its way to the drop. What it loses is the tier. Surveyed as zero, the
        namespace is admitted to the EMPTY tier, which is the one that drops
        without writing an archive first, and it survives only because a
        later gate happens to hold it. The assertions on the action, the
        reason and the tier are what separate a namespace that was never
        eligible from one that was eligible on a number nobody took.
        """
        first, second = sorted(
            (
                _orphaned_namespace(tmp_path, now=_NOW, name="sandbox-one"),
                _orphaned_namespace(tmp_path, now=_NOW, name="sandbox-two"),
            )
        )
        # The timeout lands on whichever collection the survey reaches FIRST,
        # so everything the cycle does afterwards is downstream of surviving
        # it. Collections share one suffix, so sorting the prefixes sorts the
        # names the survey enumerates.
        held_collection = _collection_of(first)
        reached_collection = _collection_of(second)
        client = _SurveyTimeoutClient(
            {held_collection: 10, reached_collection: 10},
            snapshots_dir=tmp_path / "snapshots",
            times_out=held_collection,
        )

        try:
            result = _run_cycle(client, tmp_path)
        except ResponseHandlingException as escaped:
            pytest.fail(
                "the survey's transport timeout unwound the whole maintenance "
                "cycle instead of leaving one collection uncounted: "
                f"{escaped!r}"
            )

        # Continuation, stated as an outcome rather than as an absence of a
        # raise: the namespace behind the slow one was surveyed, decided, and
        # acted on.
        reached = _outcome_for(result, second)
        assert reached.action == "archived_removed"
        assert client.deleted == [reached_collection]

        held = _outcome_for(result, first)
        assert held.action == "pending"
        assert held.reason == "survey_points_unverifiable"
        # The protective tier. An uncountable namespace read as empty is
        # routed to the tier that destroys without archiving, so this is the
        # assertion that a partial total was not quietly believed.
        assert held.tier == "data"
        assert held_collection not in client.deleted

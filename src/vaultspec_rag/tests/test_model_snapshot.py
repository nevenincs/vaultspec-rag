"""Tests for the check a model snapshot must pass before it is used.

A model revision is a name the hub resolves, and the hub may be a mirror, so
what arrives under a pinned commit is only known by hashing it. These tests
hold the check to that: a default model is accepted only when its snapshot
matches the committed digests file for file, the file at fault is named, and
a snapshot that merely has the right file names is not mistaken for one with
the right bytes.

Real directories in the layout the hub client writes, real files, the real
client resolving them, and no network. The committed digests describe
multi-gigabyte weights, so the passing case for a default model cannot be
built here; it is covered by checking a directory against a table this file
supplies, which is the same code with a different table.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from typing import TYPE_CHECKING, NamedTuple

import pytest

from .._model_cache import (
    ModelSnapshotError,
    SnapshotFault,
    cached_snapshot_is_complete,
    checked_directory,
    loadable_snapshot,
    verified_snapshot,
    verify_snapshot,
)
from .._model_pins import (
    DENSE_MODEL_ID,
    DENSE_MODEL_REVISION,
    committed_manifest,
)
from ..config._types import EnvVar
from ._model_cache_seed import ORDINARY_FILES, point_hub_cache, seed_snapshot

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

pytestmark = [pytest.mark.unit]

_OPERATOR_REPO = "example-org/operator-model"
_COMMIT = "0123456789abcdef0123456789abcdef01234567"


def _table(files: Mapping[str, bytes]) -> dict[str, str]:
    return {name: hashlib.sha256(body).hexdigest() for name, body in files.items()}


def _fault(excinfo: pytest.ExceptionInfo[ModelSnapshotError]) -> tuple[str, str | None]:
    return excinfo.value.fault.value, excinfo.value.file


class TestADirectoryCheckedAgainstATable:
    """The check itself, run against a table the test supplies."""

    def test_a_matching_directory_is_yielded_with_its_files_readable(
        self, tmp_path: Path
    ) -> None:
        snapshot = seed_snapshot(tmp_path, _OPERATOR_REPO, _COMMIT, ORDINARY_FILES)

        with checked_directory(
            _OPERATOR_REPO, snapshot, _table(ORDINARY_FILES)
        ) as held:
            assert held.directory == snapshot
            assert held.read("model.safetensors") == b"fixture"

    def test_a_file_with_different_content_is_refused_by_name(
        self, tmp_path: Path
    ) -> None:
        """Right name, right place, wrong bytes: refused, and the file is named.

        This is the mirror case: a hub that serves something else under the
        pinned commit. Mutation: with the digest comparison removed this
        failed DID NOT RAISE; restored, it passed.
        """
        snapshot = seed_snapshot(tmp_path, _OPERATOR_REPO, _COMMIT, ORDINARY_FILES)
        (snapshot / "tokenizer.json").write_bytes(b'{"swapped": true}')

        with (
            pytest.raises(ModelSnapshotError) as excinfo,
            checked_directory(_OPERATOR_REPO, snapshot, _table(ORDINARY_FILES)),
        ):
            pytest.fail("a mismatched snapshot was yielded")

        assert _fault(excinfo) == ("mismatch", "tokenizer.json")
        assert excinfo.value.fetchable

    def test_a_missing_file_is_refused_by_name(self, tmp_path: Path) -> None:
        """Mutation: with the missing-file check removed this failed, the
        absent file surfacing as an unopened handle instead of a named fault;
        restored, it passed.
        """
        snapshot = seed_snapshot(tmp_path, _OPERATOR_REPO, _COMMIT, ORDINARY_FILES)
        (snapshot / "tokenizer.json").unlink()

        with (
            pytest.raises(ModelSnapshotError) as excinfo,
            checked_directory(_OPERATOR_REPO, snapshot, _table(ORDINARY_FILES)),
        ):
            pytest.fail("an incomplete snapshot was yielded")

        assert _fault(excinfo) == ("incomplete", "tokenizer.json")
        assert excinfo.value.fetchable

    def test_an_extra_file_is_refused_by_name(self, tmp_path: Path) -> None:
        """A file the release does not contain is refused like a changed one.

        The loaders pick files up by name, so an adapter configuration
        dropped beside the reviewed files would be read. No download cures
        it, so it is not reported as fetchable. Mutation: with the extra-file
        check removed this failed DID NOT RAISE; restored, it passed.
        """
        snapshot = seed_snapshot(tmp_path, _OPERATOR_REPO, _COMMIT, ORDINARY_FILES)
        (snapshot / "adapter_config.json").write_bytes(b"{}")

        with (
            pytest.raises(ModelSnapshotError) as excinfo,
            checked_directory(_OPERATOR_REPO, snapshot, _table(ORDINARY_FILES)),
        ):
            pytest.fail("a snapshot with an extra file was yielded")

        assert _fault(excinfo) == ("extra_file", "adapter_config.json")
        assert not excinfo.value.fetchable
        assert str(snapshot / "adapter_config.json") in str(excinfo.value)

    def test_a_file_added_during_the_load_discards_the_result(
        self, tmp_path: Path
    ) -> None:
        """No handle stops a file being added, so the directory is listed twice.

        The second listing happens as the block ends. A caller that returns
        its model only after the block therefore never returns one built
        beside a file that was not there when the check ran. Mutation: with
        the second listing removed this failed DID NOT RAISE; restored, it
        passed.
        """
        snapshot = seed_snapshot(tmp_path, _OPERATOR_REPO, _COMMIT, ORDINARY_FILES)

        with (
            pytest.raises(ModelSnapshotError) as excinfo,
            checked_directory(_OPERATOR_REPO, snapshot, _table(ORDINARY_FILES)),
        ):
            (snapshot / "adapter_config.json").write_bytes(b"{}")

        assert _fault(excinfo) == ("extra_file", "adapter_config.json")

    def test_a_snapshot_of_links_is_checked_through_to_the_blobs(
        self, tmp_path: Path
    ) -> None:
        """The client's usual layout: every entry a link to a content blob."""
        try:
            snapshot = seed_snapshot(
                tmp_path, _OPERATOR_REPO, _COMMIT, ORDINARY_FILES, links=True
            )
        except OSError:
            pytest.skip("this account cannot create symbolic links")

        with checked_directory(
            _OPERATOR_REPO, snapshot, _table(ORDINARY_FILES)
        ) as held:
            assert held.read("config.json") == b"{}"

        blob = (snapshot / "tokenizer.json").resolve()
        blob.write_bytes(b'{"swapped": true}')
        with (
            pytest.raises(ModelSnapshotError) as excinfo,
            checked_directory(_OPERATOR_REPO, snapshot, _table(ORDINARY_FILES)),
        ):
            pytest.fail("a snapshot with a rewritten blob was yielded")
        assert _fault(excinfo) == ("mismatch", "tokenizer.json")

    @pytest.mark.skipif(
        sys.platform != "win32",
        reason="only Windows can refuse writers to a file another process reads",
    )
    @pytest.mark.parametrize("links", [False, True], ids=["files", "links"])
    def test_a_held_file_cannot_be_rewritten_removed_or_renamed(
        self, tmp_path: Path, links: bool
    ) -> None:
        """While the block lasts, what was hashed cannot be changed.

        Each file is open without write or delete sharing, so the loader
        reads the bytes that were checked. Mutation: with the files opened
        sharing writes, the rewrite below succeeded and this failed DID NOT
        RAISE; restored, it passed.
        """
        try:
            snapshot = seed_snapshot(
                tmp_path, _OPERATOR_REPO, _COMMIT, ORDINARY_FILES, links=links
            )
        except OSError:
            pytest.skip("this account cannot create symbolic links")
        entry = snapshot / "model.safetensors"
        content = entry.resolve()

        with checked_directory(_OPERATOR_REPO, snapshot, _table(ORDINARY_FILES)):
            with pytest.raises(PermissionError):
                content.open("r+b").close()
            with pytest.raises(PermissionError):
                content.unlink()
            with pytest.raises(PermissionError):
                entry.rename(entry.with_name("moved.safetensors"))
            with pytest.raises(PermissionError):
                snapshot.rename(snapshot.with_name("moved"))

        assert entry.read_bytes() == b"fixture"


class TestADefaultModel:
    """A default model is held to the digests committed for its pinned commit."""

    def test_the_right_names_with_other_bytes_do_not_verify(
        self, tmp_path: Path
    ) -> None:
        """Every file of the pinned release present, none of them the release's.

        The structural probe says complete, because it reads nothing. The
        check refuses, and names a file. That gap is why no surface built on
        the probe may call a model verified. Mutation: with the committed
        table ignored for default models, ``verify_snapshot`` returned and
        this failed DID NOT RAISE; restored, it passed.
        """
        manifest = committed_manifest(DENSE_MODEL_ID, DENSE_MODEL_REVISION)
        assert manifest is not None
        seed_snapshot(
            tmp_path,
            DENSE_MODEL_ID,
            DENSE_MODEL_REVISION,
            dict.fromkeys(manifest, b"not the release"),
        )

        assert cached_snapshot_is_complete(
            DENSE_MODEL_ID, revision=DENSE_MODEL_REVISION, cache_dir=tmp_path
        )
        with pytest.raises(ModelSnapshotError) as excinfo:
            verify_snapshot(
                DENSE_MODEL_ID, revision=DENSE_MODEL_REVISION, cache_dir=tmp_path
            )

        assert excinfo.value.fault is SnapshotFault.MISMATCH
        assert excinfo.value.file in manifest

    def test_an_ordinary_looking_snapshot_is_incomplete_for_it(
        self, tmp_path: Path
    ) -> None:
        """What would pass for any other model is short of the pinned release."""
        seed_snapshot(tmp_path, DENSE_MODEL_ID, DENSE_MODEL_REVISION, ORDINARY_FILES)

        assert not cached_snapshot_is_complete(
            DENSE_MODEL_ID, revision=DENSE_MODEL_REVISION, cache_dir=tmp_path
        )
        with pytest.raises(ModelSnapshotError) as excinfo:
            verify_snapshot(
                DENSE_MODEL_ID, revision=DENSE_MODEL_REVISION, cache_dir=tmp_path
            )
        assert excinfo.value.fault is SnapshotFault.INCOMPLETE

    def test_at_another_commit_it_has_no_table_and_is_judged_by_structure(
        self, tmp_path: Path
    ) -> None:
        """A default repository moved to another commit is not held to a table
        that describes different files.
        """
        seed_snapshot(tmp_path, DENSE_MODEL_ID, _COMMIT, ORDINARY_FILES)

        verify_snapshot(DENSE_MODEL_ID, revision=_COMMIT, cache_dir=tmp_path)


class TestAModelTheOperatorNamed:
    """No table exists for it: structure and weight format are all that is judged."""

    def test_a_complete_snapshot_passes(self, tmp_path: Path) -> None:
        seed_snapshot(tmp_path, _OPERATOR_REPO, _COMMIT, ORDINARY_FILES)

        assert cached_snapshot_is_complete(
            _OPERATOR_REPO, revision=_COMMIT, cache_dir=tmp_path
        )
        verify_snapshot(_OPERATOR_REPO, revision=_COMMIT, cache_dir=tmp_path)

    def test_with_no_commit_named_the_default_branch_snapshot_is_judged(
        self, tmp_path: Path
    ) -> None:
        """Unpinned is still usable: it is probed and loaded, never refused."""
        seed_snapshot(tmp_path, _OPERATOR_REPO, _COMMIT, ORDINARY_FILES)

        assert cached_snapshot_is_complete(
            _OPERATOR_REPO, revision=None, cache_dir=tmp_path
        )
        with verified_snapshot(
            _OPERATOR_REPO, revision=None, cache_dir=tmp_path
        ) as held:
            assert held.directory.name == _COMMIT

    def test_an_absent_snapshot_is_reported_as_absent(self, tmp_path: Path) -> None:
        assert not cached_snapshot_is_complete(
            _OPERATOR_REPO, revision=_COMMIT, cache_dir=tmp_path
        )
        with pytest.raises(ModelSnapshotError) as excinfo:
            verify_snapshot(_OPERATOR_REPO, revision=_COMMIT, cache_dir=tmp_path)

        assert excinfo.value.fault is SnapshotFault.ABSENT
        assert excinfo.value.fetchable

    def test_pickle_only_weights_are_refused_for_that_reason(
        self, tmp_path: Path
    ) -> None:
        """A pickle weight file is executable content, so it is never loaded.

        The refusal says so, instead of calling the model incomplete: no
        download will produce a safetensors file the repository does not
        ship. Mutation: with a pickle file counted as weights, the probe
        answered complete and this failed on the first assertion; restored,
        it passed.
        """
        files = {
            "config.json": b"{}",
            "tokenizer.json": b"{}",
            "pytorch_model.bin": b"pickle",
        }
        seed_snapshot(tmp_path, _OPERATOR_REPO, _COMMIT, files)

        assert not cached_snapshot_is_complete(
            _OPERATOR_REPO, revision=_COMMIT, cache_dir=tmp_path
        )
        with pytest.raises(ModelSnapshotError) as excinfo:
            verify_snapshot(_OPERATOR_REPO, revision=_COMMIT, cache_dir=tmp_path)

        assert _fault(excinfo) == ("pickle_only", "pytorch_model.bin")
        assert not excinfo.value.fetchable
        assert "safetensors" in str(excinfo.value)

    @pytest.mark.parametrize(
        ("missing", "fault_file"),
        [
            ("config.json", "config.json"),
            ("tokenizer.json", None),
            ("model.safetensors", None),
        ],
    )
    def test_a_snapshot_short_of_a_needed_file_is_incomplete(
        self, tmp_path: Path, missing: str, fault_file: str | None
    ) -> None:
        files = {name: body for name, body in ORDINARY_FILES.items() if name != missing}
        seed_snapshot(tmp_path, _OPERATOR_REPO, _COMMIT, files)

        assert not cached_snapshot_is_complete(
            _OPERATOR_REPO, revision=_COMMIT, cache_dir=tmp_path
        )
        with pytest.raises(ModelSnapshotError) as excinfo:
            verify_snapshot(_OPERATOR_REPO, revision=_COMMIT, cache_dir=tmp_path)
        assert _fault(excinfo) == ("incomplete", fault_file)

    def test_a_sharded_model_needs_every_shard_its_index_names(
        self, tmp_path: Path
    ) -> None:
        index = json.dumps(
            {
                "weight_map": {
                    "a": "model-00001-of-00002.safetensors",
                    "b": "model-00002-of-00002.safetensors",
                }
            }
        ).encode()
        files = {
            "config.json": b"{}",
            "tokenizer.json": b"{}",
            "model.safetensors.index.json": index,
            "model-00001-of-00002.safetensors": b"one",
        }
        snapshot = seed_snapshot(tmp_path, _OPERATOR_REPO, _COMMIT, files)

        with pytest.raises(ModelSnapshotError) as excinfo:
            verify_snapshot(_OPERATOR_REPO, revision=_COMMIT, cache_dir=tmp_path)
        assert _fault(excinfo) == (
            "incomplete",
            "model-00002-of-00002.safetensors",
        )

        (snapshot / "model-00002-of-00002.safetensors").write_bytes(b"two")
        verify_snapshot(_OPERATOR_REPO, revision=_COMMIT, cache_dir=tmp_path)


_WARMUP = "vaultspec-rag server warmup"
_DOCTOR = "vaultspec-rag server doctor"


def _pinned_names_with_other_bytes() -> dict[str, bytes]:
    manifest = committed_manifest(DENSE_MODEL_ID, DENSE_MODEL_REVISION)
    assert manifest is not None
    return dict.fromkeys(manifest, b"not the pinned bytes")


class _Refused(NamedTuple):
    """One snapshot a load must refuse, and what its refusal has to say."""

    repo: str
    revision: str
    files: Mapping[str, bytes] | None
    fault: SnapshotFault
    named: tuple[str, ...]
    not_named: tuple[str, ...]


@pytest.fixture
def hub_cache(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Make *tmp_path* the cache a load reads, as the hub client resolves it."""
    return point_hub_cache(monkeypatch, tmp_path)


class TestASnapshotAModelIsLoadedFrom:
    """A load reads the cache and nothing else, and a refusal says what to run.

    Every model reaches its loader through one call, so what is held here
    holds for the dense model, the sparse model and the reranker alike,
    whenever each first loads.
    """

    def test_a_snapshot_that_passes_is_handed_to_the_loader(
        self, hub_cache: Path
    ) -> None:
        seed_snapshot(hub_cache, _OPERATOR_REPO, _COMMIT, ORDINARY_FILES)

        with loadable_snapshot(_OPERATOR_REPO, revision=_COMMIT) as held:
            assert held.directory.name == _COMMIT
            assert held.read("model.safetensors") == b"fixture"

    @pytest.mark.parametrize(
        "case",
        [
            _Refused(
                _OPERATOR_REPO,
                _COMMIT,
                None,
                SnapshotFault.ABSENT,
                (f"run '{_WARMUP}' to fetch it",),
                (_DOCTOR,),
            ),
            _Refused(
                DENSE_MODEL_ID,
                DENSE_MODEL_REVISION,
                ORDINARY_FILES,
                SnapshotFault.INCOMPLETE,
                (f"run '{_WARMUP}' to fetch what is missing",),
                (_DOCTOR,),
            ),
            _Refused(
                DENSE_MODEL_ID,
                DENSE_MODEL_REVISION,
                _pinned_names_with_other_bytes(),
                SnapshotFault.MISMATCH,
                (f"Run '{_WARMUP}' to fetch the pinned files again", f"'{_DOCTOR}'"),
                (),
            ),
            _Refused(
                DENSE_MODEL_ID,
                DENSE_MODEL_REVISION,
                {**_pinned_names_with_other_bytes(), "added.bin": b"x"},
                SnapshotFault.EXTRA_FILE,
                (f"run '{_DOCTOR}'",),
                (_WARMUP,),
            ),
            _Refused(
                _OPERATOR_REPO,
                _COMMIT,
                {
                    "config.json": b"{}",
                    "tokenizer.json": b"{}",
                    "pytorch_model.bin": b"pickle",
                },
                SnapshotFault.PICKLE_ONLY,
                ("Name a model that ships safetensors weights",),
                (_WARMUP, _DOCTOR),
            ),
        ],
        ids=["absent", "incomplete", "mismatch", "extra-file", "pickle-only"],
    )
    def test_a_refusal_is_one_message_with_the_command_that_cures_it(
        self, hub_cache: Path, case: _Refused
    ) -> None:
        """The fault, then what to run, in the one message the operator sees.

        The remedy differs by fault because the cure does: fetching cures a
        missing file and a wrong one, and cures neither an extra file nor a
        model that ships no safetensors weights, so those two never send the
        operator to a download that would change nothing.

        Mutations: with the load yielding the check's own error unchanged,
        all five cases failed on the remedy missing from the message; with
        the remedies for a wrong file and an extra file exchanged, the
        ``mismatch`` case failed on the fetch command missing and the
        ``extra-file`` case failed on the check command missing. Restored
        after each, all passed.
        """
        if case.files is not None:
            seed_snapshot(hub_cache, case.repo, case.revision, case.files)

        with (
            pytest.raises(ModelSnapshotError) as excinfo,
            loadable_snapshot(case.repo, revision=case.revision),
        ):
            pytest.fail("a snapshot that does not pass was handed to a loader")

        refusal = excinfo.value
        message = str(refusal)
        assert refusal.fault is case.fault
        for text in case.named:
            assert text in message
        for text in case.not_named:
            assert text not in message
        cause = refusal.__cause__
        assert isinstance(cause, ModelSnapshotError)
        assert refusal.file == cause.file
        assert message.startswith(f"model {case.repo}: {cause.detail}. ")
        assert message.endswith(".")

    def test_a_loader_that_fails_is_not_mistaken_for_a_bad_snapshot(
        self, hub_cache: Path
    ) -> None:
        """An error from the loader itself leaves the block as it was raised."""
        seed_snapshot(hub_cache, _OPERATOR_REPO, _COMMIT, ORDINARY_FILES)

        with (
            pytest.raises(ZeroDivisionError),
            loadable_snapshot(_OPERATOR_REPO, revision=_COMMIT),
        ):
            _ = 1 // 0

    @pytest.mark.skipif(
        sys.platform != "win32",
        reason="only Windows refuses a read that excludes a file's writer",
    )
    def test_a_file_another_process_is_writing_stops_the_load(
        self, hub_cache: Path
    ) -> None:
        snapshot = seed_snapshot(hub_cache, _OPERATOR_REPO, _COMMIT, ORDINARY_FILES)

        with (
            (snapshot / "model.safetensors").open("r+b"),
            pytest.raises(ModelSnapshotError) as excinfo,
            loadable_snapshot(_OPERATOR_REPO, revision=_COMMIT),
        ):
            pytest.fail("a snapshot with a file open for writing was handed on")

        assert _fault(excinfo) == ("in_use", "model.safetensors")
        assert f"run '{_DOCTOR}'" in str(excinfo.value)
        assert _WARMUP not in str(excinfo.value)


_LOAD_PROBE = """
import sys

from vaultspec_rag._model_cache import ModelSnapshotError, loadable_snapshot
from vaultspec_rag._model_pins import DENSE_MODEL_ID, DENSE_MODEL_REVISION

try:
    with loadable_snapshot(DENSE_MODEL_ID, revision=DENSE_MODEL_REVISION):
        print("YIELDED")
except ModelSnapshotError as refusal:
    print("FAULT=" + refusal.fault.value)
    print("MESSAGE=" + str(refusal))
loaded = sorted(
    name
    for name in sys.modules
    if name.startswith("vaultspec_rag.commands") or name == "torch"
)
print("LOADED=" + ",".join(loaded))
"""


def test_a_load_that_finds_no_model_downloads_nothing(tmp_path: Path) -> None:
    """With an empty cache a load stops; it does not go and fetch.

    Run in a fresh interpreter against an empty cache, with the hub endpoint
    pointed at a port nothing listens on. The refusal is the absent-model one
    and names the fetch command. No command module is imported, the one that
    downloads among them, so nothing was present that could have fetched; nor
    is torch, which this check must never need.

    Mutation: with the load importing the downloader before it looks at the
    cache, this failed on the modules assertion naming
    ``vaultspec_rag.commands._model_download``; restored, it passed.
    """
    env = dict(os.environ)
    env[EnvVar.HF_HOME.value] = str(tmp_path / "hf-home")
    env.pop("HF_HUB_CACHE", None)
    env["HF_ENDPOINT"] = "https://127.0.0.1:9"
    proc = subprocess.run(
        [sys.executable, "-c", _LOAD_PROBE],
        capture_output=True,
        text=True,
        check=False,
        env=env,
        timeout=180,
    )

    assert proc.returncode == 0, proc.stderr
    lines = proc.stdout.splitlines()
    assert "FAULT=absent" in lines, proc.stdout
    assert "LOADED=" in lines, proc.stdout
    message = next(line for line in lines if line.startswith("MESSAGE="))
    assert "Nothing is downloaded while a model loads" in message
    assert f"run '{_WARMUP}' to fetch it" in message

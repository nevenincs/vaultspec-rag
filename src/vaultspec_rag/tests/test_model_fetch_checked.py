"""What a hub serves is checked before a fetch reports it as downloaded.

The whole fetch runs in a fresh interpreter against a loopback stand-in hub,
so the request the hub receives and the outcome the fetch prints are both the
shipped ones.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

import pytest

from .._model_pins import DENSE_MODEL_ID, DENSE_MODEL_REVISION, committed_manifest
from ..commands._model_fetch import MODELS_UNVERIFIED
from ..config._types import EnvVar
from ._loopback_model_hub import loopback_model_hub
from ._model_cache_seed import seed_snapshot
from ._model_fetch_child import DENSE_REPO, RERANKER_REPO, fetch_from

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = [pytest.mark.unit, pytest.mark.usefixtures("inference_host")]


class TestWhatTheHubServesIsChecked:
    """A fetch ends with the snapshot check, and only a passing one is a success.

    A model revision is a name the hub resolves, and the hub may be a mirror,
    so reaching the hub and receiving files proves nothing about them. These
    run the whole fetch in a fresh interpreter against a hub that answers for
    a pinned default model at its pinned commit, the way a mirror would.

    The digests committed for a default model describe gigabytes of weights,
    so this hub cannot serve the release itself. Every case here is therefore
    one where the hub serves something else. The success of a repair - a
    cached file that fails its check, fetched again, now passing - cannot be
    staged without the real weights and is not tested here; its first half,
    that the files are fetched again, is.
    """

    @staticmethod
    def _other_bytes(word: bytes) -> dict[str, bytes]:
        manifest = committed_manifest(DENSE_MODEL_ID, DENSE_MODEL_REVISION)
        assert manifest is not None
        return dict.fromkeys(manifest, word)

    def test_other_bytes_under_the_pinned_commit_are_refused(
        self, tmp_path: Path
    ) -> None:
        """The hub is asked for the pinned commit, and what it sends is hashed.

        Every file of the pinned release arrives, by name, with other content.
        The download itself succeeds; the repository is still a failure, under
        its own code, and the next repository is fetched all the same.

        Mutation check: with the check after a download removed, the
        repository is reported ``created`` and the first ``repos`` assertion
        fails with that word. With the pinned commit dropped from the request,
        the hub is asked for ``revision/main`` and the request assertion
        fails. Restoring each passes.
        """
        cache = tmp_path / "hub-cache"
        with loopback_model_hub([DENSE_MODEL_ID, RERANKER_REPO]) as hub:
            hub.commits[DENSE_MODEL_ID] = DENSE_MODEL_REVISION
            hub.files[DENSE_MODEL_ID] = self._other_bytes(b"a mirror's own bytes")
            outcome, progress = fetch_from(
                hub, cache, {EnvVar.EMBEDDING_MODEL.value: DENSE_MODEL_ID}
            )

        pinned = f"/api/models/{DENSE_MODEL_ID}/revision/{DENSE_MODEL_REVISION}"
        assert ("GET", pinned) in hub.requests
        assert ("GET", f"/api/models/{DENSE_MODEL_ID}/revision/main") not in (
            hub.requests
        )
        assert outcome["repos"] == [
            [DENSE_MODEL_ID, "failed", MODELS_UNVERIFIED],
            [RERANKER_REPO, "created", ""],
        ]
        assert outcome["code"] == MODELS_UNVERIFIED
        detail = str(outcome["detail"])
        assert "does not match the SHA256 committed for the pinned release" in detail
        assert hub.endpoint in detail
        assert EnvVar.RAG_HF_ENDPOINT.value in detail
        assert "vaultspec-rag server warmup" in detail
        assert "Verifying Dense (Qwen3) (1/2)" in progress
        assert outcome["processes_left"] == []

    def test_a_cached_file_that_fails_its_check_is_fetched_again(
        self, tmp_path: Path
    ) -> None:
        """An altered cache is not skipped as already present.

        The cache holds every file of the pinned release with other content.
        The hub client would keep files it already has, so the fetch has to
        ask for them again, and the hub log shows that it did. The hub then
        serves other bytes too, so the run still fails; what is proven is
        that the altered files were not trusted for being there.

        Mutation check: with the repair no longer forcing the download, the
        hub is asked for no file at all and the request-count assertion fails
        with zero. Restoring it passes.
        """
        cache = tmp_path / "hub-cache"
        seed_snapshot(
            cache, DENSE_MODEL_ID, DENSE_MODEL_REVISION, self._other_bytes(b"altered")
        )
        with loopback_model_hub([DENSE_MODEL_ID, RERANKER_REPO]) as hub:
            hub.commits[DENSE_MODEL_ID] = DENSE_MODEL_REVISION
            hub.files[DENSE_MODEL_ID] = self._other_bytes(b"a mirror's own bytes")
            outcome, _progress = fetch_from(
                hub, cache, {EnvVar.EMBEDDING_MODEL.value: DENSE_MODEL_ID}
            )

        fetched_again = hub.downloads_of(DENSE_MODEL_ID)
        assert len(fetched_again) == len(hub.files[DENSE_MODEL_ID]), fetched_again
        repos = cast("list[list[str]]", outcome["repos"])
        assert repos[0] == [DENSE_MODEL_ID, "failed", MODELS_UNVERIFIED]
        assert "was downloaded from" in str(outcome["detail"])

    def test_a_model_with_only_pickle_weights_is_refused_and_not_asked_for_twice(
        self, tmp_path: Path
    ) -> None:
        """Pickle weights are never loaded, so such a model is refused outright.

        It is refused after the download that reveals it, and again from the
        cache alone on the next run, without another request: no download
        produces a safetensors file the repository does not ship.

        Mutation check: with a pickle weight file counted as weights, the
        repository is reported ``created`` and the ``repos`` assertion fails.
        Restoring the refusal passes.
        """
        cache = tmp_path / "hub-cache"
        pickled = {
            "config.json": b"{}",
            "tokenizer.json": b"{}",
            "pytorch_model.bin": b"pickle",
        }
        with loopback_model_hub([DENSE_REPO, RERANKER_REPO]) as hub:
            hub.files[DENSE_REPO] = pickled
            first, _progress = fetch_from(hub, cache)
            asked_so_far = len(hub.requests)
            second, _progress = fetch_from(hub, cache)

        for outcome in (first, second):
            repos = cast("list[list[str]]", outcome["repos"])
            assert repos[0] == [DENSE_REPO, "failed", MODELS_UNVERIFIED]
            assert "safetensors" in str(outcome["detail"])
        assert len(hub.requests) == asked_so_far, hub.requests[asked_so_far:]
        assert second["processes_started"] == 0

"""Batch hook spawns for document runs, consumed one document at a time.

Document publication is a serial per-path loop: each file is extracted,
chunked, encoded and checkpointed before the next. A ``batch = true`` rule
still owes one hook process per group, not per file, so the groups are run
lazily: the first document of a group to be published runs the whole group
through one spawn, and every later member takes its outcome from that spawn.
Publication order, per-file checkpoints and per-file failure recording are
unchanged, and an outcome is held only until its document is published.

Extraction is CPU work in a hook subprocess. Nothing here touches the GPU or
runs under its lock.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..job_control import NO_RUN_CONTROL
from ._chunk_producer import partition_batch_work
from ._chunk_worker import preprocess_document_batch

if TYPE_CHECKING:
    import pathlib
    from collections.abc import Callable, Iterable

    from ..job_control import RunControl
    from ._chunk_worker import DocumentBatchResult
    from ._preprocess_config import PreprocessContext, PreprocessRule

__all__ = ["DocumentBatchPreprocessor"]


class DocumentBatchPreprocessor:
    """Hand each batch-rule document the outcome of its group's single spawn."""

    __slots__ = ("_checkpoint", "_group_of", "_groups", "_outcomes", "_prep", "_root")

    def __init__(
        self,
        paths: Iterable[pathlib.Path],
        root_dir: pathlib.Path,
        prep: PreprocessContext | None,
        *,
        extractor_checkpoint: Callable[[], Callable[[], None]],
        run_control: RunControl = NO_RUN_CONTROL,
    ) -> None:
        """Group the documents about to be published by their batch rule.

        Args:
            paths: Admitted document paths this run will publish.
            root_dir: Project root every path is relative to.
            prep: The run's preprocess context; ``None`` disables batching.
            extractor_checkpoint: Builds the cooperative check one hook
                invocation polls, fresh for each spawn as on the per-file path.
            run_control: Run control polled while grouping.
        """
        self._root = root_dir
        self._prep = prep
        self._checkpoint = extractor_checkpoint
        groups, _singles = partition_batch_work(
            list(paths), root_dir, prep, run_control=run_control
        )
        self._groups: dict[int, tuple[PreprocessRule, list[pathlib.Path]]] = dict(
            enumerate(groups)
        )
        self._group_of: dict[pathlib.Path, int] = {
            path: index for index, (_rule, group) in enumerate(groups) for path in group
        }
        self._outcomes: dict[pathlib.Path, DocumentBatchResult] = {}

    def take(self, path: pathlib.Path) -> DocumentBatchResult | None:
        """Return *path*'s batch outcome, running its group on first demand.

        ``None`` means the per-file path decides alone: the path is not under
        a batch rule, its group served it already, or it was a cache hit or a
        pre-launch refusal that never reached the hook.

        Raises:
            PreprocessAbortError: If a group member fails under
                ``on_error == "fail"``.
        """
        index = self._group_of.pop(path, None)
        if index is not None:
            pending = self._groups.pop(index, None)
            if pending is not None:
                assert self._prep is not None
                rule, group = pending
                self._outcomes.update(
                    preprocess_document_batch(
                        group, self._root, rule, self._prep, self._checkpoint()
                    )
                )
        return self._outcomes.pop(path, None)

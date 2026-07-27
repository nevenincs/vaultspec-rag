"""Real watcher-event parity for policy-driven code admission."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import pytest
from watchfiles import (
    Change,
    awatch,  # pyright: ignore[reportUnknownVariableType] - watchfiles stub gap
)

from ...indexer import SUPPORTED_EXTENSIONS, CodebaseIndexer
from ...indexer._content_policy import (
    AdmissionReason,
    ContentKind,
    ContentRoute,
    RootContentPolicy,
    SourceProfileVersion,
)
from ...progress import NullProgressReporter
from ...watcher_policy import is_code_change

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

pytestmark = [pytest.mark.integration]

_EVENT_TIMEOUT_SECONDS = 5.0


async def _wait_for_exact_changes(
    stream: AsyncGenerator[set[tuple[Change, str]]],
    targets: frozenset[Path],
    expected_change: Change,
) -> frozenset[Path]:
    """Collect one real watchfiles change kind for every target path."""
    seen: set[Path] = set()
    loop = asyncio.get_running_loop()
    deadline = loop.time() + _EVENT_TIMEOUT_SECONDS
    while seen != targets:  # pyright: ignore[reportUnnecessaryComparison] - set == frozenset compares by content
        remaining = deadline - loop.time()
        if remaining <= 0:
            raise AssertionError(
                f"watcher did not emit {expected_change!r} for "
                f"{sorted(str(path) for path in targets - seen)!r}"
            )
        changes = await asyncio.wait_for(anext(stream), timeout=remaining)
        seen.update(
            Path(raw_path).resolve()
            for change, raw_path in changes
            if change == expected_change and Path(raw_path).resolve() in targets
        )
    return frozenset(seen)


async def _wait_until_idle(
    stream: AsyncGenerator[set[tuple[Change, str]]],
) -> None:
    """Consume watcher batches until its bounded timeout yields an empty batch."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + _EVENT_TIMEOUT_SECONDS
    while True:
        remaining = deadline - loop.time()
        if remaining <= 0:
            raise AssertionError("watcher event stream did not become idle")
        if not await asyncio.wait_for(anext(stream), timeout=remaining):
            return


@pytest.mark.asyncio
@pytest.mark.timeout(20)
async def test_added_and_modified_events_match_discovery_admission(
    tmp_path: Path,
) -> None:
    """Keep ordinary watcher events aligned with full and scoped discovery."""
    vault_dir = tmp_path / ".vault"
    vault_dir.mkdir()
    for directory in ("src", "config", "incoming"):
        (tmp_path / directory).mkdir()

    paths = {
        "src/logic.py": tmp_path / "src" / "logic.py",
        "config/options.toml": tmp_path / "config" / "options.toml",
        "incoming/report.pdf": tmp_path / "incoming" / "report.pdf",
    }
    targets = frozenset(path.resolve() for path in paths.values())
    indexer = CodebaseIndexer(
        tmp_path,
        cast("Any", None),
        cast("Any", None),
        options=CodebaseIndexer.Options(
            content_policy=RootContentPolicy(
                SourceProfileVersion.CONVENTIONAL_V1,
                (ContentRoute("incoming/report.pdf", ContentKind.DOCUMENT),),
            )
        ),
    )
    policy = indexer.resolve_policy_snapshot()
    stop_event = asyncio.Event()
    stream = awatch(
        tmp_path,
        debounce=25,
        step=10,
        stop_event=stop_event,
        rust_timeout=100,
        yield_on_timeout=True,
    )

    try:
        added_waiter = asyncio.create_task(
            _wait_for_exact_changes(stream, targets, Change.added)
        )
        await asyncio.sleep(0.2)
        paths["src/logic.py"].write_text("value = 1\n", encoding="utf-8")
        paths["config/options.toml"].write_text("enabled = true\n", encoding="utf-8")
        paths["incoming/report.pdf"].write_bytes(b"%PDF-1.4\ninitial\n")
        added = await added_waiter
        await _wait_until_idle(stream)

        modified_waiter = asyncio.create_task(
            _wait_for_exact_changes(stream, targets, Change.modified)
        )
        await asyncio.sleep(0.05)
        paths["src/logic.py"].write_text("value = 2\n", encoding="utf-8")
        paths["config/options.toml"].write_text("enabled = false\n", encoding="utf-8")
        paths["incoming/report.pdf"].write_bytes(b"%PDF-1.4\nmodified\n")
        modified = await modified_waiter
    finally:
        stop_event.set()
        await stream.aclose()

    full_scan = indexer.scan_content(sample_limit=len(paths))
    full_admitted = {path.relative_to(tmp_path).as_posix() for path in full_scan.files}
    scoped, rejected = indexer._scan_changed_paths(
        paths.values(),
        NullProgressReporter(),
        policy,
    )

    assert ".toml" in SUPPORTED_EXTENSIONS
    assert full_admitted == {"src/logic.py"}
    assert set(scoped) == full_admitted
    assert rejected == set(paths) - full_admitted

    for event_paths in (added, modified):
        watcher_admitted = {
            path.relative_to(tmp_path).as_posix()
            for path in event_paths
            if is_code_change(path, tmp_path, vault_dir, policy)
        }
        assert watcher_admitted == full_admitted == set(scoped)

    dispositions = {sample.path: sample for sample in full_scan.samples}
    code = dispositions["src/logic.py"]
    parser_capable_non_source = dispositions["config/options.toml"]
    document_owned = dispositions["incoming/report.pdf"]
    assert (code.kind, code.admitted, code.reason) == (
        ContentKind.CODE,
        True,
        AdmissionReason.SOURCE_PROFILE,
    )
    assert (
        parser_capable_non_source.admitted,
        parser_capable_non_source.reason,
    ) == (False, AdmissionReason.SOURCE_PROFILE_EXCLUDED)
    assert (
        document_owned.kind,
        document_owned.admitted,
        document_owned.reason,
    ) == (ContentKind.DOCUMENT, True, AdmissionReason.EXPLICIT_ROUTE)

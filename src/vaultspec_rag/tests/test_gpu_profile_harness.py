"""Pure CPU checks for profiling artifact and native admission boundaries."""

from __future__ import annotations

import os
from argparse import Namespace
from pathlib import Path
from types import SimpleNamespace

import pytest

from dev._profile_tools import (
    sample_stacks,
    sampling_command,
    trace_kernel_count,
    verify_py_spy,
    write_json,
)
from dev._profile_workloads import chunk_sources, corpus
from dev.gpu_pipeline_profile import dedicated_consumer, encoder_run, oom_counts

pytestmark = pytest.mark.unit


def test_missing_binary_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        verify_py_spy(tmp_path / "missing.exe")


def test_unpinned_binary_is_rejected_before_spawn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Removing the digest comparison must trip the execution-boundary assertion.
    def reject_spawn(*_args: object, **_kwargs: object) -> None:
        pytest.fail("Unverified native profiler reached subprocess spawn")

    monkeypatch.setattr("dev._profile_tools.subprocess.Popen", reject_spawn)
    binary = tmp_path / "py-spy.exe"
    binary.write_bytes(b"untrusted executable")
    with (
        pytest.raises(ValueError, match="reviewed SHA256 pin"),
        sample_stacks(binary, tmp_path / "trace.json", 1),
    ):
        pytest.fail("Unverified native profiler reached workload execution")
    assert not (tmp_path / "trace.log").exists()


def test_sampling_command_can_target_only_current_process(tmp_path: Path) -> None:
    command = sampling_command(Path("py-spy.exe"), tmp_path / "trace.json", 30)
    assert command[command.index("--pid") + 1] == str(os.getpid())
    assert command[command.index("--duration") + 1] == "30"
    assert command[command.index("--format") + 1] == "speedscope"
    assert "--threads" in command
    # Removing nonblocking must fail here: interrupted sampling must not suspend work.
    assert "--nonblocking" in command
    assert "--native" not in command
    assert "--gil" not in command
    assert "--gil" in sampling_command(
        Path("py-spy.exe"), tmp_path / "gil.json", 30, gil=True
    )


@pytest.mark.parametrize("duration", [0, -1, 61])
def test_sampling_duration_is_bounded(tmp_path: Path, duration: int) -> None:
    with pytest.raises(ValueError, match="between 1 and 60"):
        sampling_command(Path("py-spy.exe"), tmp_path / "trace.json", duration)


def test_artifacts_are_exclusive(tmp_path: Path) -> None:
    path = tmp_path / "results.json"
    write_json(path, {"first": True})
    with pytest.raises(FileExistsError):
        write_json(path, {"second": True})
    with pytest.raises(FileExistsError):
        sampling_command(Path("py-spy.exe"), path, 1)
    assert '"first": true' in path.read_text()


def test_cuda_attribution_counts_only_actual_kernel_events(tmp_path: Path) -> None:
    path = tmp_path / "trace.json"
    write_json(
        path,
        {
            "traceEvents": [
                {"cat": "cuda_runtime", "ph": "X", "name": "cudaLaunchKernel"},
                {"cat": "kernel", "ph": "X", "name": "actual_device_kernel"},
                {"cat": "kernel", "ph": "M", "name": "metadata"},
            ]
        },
    )
    assert trace_kernel_count(path) == 1


def test_corpus_uses_canonical_chunks_and_preserves_selected_texts() -> None:
    source = "\n".join(f"def real_{n}():\n    return {n}\n" for n in range(20))
    chunks = chunk_sources([("example.py", source)], 80)
    selected = corpus(chunks, 4)
    actual = {chunk[0] for _, chunk in chunks}
    assert set(selected) == {"short", "long", "mixed", "token_dense"}
    assert all(len(texts) == 4 for texts in selected.values())
    assert all(text in actual for texts in selected.values() for text in texts)
    assert selected == corpus(chunks, 4)


def test_consumer_runs_off_caller_and_propagates_failure() -> None:
    import threading

    caller = threading.get_ident()
    result = dedicated_consumer(lambda: {"thread": threading.get_ident()})
    assert result["thread"] != caller

    def fail() -> dict:
        raise ValueError("consumer failed")

    with pytest.raises(ValueError, match="consumer failed"):
        dedicated_consumer(fail)


def test_combined_oom_counts_sum_independent_encoder_counters() -> None:
    events = [
        {"kind": "dense", "stage": "before", "oom_count": 0},
        {"kind": "dense", "stage": "after", "oom_count": 2},
        {"kind": "sparse", "stage": "before", "oom_count": 0},
        {"kind": "sparse", "stage": "after", "oom_count": 3},
        {"kind": "sparse", "stage": "after", "oom_count": 3},
    ]
    counts = oom_counts(events)
    assert counts == {"dense": 2, "sparse": 3}
    assert sum(counts.values()) == 5


def test_failed_encoder_work_drops_model_then_releases_cache_before_return(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    events: list[str] = []

    class Model:
        def __del__(self) -> None:
            events.append("model_deleted")

    def failed_work(_args: object, _workloads: object) -> dict:
        _model = Model()
        events.append("work")
        raise ValueError("work failed")

    def snapshot(_torch: object) -> dict:
        events.append("snapshot")
        return {"allocated": 0, "reserved": 0, "rss": 1}

    accelerator = SimpleNamespace(
        torch=SimpleNamespace(
            cuda=SimpleNamespace(synchronize=lambda: events.append("synchronize"))
        ),
        release_cache=lambda: events.append("release_cache"),
    )
    monkeypatch.setattr("vaultspec_rag._gpu.load_accelerator", lambda: accelerator)
    monkeypatch.setattr("dev.gpu_pipeline_profile.encoder_work", failed_work)
    monkeypatch.setattr("dev.gpu_pipeline_profile.memory_snapshot", snapshot)
    with pytest.raises(ValueError, match="work failed"):
        dedicated_consumer(lambda: encoder_run(Namespace(output=tmp_path), {}))
    assert events == [
        "work",
        "model_deleted",
        "synchronize",
        "release_cache",
        "synchronize",
        "snapshot",
    ]
    assert '"reserved": 0' in (tmp_path / "teardown.json").read_text()


def test_teardown_failure_prevents_successful_encoder_return(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail_release() -> None:
        raise RuntimeError("cache release failed")

    accelerator = SimpleNamespace(
        torch=SimpleNamespace(cuda=SimpleNamespace(synchronize=lambda: None)),
        release_cache=fail_release,
    )
    monkeypatch.setattr("vaultspec_rag._gpu.load_accelerator", lambda: accelerator)
    monkeypatch.setattr("dev.gpu_pipeline_profile.encoder_work", lambda _a, _w: {})
    monkeypatch.setattr(
        "dev.gpu_pipeline_profile.memory_snapshot", lambda _torch: {"reserved": 0}
    )
    with pytest.raises(RuntimeError, match="cache release failed"):
        dedicated_consumer(lambda: encoder_run(Namespace(output=tmp_path), {}))
    assert not (tmp_path / "teardown.json").exists()

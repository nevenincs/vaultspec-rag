"""Pure CPU checks for profiling artifact and native admission boundaries."""

from __future__ import annotations

import argparse
import os
from argparse import Namespace
from itertools import pairwise
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, cast

import pytest

from dev._profile_tools import (
    sample_stacks,
    sampling_command,
    trace_kernel_count,
    verify_py_spy,
    write_json,
)
from dev._profile_workloads import chunk_sources, corpus
from dev.gpu_pipeline_profile import (
    BucketEvent,
    DeviceSampler,
    arguments,
    budget_comparison,
    compare_sparse_dot_scores,
    compare_sparse_vectors,
    dedicated_consumer,
    encoder_run,
    energy_summary,
    energy_windows,
    oom_counts,
    sparse_budget_arm,
    sparse_budget_windows,
    sparse_budgets,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from ..embeddings import EmbeddingModel

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

    def fail() -> dict[str, object]:
        raise ValueError("consumer failed")

    with pytest.raises(ValueError, match="consumer failed"):
        dedicated_consumer(fail)


def test_combined_oom_counts_sum_independent_encoder_counters() -> None:
    events: list[BucketEvent] = [
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

    def failed_work(_args: object, _workloads: object) -> dict[str, object]:
        _model = Model()
        events.append("work")
        raise ValueError("work failed")

    def snapshot(_torch: object) -> dict[str, object]:
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

    def successful_work(_args: object, _workloads: object) -> dict[str, object]:
        return {}

    def empty_snapshot(_torch: object) -> dict[str, int]:
        return {"reserved": 0}

    monkeypatch.setattr("dev.gpu_pipeline_profile.encoder_work", successful_work)
    monkeypatch.setattr("dev.gpu_pipeline_profile.memory_snapshot", empty_snapshot)
    with pytest.raises(RuntimeError, match="cache release failed"):
        dedicated_consumer(lambda: encoder_run(Namespace(output=tmp_path), {}))
    assert not (tmp_path / "teardown.json").exists()


@pytest.mark.parametrize(
    "samples",
    [
        [],
        [{"monotonic": 1, "power_milliwatts": 100000}],
        [{"monotonic": 1, "power_milliwatts": None}],
    ],
)
def test_energy_withholds_values_without_enough_power_samples(
    samples: list[dict[str, object]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def integration_boundary(
        points: list[tuple[float, float]],
    ) -> Iterator[tuple[tuple[float, float], tuple[float, float]]]:
        # Accepting one sample must fail here before incidental zero-span division.
        assert len(points) >= 2, "Insufficient power samples reached integration"
        return pairwise(points)

    monkeypatch.setattr("dev.gpu_pipeline_profile.pairwise", integration_boundary)
    result = energy_summary(samples, 0, 30, 100)
    assert result["device_wide_joules"] is None
    assert result["device_wide_joules_per_item_estimate"] is None
    assert result["sampling_complete"] is False
    assert result["reason"] == "Fewer than two valid in-window power samples"


def test_energy_coverage_controls_per_item_estimate_without_extrapolating_span() -> (
    None
):
    # Lowering the coverage threshold must fail the withheld partial-span estimate.
    samples: list[dict[str, object]] = [
        {"monotonic": stamp, "power_milliwatts": 100000} for stamp in range(1, 30)
    ]
    partial = energy_summary(samples[:3], 0, 30, 100)
    covered = energy_summary(samples, 0, 30, 100)
    assert partial["sampled_span_seconds"] == 2
    assert partial["sample_count"] == 3
    partial_joules = partial["device_wide_joules"]
    assert partial_joules is not None and partial_joules > 0
    assert partial["device_wide_joules_per_item_estimate"] is None
    assert partial["sampling_complete"] is False
    assert covered["sampled_span_seconds"] == 28
    assert covered["coverage_fraction"] == pytest.approx(28 / 30)
    assert covered["sampling_complete"] is True
    covered_estimate = covered["device_wide_joules_per_item_estimate"]
    assert covered_estimate is not None and covered_estimate > 0
    covered_joules = covered["device_wide_joules"]
    assert covered_joules is not None and covered_joules > partial_joules


@pytest.mark.parametrize("times", [[1, 2, 1.5], [-1, 1], [1, 1], [1, 29]])
def test_invalid_sample_times_or_large_gaps_prevent_energy_claim(
    times: list[float],
) -> None:
    # Removing monotonicity checks or raising the maximum gap must fail null energy.
    result = energy_summary(
        [{"monotonic": stamp, "power_milliwatts": 100000} for stamp in times],
        0,
        30,
        100,
    )
    assert result["device_wide_joules"] is None
    assert result["device_wide_joules_per_item_estimate"] is None
    assert result["sampling_complete"] is False


def test_energy_windows_alternate_caps_and_record_actual_bucket_attempts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = [0.0]
    caps: list[int] = []

    def encode(
        _model: object, _texts: object, cap: int, kind: str, events: list[BucketEvent]
    ) -> None:
        assert kind == "combined"
        caps.append(cap)
        clock[0] += 6
        events.extend(
            [
                {"kind": "dense", "stage": "before", "bucket_items": 3, "oom_count": 0},
                {"kind": "dense", "stage": "after", "bucket_items": 3, "oom_count": 1},
                {
                    "kind": "sparse",
                    "stage": "before",
                    "bucket_items": 2,
                    "oom_count": 0,
                },
                {"kind": "sparse", "stage": "after", "bucket_items": 2, "oom_count": 2},
            ]
        )

    monkeypatch.setattr("dev.gpu_pipeline_profile.time.perf_counter", lambda: clock[0])
    monkeypatch.setattr("dev.gpu_pipeline_profile.encode_call", encode)

    def empty_snapshot(_torch: object) -> dict[str, int]:
        return {}

    def empty_ceilings(_model: object) -> dict[str, object]:
        return {}

    monkeypatch.setattr("dev.gpu_pipeline_profile.memory_snapshot", empty_snapshot)
    monkeypatch.setattr("dev.gpu_pipeline_profile.ceiling_state", empty_ceilings)
    torch = SimpleNamespace(
        cuda=SimpleNamespace(
            synchronize=lambda: None,
            reset_peak_memory_stats=lambda: None,
            max_memory_allocated=lambda: 17,
            max_memory_reserved=lambda: 29,
        )
    )
    sampler = DeviceSampler()
    sampler.samples = [
        {"monotonic": stamp, "power_milliwatts": 100000} for stamp in range(25)
    ]
    rows = energy_windows(
        cast("EmbeddingModel", object()),
        torch,
        Namespace(rounds=2, energy_seconds=5),
        {"mixed": ["a", "b", "c"]},
        sampler,
    )
    assert caps == [8, 32, 32, 8]
    assert all(row["input_items"] == 3 for row in rows)
    assert all(row["seconds"] == 6 for row in rows)
    assert all(
        row["peak_allocated"] == 17 and row["peak_reserved"] == 29 for row in rows
    )
    assert all(
        row["bucket_attempt_item_histograms"] == {"dense": {3: 1}, "sparse": {2: 1}}
        for row in rows
    )
    assert all(row["oom_count_by_encoder"] == {"dense": 1, "sparse": 2} for row in rows)


@pytest.mark.parametrize(
    "value", ["", "0,24000", "-1,24000", "x,24000", "4096,4096,24000", "4096"]
)
def test_sparse_budget_options_reject_invalid_arms(value: str) -> None:
    # Each positivity, uniqueness and reference guard failed when removed, then passed.
    with pytest.raises(argparse.ArgumentTypeError):
        sparse_budgets(value)


@pytest.mark.parametrize("seconds", [4, 61])
def test_sparse_budget_window_duration_bounds(
    seconds: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Mutation proof: allowing a four-second window failed; restored passed.
    monkeypatch.setattr(
        "sys.argv",
        [
            "profile",
            "encoder",
            "--output",
            "unused",
            "--sparse-budget-seconds",
            str(seconds),
        ],
    )
    with pytest.raises(SystemExit) as failure:
        arguments()
    assert failure.value.code == 2


def test_sparse_budget_arm_restores_original_policy_and_ceiling_on_error() -> None:
    # Fresh-ceiling and policy-restoration mutations failed; both restored passed.
    from ..embeddings import EncodeBatchCeiling

    original = EncodeBatchCeiling()
    original.record_oom(10000)
    model = SimpleNamespace(
        _sparse_encode_token_budget=8192, _sparse_batch_ceiling=original
    )
    with pytest.raises(ValueError, match="arm failed"), sparse_budget_arm(model, 4096):
        assert model._sparse_encode_token_budget == 4096
        assert model._sparse_batch_ceiling is not original
        assert model._sparse_batch_ceiling.clamp(4096) == 4096
        model._sparse_batch_ceiling.record_oom(4096)
        raise ValueError("arm failed")
    assert model._sparse_encode_token_budget == 8192
    assert model._sparse_batch_ceiling is original
    assert original.clamp(10000) == 5000


def test_sparse_budget_windows_alternate_fresh_arms_and_save_each_row(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ..embeddings import EncodeBatchCeiling

    original = EncodeBatchCeiling()
    model = SimpleNamespace(
        _sparse_encode_token_budget=8192,
        _sparse_batch_ceiling=original,
        _encode_token_budget=24000,
    )
    observed: list[int] = []
    ceilings: list[EncodeBatchCeiling] = []

    def warm(
        active: SimpleNamespace, _texts: object, size: int, kind: str, _events: object
    ) -> None:
        assert size == 32 and kind == "combined"
        ceiling = active._sparse_batch_ceiling
        assert (
            ceiling.clamp(active._sparse_encode_token_budget)
            == active._sparse_encode_token_budget
        )
        ceilings.append(ceiling)
        ceiling.record_oom(active._sparse_encode_token_budget)

    def window(
        active: SimpleNamespace,
        _torch: object,
        _texts: object,
        _sampler: object,
        arm: dict[str, int],
    ) -> dict[str, object]:
        assert active._encode_token_budget == 24000
        assert arm == {"size": 32, "seconds": 5}
        budget = active._sparse_encode_token_budget
        observed.append(budget)
        assert active._sparse_batch_ceiling.clamp(budget) == budget // 2
        return {"requested_batch_size": 32}

    monkeypatch.setattr("dev.gpu_pipeline_profile.encode_call", warm)
    monkeypatch.setattr("dev.gpu_pipeline_profile.sustained_window", window)
    args = Namespace(
        rounds=2,
        warmups=1,
        sparse_budgets=[4096, 8192, 24000],
        sparse_budget_seconds=5,
        output=tmp_path,
    )
    rows = sparse_budget_windows(
        model, None, args, {"mixed": ["actual text"]}, DeviceSampler()
    )
    assert observed == [4096, 8192, 24000, 24000, 8192, 4096]
    assert len({id(ceiling) for ceiling in ceilings}) == 6
    assert model._sparse_encode_token_budget == 8192
    assert model._sparse_batch_ceiling is original
    assert (
        len(list((tmp_path / "sparse-budget-window-rows").glob("*.json")))
        == len(rows)
        == 6
    )


def test_sparse_parity_rejects_changed_coordinates_and_score_drift() -> None:
    # Coordinate and score-comparison mutations failed; both restored passed.
    from ..embeddings import SparseResult

    reference = SparseResult([1, 3], [1.0, 2.0])
    changed_coordinates = compare_sparse_vectors(
        reference, SparseResult([1, 4], [1.0, 2.0])
    )
    changed_scores = compare_sparse_vectors(reference, SparseResult([1, 3], [1.0, 2.1]))
    assert changed_coordinates["coordinates_equal"] is False
    assert changed_coordinates["scores_close"] is False
    assert changed_scores["coordinates_equal"] is True
    assert changed_scores["scores_close"] is False
    assert changed_scores["maximum_absolute_score_error"] == pytest.approx(0.1)
    assert compare_sparse_vectors(reference, reference)["scores_close"] is True


def test_failed_sparse_parity_is_saved_and_never_reaches_timed_windows(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Mutation proof: bypassing rejection reached this interception; restored passed.
    def reject_window(*_args: object) -> None:
        pytest.fail("Failed sparse parity reached timed windows")

    def failed_parity(*_args: object) -> list[dict[str, bool]]:
        return [{"pass": False}]

    monkeypatch.setattr("dev.gpu_pipeline_profile.sparse_output_parity", failed_parity)
    monkeypatch.setattr("dev.gpu_pipeline_profile.sparse_budget_windows", reject_window)
    with pytest.raises(RuntimeError, match="Sparse budget output parity failed"):
        budget_comparison(None, None, Namespace(output=tmp_path), {}, DeviceSampler())
    assert '"pass": false' in (tmp_path / "sparse-budget-parity.json").read_text()


def test_sparse_comparison_rejects_changed_dense_policy(tmp_path: Path) -> None:
    # Mutation proof: bypassing the dense-policy guard failed; restored passed.
    model = SimpleNamespace(_encode_token_budget=8192)
    with pytest.raises(ValueError, match="unchanged dense token budget 24000"):
        sparse_budget_windows(
            model, None, Namespace(output=tmp_path), {}, DeviceSampler()
        )


@pytest.mark.parametrize("invalid", [float("inf"), float("nan"), -1.0])
@pytest.mark.parametrize("side", ["reference", "candidate", "both"])
def test_sparse_parity_rejects_invalid_weights_even_when_they_match(
    invalid: float, side: str
) -> None:
    from ..embeddings import SparseResult

    # Finite and nonnegative guard removals failed matching invalid weights;
    # both restored paths passed.
    reference = SparseResult([1], [invalid if side in ("reference", "both") else 1.0])
    candidate = SparseResult([1], [invalid if side in ("candidate", "both") else 1.0])
    result = compare_sparse_vectors(reference, candidate)
    assert result["scores_close"] is False
    assert result["maximum_absolute_score_error"] is None
    assert result["reference_weights_valid"] is (side == "candidate")
    assert result["candidate_weights_valid"] is (side == "reference")


@pytest.mark.parametrize("invalid", [float("inf"), float("nan")])
@pytest.mark.parametrize("side", ["reference", "candidate", "both"])
def test_sparse_dot_parity_rejects_nonfinite_scores(invalid: float, side: str) -> None:
    # Mutation proof: matching infinities passed without finite guards and
    # failed this assertion; the restored guards passed.
    reference = [invalid if side in ("reference", "both") else 1.0]
    candidate = [invalid if side in ("candidate", "both") else 1.0]
    result = compare_sparse_dot_scores(reference, candidate)
    assert result["scores_close"] is False
    assert result["reference_finite"] is (side == "candidate")
    assert result["candidate_finite"] is (side == "reference")
    assert result["reference_scores"] == ([1.0] if side == "candidate" else [None])
    assert result["candidate_scores"] == ([1.0] if side == "reference" else [None])

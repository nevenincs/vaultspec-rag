"""Real configuration tests for content ownership and policy snapshots."""

from __future__ import annotations

import pickle
from pathlib import Path

import pathspec
import pytest

from .._job_errors import JobErrorKind, classify_error_text
from ..config import ContentRouteConfig, RootContentPolicyConfig
from ..indexer._content_policy import (
    AdmissionPolicyError,
    AdmissionReason,
    ContentKind,
    ContentRoute,
    RootContentPolicy,
    SourceProfileVersion,
    classify_content,
)
from ..indexer._ignore_specs import is_ignored
from ..indexer._preprocess_config import (
    PREPROCESS_CONFIG_FILENAME,
    PreprocessPolicyError,
    PreprocessRule,
)
from ..indexer._resolved_policy import (
    DecoderPolicy,
    ResolvedIndexPolicy,
    ResolvedPreprocessRule,
    compile_content_policy,
    resolve_index_policy,
)

pytestmark = [pytest.mark.unit]


def test_raw_route_configuration_preserves_order_and_closed_targets() -> None:
    raw = RootContentPolicyConfig(
        "explicit-only-v1",
        (
            ContentRouteConfig("manuals/**", "document"),
            ContentRouteConfig("schemas/**/*.xsd", "code"),
        ),
    )
    resolved = compile_content_policy(raw)
    assert resolved.source_profile is SourceProfileVersion.EXPLICIT_ONLY_V1
    assert resolved.routes == (
        ContentRoute("manuals/**", ContentKind.DOCUMENT),
        ContentRoute("schemas/**/*.xsd", ContentKind.CODE),
    )


def test_unknown_route_target_has_structured_error_identity() -> None:
    raw = RootContentPolicyConfig(
        "conventional-v1",
        (ContentRouteConfig("**/*.py", "unknown"),),
    )
    with pytest.raises(AdmissionPolicyError) as caught:
        compile_content_policy(raw)
    assert (
        classify_error_text(str(caught.value)) is JobErrorKind.ADMISSION_CONFIG_INVALID
    )


def test_ignore_wins_before_explicit_and_conventional_admission() -> None:
    policy = RootContentPolicy(
        SourceProfileVersion.CONVENTIONAL_V1,
        (ContentRoute("generated/**", ContentKind.DOCUMENT),),
    )
    git_spec = pathspec.GitIgnoreSpec.from_lines(["generated/**"])
    ignored = is_ignored("generated/module.py", git_spec, None)
    result = classify_content(
        rel_path="generated/module.py",
        ignored=ignored,
        policy=policy,
    )
    assert not result.disposition.admitted
    assert result.disposition.reason is AdmissionReason.IGNORED
    assert result.language is None


def test_overlapping_explicit_targets_must_agree_for_a_real_path() -> None:
    policy = RootContentPolicy(
        SourceProfileVersion.EXPLICIT_ONLY_V1,
        (
            ContentRoute("schemas/**", ContentKind.DOCUMENT),
            ContentRoute("schemas/**/*.xsd", ContentKind.CODE),
        ),
    )
    with pytest.raises(AdmissionPolicyError):
        classify_content(
            rel_path="schemas/v2/types.xsd",
            ignored=False,
            policy=policy,
        )


def test_explicit_routes_are_path_layout_agnostic() -> None:
    for prefix in ("manuals", "resources", "inputs"):
        policy = RootContentPolicy(
            SourceProfileVersion.EXPLICIT_ONLY_V1,
            (ContentRoute(f"{prefix}/**", ContentKind.DOCUMENT),),
        )
        result = classify_content(
            rel_path=f"{prefix}/nested/guide.txt",
            ignored=False,
            policy=policy,
        )
        assert result.disposition.kind is ContentKind.DOCUMENT
        assert result.disposition.reason is AdmissionReason.EXPLICIT_ROUTE


def test_snapshot_rejects_route_transform_conflict_before_use() -> None:
    policy = RootContentPolicy(
        SourceProfileVersion.EXPLICIT_ONLY_V1,
        (ContentRoute("manuals/**", ContentKind.DOCUMENT),),
    )
    rule = ResolvedPreprocessRule.from_rule(
        PreprocessRule(
            "manuals/**",
            "compile {path}",
            None,
            10,
            ContentKind.CODE,
            "1",
            "fail",
            30.0,
            {},
            0,
        )
    )
    with pytest.raises(AdmissionPolicyError):
            ResolvedIndexPolicy(
                Path.cwd().resolve(),
                1,
            policy,
            2,
            (rule,),
            DecoderPolicy(),
            "default",
            True,
            4096,
            (),
            (),
            (),
        )


def test_resolved_snapshot_pickle_preserves_classification_and_fingerprints(
    tmp_path: Path,
) -> None:
    policy = RootContentPolicy(SourceProfileVersion.CONVENTIONAL_V1)
    snapshot = resolve_index_policy(
        tmp_path,
        content_policy=policy,
        extra_excludes=("generated/**",),
        execution_mode="default",
        html_strip=True,
        max_emitted_bytes=4096,
    )
    restored = pickle.loads(pickle.dumps(snapshot))
    assert restored == snapshot
    assert restored.fingerprints == snapshot.fingerprints
    assert restored.classify("package/module.py") == snapshot.classify(
        "package/module.py"
    )
    assert restored.classify("generated/module.py").disposition.reason is (
        AdmissionReason.IGNORED
    )


def test_legacy_migration_refusal_does_not_mutate_root(tmp_path: Path) -> None:
    config_path = tmp_path / PREPROCESS_CONFIG_FILENAME
    config_path.write_text("version = 1\n", encoding="utf-8")
    before = {
        path.relative_to(tmp_path).as_posix(): path.read_bytes()
        for path in tmp_path.rglob("*")
        if path.is_file()
    }
    with pytest.raises(PreprocessPolicyError) as caught:
        resolve_index_policy(
            tmp_path,
            content_policy=RootContentPolicy(SourceProfileVersion.CONVENTIONAL_V1),
        )
    after = {
        path.relative_to(tmp_path).as_posix(): path.read_bytes()
        for path in tmp_path.rglob("*")
        if path.is_file()
    }
    assert caught.value.error_kind is JobErrorKind.MIGRATION_REQUIRED
    assert after == before

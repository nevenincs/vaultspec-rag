"""Declared preprocess inputs in extractor identity and the extraction cache key.

A rule may name the files that define its extractor. Their content joins the
rule's content fingerprint and its cache key, so an edited hook script is
seen as an extraction change. Real files and real policy resolution under
``tmp_path``; no mocks.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

import pytest

from .._job_errors import JobErrorKind
from ..indexer import _config_epoch as ce
from ..indexer._content_policy import (
    ContentKind,
    RootContentPolicy,
    SourceProfileVersion,
)
from ..indexer._preprocess_cache import PreprocessCacheIdentity
from ..indexer._preprocess_config import (
    PREPROCESS_CONFIG_FILENAME,
    PreprocessPolicyError,
    PreprocessRule,
    load_preprocess_rules,
)
from ..indexer._resolved_policy import (
    IndexPolicyResolutionOptions,
    ResolvedPreprocessRule,
    resolve_index_policy,
)

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = [pytest.mark.unit]


def _write_policy(root: Path, inputs: str | None) -> None:
    lines = [
        "version = 2",
        "",
        "[[rule]]",
        'pattern = "*.pdf"',
        'target = "document"',
        'extractor_version = "1"',
        "command = 'python tools/extract.py {path}'",
    ]
    if inputs is not None:
        lines.append(f"inputs = {inputs}")
    (root / PREPROCESS_CONFIG_FILENAME).write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )


def _hook_root(root: Path, inputs: str | None = '["tools/*.py"]') -> Path:
    tools = root / "tools"
    tools.mkdir(parents=True)
    (tools / "extract.py").write_text("print('v1')\n", encoding="utf-8")
    (tools / "helper.py").write_text("HELPER = 1\n", encoding="utf-8")
    (tools / "notes.txt").write_text("not an input\n", encoding="utf-8")
    _write_policy(root, inputs)
    return root


def _only_rule(root: Path) -> PreprocessRule:
    rules = load_preprocess_rules(root, strict=True).rules
    assert len(rules) == 1
    return rules[0]


def _cache_key(root: Path) -> str:
    return PreprocessCacheIdentity.from_rule(
        source_path="docs/a.pdf",
        source_hash="source-hash",
        rule=_only_rule(root),
        mode="single",
        max_emitted_bytes=4096,
    ).key


def _content_fingerprints(root: Path) -> tuple[str, str, str]:
    policy = resolve_index_policy(
        root,
        IndexPolicyResolutionOptions(
            content_policy=RootContentPolicy(SourceProfileVersion.CONVENTIONAL_V1),
            execution_mode="default",
            html_strip=True,
            max_emitted_bytes=4096,
        ),
    )
    return (
        policy.fingerprints.content,
        policy.fingerprints_for(ContentKind.DOCUMENT).content,
        policy.fingerprints_for(ContentKind.CODE).content,
    )


def _refusal(root: Path) -> PreprocessPolicyError:
    with pytest.raises(PreprocessPolicyError) as caught:
        load_preprocess_rules(root)
    assert caught.value.error_kind is JobErrorKind.ADMISSION_CONFIG_INVALID
    return caught.value


def _link_directory(link: Path, target: Path) -> None:
    """Create a directory link without needing the symlink privilege."""
    if os.name == "nt":
        import _winapi

        _winapi.CreateJunction(str(target), str(link))
    else:
        link.symlink_to(target, target_is_directory=True)


# Pinned from the fingerprint and cache code as it stood before rules could
# declare inputs: an undeclared rule must keep byte-identical identities, or
# every existing hook root would be forced to rebuild on upgrade.
_PINNED_CONTENT = (
    "085bf51576d27b4c47efd89577d403c5399dc08b692a6de562a126e8cc0594745"
    "3619dcdb0ff83f65114f8a0e46550ce5b80df5e43b70d98a7632922e79bbcad"
)
_PINNED_DOCUMENT_CONTENT = (
    "92f6df259cf97296a0e143d3fa2bcee8518e080b2fcd7c67f9f01c4beaadace3"
    "8905a935a31af211d36b0e0fc5357d93153e568e9a58fbf3b1ded13635152615"
)
_PINNED_EXECUTION = (
    "97a9716705196e2c942c927a8cb1cc60008610709941454dbabb9a72ecc0f486"
    "cb28c4325a6d2c0f2ec79ce966f0b1a75d02e3bbad940cbde9563320191fc244"
)


def test_undeclared_rule_keeps_its_pre_inputs_identities() -> None:
    rule = PreprocessRule(
        pattern="*.pdf",
        command="python tools/extract.py {path}",
        entry_point=None,
        priority=100,
        target=ContentKind.DOCUMENT,
        extractor_version="1",
        on_error="skip",
        timeout_s=120.0,
        options={},
        order=0,
    )
    fingerprints = ce.resolved_policy_fingerprints(
        policy_schema_version=1,
        content_policy=RootContentPolicy(SourceProfileVersion.CONVENTIONAL_V1),
        gitignore_patterns=(),
        vaultragignore_patterns=(),
        extra_excludes=(),
        preprocess_schema_version=2,
        preprocess_rules=(ResolvedPreprocessRule.from_rule(rule),),
        decoder_encoding="utf-8",
        decoder_errors="replace",
        normalize_newlines=True,
        execution_mode="default",
        html_strip=True,
        max_emitted_bytes=4096,
        document_chunking={
            "chunk_chars": 2000,
            "chunk_overlap_chars": 200,
            "unit_text_max_chars": 4000,
        },
    )
    identity = PreprocessCacheIdentity.from_rule(
        source_path="docs/a.pdf",
        source_hash="h",
        rule=rule,
        mode="single",
        max_emitted_bytes=4096,
    )
    assert fingerprints.content == _PINNED_CONTENT
    assert fingerprints.per_kind.document.content == _PINNED_DOCUMENT_CONTENT
    assert identity.execution_fingerprint == _PINNED_EXECUTION


def test_undeclared_rule_carries_no_inputs_digest(tmp_path: Path) -> None:
    rule = _only_rule(_hook_root(tmp_path, inputs=None))
    assert rule.inputs == ()
    assert rule.inputs_digest is None


def test_editing_a_declared_input_changes_fingerprint_and_cache_key(
    tmp_path: Path,
) -> None:
    root = _hook_root(tmp_path)
    before_fingerprints = _content_fingerprints(root)
    before_key = _cache_key(root)

    (root / "tools" / "extract.py").write_text("print('v2')\n", encoding="utf-8")

    after_fingerprints = _content_fingerprints(root)
    # Guard: with the inputs_digest entry removed from the identity payloads,
    # these two assertions fail while the rule table is unchanged.
    assert after_fingerprints[0] != before_fingerprints[0]
    assert after_fingerprints[1] != before_fingerprints[1]
    # The rule targets documents, so the code identity is untouched.
    assert after_fingerprints[2] == before_fingerprints[2]
    # Guard: with inputs_digest left out of the cache execution mapping, the
    # rebuild would hit the stale extraction under this same key.
    assert _cache_key(root) != before_key


def test_editing_an_undeclared_file_changes_nothing(tmp_path: Path) -> None:
    root = _hook_root(tmp_path)
    before_fingerprints = _content_fingerprints(root)
    before_key = _cache_key(root)

    (root / "tools" / "notes.txt").write_text("edited\n", encoding="utf-8")
    (root / "README.md").write_text("edited\n", encoding="utf-8")

    # Guard: hashing anything beyond the matched files (for example the whole
    # tools directory) fails these assertions.
    assert _content_fingerprints(root) == before_fingerprints
    assert _cache_key(root) == before_key


def test_input_edit_keeps_the_approval_digest(tmp_path: Path) -> None:
    root = _hook_root(tmp_path)
    before = load_preprocess_rules(root, strict=True).policy_digest
    (root / "tools" / "extract.py").write_text("print('v2')\n", encoding="utf-8")
    assert load_preprocess_rules(root, strict=True).policy_digest == before


def test_inputs_digest_survives_snapshot_materialization(tmp_path: Path) -> None:
    rule = _only_rule(_hook_root(tmp_path))
    assert rule.inputs == ("tools/*.py",)
    assert rule.inputs_digest is not None
    restored = ResolvedPreprocessRule.from_rule(rule).materialize()
    assert restored.inputs == rule.inputs
    assert restored.inputs_digest == rule.inputs_digest


@pytest.mark.parametrize(
    "pattern",
    [
        pytest.param('["../outside.py"]', id="parent"),
        pytest.param('["tools/../../outside.py"]', id="nested-parent"),
        pytest.param('["/tools/extract.py"]', id="absolute"),
        pytest.param('["C:/outside.py"]', id="drive"),
        pytest.param('["tools\\\\extract.py"]', id="backslash"),
        pytest.param('["!tools/extract.py"]', id="negation"),
    ],
)
def test_input_pattern_escaping_the_root_is_refused(
    tmp_path: Path, pattern: str
) -> None:
    root = tmp_path / "project"
    (tmp_path / "outside.py").write_text("print('outside')\n", encoding="utf-8")
    _hook_root(root, inputs=pattern)
    # Guard: without the pattern-shape check, "../outside.py" is never
    # matched and the refusal names "matches no file" instead.
    assert "stay inside it" in str(_refusal(root))


def test_input_reached_through_a_linked_prefix_is_refused(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "extract.py").write_text("print('outside')\n", encoding="utf-8")
    _link_directory(root / "tools", outside)
    _write_policy(root, '["tools/*.py"]')
    # Guard: without the canonical-prefix check only the per-file read
    # refuses, naming the file rather than the link, so this assertion fails.
    assert "outside the project root through a link" in str(_refusal(root))


def test_input_walk_through_a_linked_directory_is_refused(tmp_path: Path) -> None:
    root = _hook_root(tmp_path / "project", inputs='["tools/**"]')
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "lib.py").write_text("print('outside')\n", encoding="utf-8")
    _link_directory(root / "tools" / "vendor", outside)
    # Guard: without the linked-directory check the refusal depends on how
    # the platform walk treats links; it no longer names the link.
    assert "reaching the link 'tools/vendor'" in str(_refusal(root))


def test_input_pattern_matching_nothing_fails_the_root_closed(
    tmp_path: Path,
) -> None:
    root = _hook_root(tmp_path, inputs='["tools/missing.py"]')
    # Non-strict loading still raises: the rule is never dropped.
    assert "matches no file" in str(_refusal(root))


@pytest.mark.parametrize(
    "inputs",
    [
        pytest.param("[]", id="empty"),
        pytest.param('"tools/extract.py"', id="not-a-list"),
        pytest.param("[1]", id="not-a-string"),
    ],
)
def test_malformed_inputs_are_refused(tmp_path: Path, inputs: str) -> None:
    root = _hook_root(tmp_path, inputs=inputs)
    assert "'inputs'" in str(_refusal(root))


def test_too_many_input_files_are_refused(tmp_path: Path) -> None:
    root = _hook_root(tmp_path, inputs='["many/*.py"]')
    many = root / "many"
    many.mkdir()
    for index in range(257):
        (many / f"m{index}.py").write_text("", encoding="utf-8")
    assert "more than 256 input files" in str(_refusal(root))


def test_oversized_inputs_are_refused(tmp_path: Path) -> None:
    root = _hook_root(tmp_path, inputs='["tools/*.py"]')
    with (root / "tools" / "big.py").open("wb") as stream:
        stream.truncate(32 * 1024 * 1024 + 1)
    assert "larger than 33554432 bytes" in str(_refusal(root))

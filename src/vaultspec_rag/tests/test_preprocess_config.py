"""Real-file tests for versioned preprocessing ownership configuration."""

from __future__ import annotations

import os
import pickle
import subprocess
import sys
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from .._job_errors import JobErrorKind
from ..config._types import EnvVar
from ..indexer._content_policy import ContentKind
from ..indexer._preprocess_config import (
    PREPROCESS_CONFIG_FILENAME,
    PreprocessConfig,
    PreprocessConfigError,
    PreprocessPolicyError,
    load_preprocess_rules,
)

pytestmark = [pytest.mark.unit]


def _write_config(root: Path, body: str) -> None:
    (root / PREPROCESS_CONFIG_FILENAME).write_text(body, encoding="utf-8")


def test_absent_config_yields_empty_versioned_config(tmp_path: Path) -> None:
    config = load_preprocess_rules(tmp_path, strict=True)
    assert not config
    assert config.schema_version == 2
    assert config.rules == []


def test_schema_v2_rule_loads_required_owner_and_extractor_version(
    tmp_path: Path,
) -> None:
    _write_config(
        tmp_path,
        """
        version = 2

        [[rule]]
        pattern = "*.pdf"
        command = "extract {path}"
        target = "document"
        extractor_version = "3.2.1"
        on_error = "skip"
        timeout_s = 30
        """,
    )
    config = load_preprocess_rules(tmp_path, strict=True)
    rule = config.match("manuals/report.pdf")
    assert rule is not None
    assert rule.target is ContentKind.DOCUMENT
    assert rule.extractor_version == "3.2.1"
    assert rule.command == "extract {path}"
    assert rule.timeout_s == 30.0
    assert config.match("manuals/report.txt") is None


def test_priority_then_source_order_is_deterministic(tmp_path: Path) -> None:
    _write_config(
        tmp_path,
        """
        version = 2

        [[rule]]
        pattern = "*.pdf"
        command = "later {path}"
        target = "document"
        extractor_version = "1"
        priority = 50

        [[rule]]
        pattern = "*.pdf"
        command = "first {path}"
        target = "document"
        extractor_version = "1"
        priority = 10
        """,
    )
    config = load_preprocess_rules(tmp_path, strict=True)
    matched = config.match("manual.pdf")
    assert matched is not None
    assert matched.command == "first {path}"
    assert [rule.command for rule in config.rules] == [
        "first {path}",
        "later {path}",
    ]


def test_options_and_entry_point_survive_real_loading_and_pickle(
    tmp_path: Path,
) -> None:
    _write_config(
        tmp_path,
        """
        version = 2

        [[rule]]
        pattern = "*.rst"
        entry_point = "project.extract:rst"
        target = "document"
        extractor_version = "2026.07"

        [rule.options]
        section_limit = 5
        include_hidden = false
        """,
    )
    rule = load_preprocess_rules(tmp_path, strict=True).match("guide.rst")
    assert rule is not None
    assert rule.entry_point == "project.extract:rst"
    assert rule.command is None
    assert rule.options == {"section_limit": 5, "include_hidden": False}
    assert pickle.loads(pickle.dumps(rule)) == rule


def test_toml_temporal_options_are_canonical_json_at_admission(
    tmp_path: Path,
) -> None:
    _write_config(
        tmp_path,
        """
        version = 2

        [[rule]]
        pattern = "*.rst"
        entry_point = "project.extract:rst"
        target = "document"
        extractor_version = "2026.07"

        [rule.options]
        release_date = 2026-07-22
        release_time = 14:30:15
        generated_at = 2026-07-22T14:30:15Z
        """,
    )
    rule = load_preprocess_rules(tmp_path, strict=True).match("guide.rst")
    assert rule is not None
    assert rule.options == {
        "release_date": "2026-07-22",
        "release_time": "14:30:15",
        "generated_at": "2026-07-22T14:30:15+00:00",
    }


def test_non_finite_option_is_rejected_at_admission(tmp_path: Path) -> None:
    _write_config(
        tmp_path,
        """
        version = 2

        [[rule]]
        pattern = "*.rst"
        entry_point = "project.extract:rst"
        target = "document"
        extractor_version = "2026.07"

        [rule.options]
        threshold = inf
        """,
    )
    with pytest.raises(PreprocessConfigError, match="non-finite"):
        load_preprocess_rules(tmp_path, strict=True)
    assert load_preprocess_rules(tmp_path).rules == []


def test_omitted_timeout_resolves_to_finite_ceiling(tmp_path: Path) -> None:
    _write_config(
        tmp_path,
        """
        version = 2

        [[rule]]
        pattern = "*.pdf"
        command = "extract {path}"
        target = "document"
        extractor_version = "1"
        """,
    )
    rule = load_preprocess_rules(tmp_path, strict=True).match("manual.pdf")
    assert rule is not None
    assert rule.timeout_s == 120.0


def test_rule_source_ceiling_is_positive_and_survives_resolution(
    tmp_path: Path,
) -> None:
    _write_config(
        tmp_path,
        """
        version = 2

        [[rule]]
        pattern = "*.bin"
        command = "extract {path}"
        target = "document"
        extractor_version = "1"
        max_source_bytes = 4096
        """,
    )
    rule = load_preprocess_rules(tmp_path, strict=True).match("payload.bin")
    assert rule is not None
    assert rule.max_source_bytes == 4096


@pytest.mark.parametrize("value", [0, -1, True, "4096"])
def test_invalid_rule_source_ceiling_is_rejected(
    tmp_path: Path,
    value: object,
) -> None:
    rendered = str(value).lower() if isinstance(value, bool) else repr(value)
    _write_config(
        tmp_path,
        f"""
        version = 2

        [[rule]]
        pattern = "*.bin"
        command = "extract {{path}}"
        target = "document"
        extractor_version = "1"
        max_source_bytes = {rendered}
        """,
    )
    with pytest.raises(PreprocessConfigError):
        load_preprocess_rules(tmp_path, strict=True)


def test_invalid_invocation_is_dropped_non_strict_and_rejected_strict(
    tmp_path: Path,
) -> None:
    _write_config(
        tmp_path,
        """
        version = 2

        [[rule]]
        pattern = "*.pdf"
        target = "document"
        extractor_version = "1"
        """,
    )
    assert load_preprocess_rules(tmp_path).rules == []
    with pytest.raises(PreprocessConfigError):
        load_preprocess_rules(tmp_path, strict=True)


def test_malformed_toml_degrades_non_strict_and_raises_strict(tmp_path: Path) -> None:
    _write_config(tmp_path, "this is = = not toml [[[\n")
    assert load_preprocess_rules(tmp_path).rules == []
    with pytest.raises(PreprocessConfigError):
        load_preprocess_rules(tmp_path, strict=True)


@pytest.mark.parametrize(
    ("body", "error_kind"),
    [
        (
            """
            version = 1
            """,
            JobErrorKind.MIGRATION_REQUIRED,
        ),
        (
            """
            version = 2
            [[rule]]
            pattern = "*.pdf"
            command = "extract {path}"
            extractor_version = "1"
            """,
            JobErrorKind.MIGRATION_REQUIRED,
        ),
        (
            """
            version = 2
            [[rule]]
            pattern = "*.pdf"
            command = "extract {path}"
            target = "document"
            """,
            JobErrorKind.MIGRATION_REQUIRED,
        ),
        (
            """
            version = 2
            [[rule]]
            pattern = "*.pdf"
            command = "extract {path}"
            target = "unknown"
            extractor_version = "1"
            """,
            JobErrorKind.ADMISSION_CONFIG_INVALID,
        ),
        (
            """
            version = 99
            """,
            JobErrorKind.ADMISSION_CONFIG_INVALID,
        ),
    ],
)
def test_schema_and_owner_defects_fail_closed_in_every_mode(
    tmp_path: Path,
    body: str,
    error_kind: JobErrorKind,
) -> None:
    _write_config(tmp_path, body)
    for strict in (False, True):
        with pytest.raises(PreprocessPolicyError) as caught:
            load_preprocess_rules(tmp_path, strict=strict)
        assert caught.value.error_kind is error_kind


def test_conflicting_same_pattern_owners_reject_whole_config(tmp_path: Path) -> None:
    _write_config(
        tmp_path,
        """
        version = 2

        [[rule]]
        pattern = "inputs/**"
        command = "extract {path}"
        target = "document"
        extractor_version = "1"

        [[rule]]
        pattern = "inputs/**"
        command = "compile {path}"
        target = "code"
        extractor_version = "1"
        """,
    )
    with pytest.raises(PreprocessPolicyError) as caught:
        load_preprocess_rules(tmp_path)
    assert caught.value.error_kind is JobErrorKind.ADMISSION_CONFIG_INVALID


def test_config_pickle_rebuilds_matchers_from_versioned_rules(tmp_path: Path) -> None:
    _write_config(
        tmp_path,
        """
        version = 2

        [[rule]]
        pattern = "schemas/**/*.xsd"
        command = "compile {path}"
        target = "code"
        extractor_version = "4"
        """,
    )
    config = load_preprocess_rules(tmp_path, strict=True)
    restored = pickle.loads(pickle.dumps(config))
    assert isinstance(restored, PreprocessConfig)
    assert restored.schema_version == 2
    assert restored.match("schemas/v2/types.xsd") == config.match(
        "schemas/v2/types.xsd"
    )


def test_off_mode_suppresses_execution_but_strict_retains_routing(
    tmp_path: Path,
) -> None:
    _write_config(
        tmp_path,
        """
        version = 2

        [[rule]]
        pattern = "*.pdf"
        command = "extract {path}"
        target = "document"
        extractor_version = "1"
        """,
    )
    environment = os.environ.copy()
    environment[EnvVar.PREPROCESS.value] = "off"
    environment[EnvVar.STATUS_DIR.value] = str(tmp_path / "status")
    script = """
from pathlib import Path
import sys
from vaultspec_rag.indexer._preprocess_config import (  # absolute-import-ok
    load_preprocess_rules,
)
root = Path(sys.argv[1])
runtime_count = len(load_preprocess_rules(root).rules)
strict_count = len(load_preprocess_rules(root, strict=True).rules)
print(runtime_count, strict_count)
"""
    completed = subprocess.run(
        [sys.executable, "-c", script, str(tmp_path)],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "1 1"

"""Unit tests for preprocess rule config loading (no GPU).

Exercises D1/D2/D3: real ``.vaultragpreprocess.toml`` fixtures written to a
tmp project root, deterministic ordering, ignore-style matching, the v1
command-only constraint, and the degrade-vs-strict error policy.
"""

from pathlib import Path

import pytest

from ..indexer._preprocess_config import (
    PREPROCESS_CONFIG_FILENAME,
    PreprocessConfig,
    PreprocessConfigError,
    load_preprocess_rules,
)

pytestmark = [pytest.mark.unit]


def _write_config(root: Path, body: str) -> None:
    (root / PREPROCESS_CONFIG_FILENAME).write_text(body, encoding="utf-8")


def test_absent_config_yields_empty(tmp_path: Path) -> None:
    config = load_preprocess_rules(tmp_path)
    assert not config
    assert config.rules == []
    assert config.match("anything.pdf") is None


def test_single_command_rule_loads_and_matches(tmp_path: Path) -> None:
    _write_config(
        tmp_path,
        """
        version = 1

        [[rule]]
        pattern = "*.pdf"
        command = "extract {path}"
        on_error = "skip"
        timeout_s = 30
        """,
    )
    config = load_preprocess_rules(tmp_path)
    assert bool(config)
    rule = config.match("docs/report.pdf")
    assert rule is not None
    assert rule.command == "extract {path}"
    assert rule.on_error == "skip"
    assert rule.timeout_s == 30.0
    assert config.match("docs/report.txt") is None


def test_priority_then_file_order_is_deterministic(tmp_path: Path) -> None:
    _write_config(
        tmp_path,
        """
        [[rule]]
        pattern = "*.pdf"
        command = "low-priority {path}"
        priority = 50

        [[rule]]
        pattern = "*.pdf"
        command = "high-priority {path}"
        priority = 10
        """,
    )
    config = load_preprocess_rules(tmp_path)
    rule = config.match("a.pdf")
    assert rule is not None
    assert rule.command == "high-priority {path}"
    # Precedence order is exposed for inspection (lower priority first).
    assert [r.command for r in config.rules] == [
        "high-priority {path}",
        "low-priority {path}",
    ]


def test_equal_priority_breaks_on_file_order(tmp_path: Path) -> None:
    _write_config(
        tmp_path,
        """
        [[rule]]
        pattern = "data/*"
        command = "first {path}"

        [[rule]]
        pattern = "data/*"
        command = "second {path}"
        """,
    )
    config = load_preprocess_rules(tmp_path)
    rule = config.match("data/x.bin")
    assert rule is not None
    assert rule.command == "first {path}"


def test_options_table_is_carried(tmp_path: Path) -> None:
    _write_config(
        tmp_path,
        """
        [[rule]]
        pattern = "*.xlsx"
        command = "xlsx {path}"

        [rule.options]
        sheet_limit = 5
        include_hidden = false
        """,
    )
    config = load_preprocess_rules(tmp_path)
    rule = config.match("book.xlsx")
    assert rule is not None
    assert rule.options == {"sheet_limit": 5, "include_hidden": False}


def test_entry_point_rule_loads(tmp_path: Path) -> None:
    _write_config(
        tmp_path,
        """
        [[rule]]
        pattern = "*.rst"
        entry_point = "myproj.pre:rst"
        """,
    )
    config = load_preprocess_rules(tmp_path)
    rule = config.match("a.rst")
    assert rule is not None
    assert rule.entry_point == "myproj.pre:rst"
    assert rule.command is None


def test_malformed_entry_point_is_dropped(tmp_path: Path) -> None:
    _write_config(
        tmp_path,
        """
        [[rule]]
        pattern = "*.rst"
        entry_point = "no-colon"
        """,
    )
    assert load_preprocess_rules(tmp_path).rules == []


def test_rule_with_both_command_and_entry_point_is_dropped(tmp_path: Path) -> None:
    _write_config(
        tmp_path,
        """
        [[rule]]
        pattern = "*.pdf"
        command = "c {path}"
        entry_point = "m:f"
        """,
    )
    assert load_preprocess_rules(tmp_path).rules == []


def test_invalid_on_error_is_dropped_but_valid_rule_survives(tmp_path: Path) -> None:
    _write_config(
        tmp_path,
        """
        [[rule]]
        pattern = "*.bad"
        command = "c {path}"
        on_error = "explode"

        [[rule]]
        pattern = "*.good"
        command = "c {path}"
        """,
    )
    config = load_preprocess_rules(tmp_path)
    assert config.match("x.bad") is None
    assert config.match("x.good") is not None


def test_malformed_toml_degrades_to_empty(tmp_path: Path) -> None:
    _write_config(tmp_path, "this is = = not toml [[[")
    config = load_preprocess_rules(tmp_path)
    assert isinstance(config, PreprocessConfig)
    assert config.rules == []


def test_strict_mode_raises_on_malformed_toml(tmp_path: Path) -> None:
    _write_config(tmp_path, "this is = = not toml [[[")
    with pytest.raises(PreprocessConfigError):
        load_preprocess_rules(tmp_path, strict=True)


def test_strict_mode_raises_on_invalid_rule(tmp_path: Path) -> None:
    _write_config(
        tmp_path,
        """
        [[rule]]
        pattern = "*.pdf"
        on_error = "skip"
        """,
    )
    with pytest.raises(PreprocessConfigError):
        load_preprocess_rules(tmp_path, strict=True)


def test_negative_timeout_is_rejected(tmp_path: Path) -> None:
    _write_config(
        tmp_path,
        """
        [[rule]]
        pattern = "*.pdf"
        command = "c {path}"
        timeout_s = -5
        """,
    )
    assert load_preprocess_rules(tmp_path).rules == []


def test_newer_config_version_degrades(tmp_path: Path) -> None:
    _write_config(
        tmp_path,
        """
        version = 99

        [[rule]]
        pattern = "*.pdf"
        command = "c {path}"
        """,
    )
    # A future config-schema version is not silently half-read (CONFIG-001).
    assert load_preprocess_rules(tmp_path).rules == []


def test_newer_config_version_strict_raises(tmp_path: Path) -> None:
    _write_config(tmp_path, "version = 99\n")
    with pytest.raises(PreprocessConfigError):
        load_preprocess_rules(tmp_path, strict=True)


def test_resolved_rule_is_picklable(tmp_path: Path) -> None:
    import pickle

    _write_config(
        tmp_path,
        """
        [[rule]]
        pattern = "*.pdf"
        command = "c {path}"
        """,
    )
    rule = load_preprocess_rules(tmp_path).match("a.pdf")
    assert rule is not None
    restored = pickle.loads(pickle.dumps(rule))
    assert restored == rule

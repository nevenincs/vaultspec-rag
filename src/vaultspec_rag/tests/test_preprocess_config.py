"""Unit tests for preprocess rule config loading and the kill switch (no GPU).

Exercises two layers over real ``.vaultragpreprocess.toml`` fixtures written to
a tmp project root:

- Rule resolution (D1/D2/D3): deterministic ordering, ignore-style matching,
  the command/entry_point constraint, and the degrade-vs-strict error policy.
- The tri-state preprocess mode (preprocess-sandbox ADR D7/D8): rules resolve
  for any root with no trust check because the OS sandbox at the runner is the
  security boundary, ``off`` is the kill switch, and ``unsandboxed`` runs the
  rules without a sandbox. The trust-on-first-use store was removed here.

Every test isolates ``VAULTSPEC_RAG_STATUS_DIR`` to a tmp path via the autouse
fixture (the managed-singleton isolation sibling) and clears the mode env vars
so the resolved mode is the on-sandbox ``default``; the off/unsandboxed tests
set the env explicitly.
"""

from collections.abc import Iterator
from pathlib import Path

import pytest

from ..config import EnvVar, reset_config
from ..indexer._preprocess_config import (
    PREPROCESS_CONFIG_FILENAME,
    PreprocessConfig,
    PreprocessConfigError,
    load_preprocess_rules,
)

pytestmark = [pytest.mark.unit]


@pytest.fixture(autouse=True)
def _isolate_status_dir_and_default_mode(  # pyright: ignore[reportUnusedFunction]
    tmp_path_factory: pytest.TempPathFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[None]:
    """Isolate the status dir to a tmp path and resolve the on-sandbox default.

    Clearing both mode env vars leaves the resolved mode at ``default``, which
    resolves a root's rules for any root (containment is the boundary, not
    consent), so the rule-resolution tests load rules without any trust act.
    The off/unsandboxed tests set the env themselves.
    """
    status = tmp_path_factory.mktemp("status")
    monkeypatch.setenv(EnvVar.STATUS_DIR.value, str(status))
    monkeypatch.delenv(EnvVar.PREPROCESS.value, raising=False)
    monkeypatch.delenv(EnvVar.PREPROCESS_UNSANDBOXED.value, raising=False)
    reset_config()
    try:
        yield
    finally:
        reset_config()


def _write_config(root: Path, body: str) -> None:
    (root / PREPROCESS_CONFIG_FILENAME).write_text(body, encoding="utf-8")


# --------------------------------------------------------------------------
# Rule resolution (D1/D2/D3) - exercised under the on-sandbox default mode.
# --------------------------------------------------------------------------


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


def test_omitted_timeout_defaults_to_bounded_ceiling(tmp_path: Path) -> None:
    """H1: a rule without timeout_s gets a finite default, never wait-forever."""
    _write_config(
        tmp_path,
        """
        version = 1

        [[rule]]
        pattern = "*.pdf"
        command = "extract {path}"
        """,
    )
    rule = load_preprocess_rules(tmp_path).match("a.pdf")
    assert rule is not None
    assert rule.timeout_s is not None
    assert rule.timeout_s == 120.0


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


# --------------------------------------------------------------------------
# Tri-state mode enforcement (ADR D7/D8): kill switch and unsandboxed hatch.
# --------------------------------------------------------------------------


def test_rules_resolve_for_any_root_with_no_trust(tmp_path: Path) -> None:
    """default: rules resolve for any root - no trust record is consulted."""
    _write_config(
        tmp_path,
        """
        [[rule]]
        pattern = "*.pdf"
        command = "extract {path}"
        """,
    )
    # No trust act, no status-dir sidecar - the rules still resolve because
    # containment (the sandbox), not consent, is the security boundary.
    config = load_preprocess_rules(tmp_path)
    assert config.match("docs/a.pdf") is not None
    assert [r.command for r in config.rules] == ["extract {path}"]


def test_off_mode_yields_empty_with_debug_log(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """off is the kill switch: a present config loads zero rules."""
    _write_config(
        tmp_path,
        """
        [[rule]]
        pattern = "*.pdf"
        command = "extract {path}"
        """,
    )
    monkeypatch.setenv(EnvVar.PREPROCESS.value, "off")
    reset_config()
    with caplog.at_level("DEBUG"):
        config = load_preprocess_rules(tmp_path)
    assert config.rules == []
    assert any("'off'" in rec.message for rec in caplog.records)


def test_unsandboxed_mode_resolves_rules(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """unsandboxed resolves a root's rules (the sandbox is bypassed downstream)."""
    _write_config(
        tmp_path,
        """
        [[rule]]
        pattern = "*.pdf"
        command = "extract {path}"
        """,
    )
    monkeypatch.setenv(EnvVar.PREPROCESS_UNSANDBOXED.value, "1")
    reset_config()
    config = load_preprocess_rules(tmp_path)
    assert config.match("a.pdf") is not None


def test_off_wins_over_unsandboxed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The kill switch takes precedence when both env vars are set."""
    _write_config(
        tmp_path,
        """
        [[rule]]
        pattern = "*.pdf"
        command = "extract {path}"
        """,
    )
    monkeypatch.setenv(EnvVar.PREPROCESS_UNSANDBOXED.value, "1")
    monkeypatch.setenv(EnvVar.PREPROCESS.value, "off")
    reset_config()
    assert load_preprocess_rules(tmp_path).rules == []


def test_strict_bypasses_off_kill_switch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """strict validates the config regardless of the host's mode (off gate)."""
    _write_config(
        tmp_path,
        """
        [[rule]]
        pattern = "*.pdf"
        command = "extract {path}"
        """,
    )
    monkeypatch.setenv(EnvVar.PREPROCESS.value, "off")
    reset_config()
    # Non-strict honours the kill switch; strict bypasses it (preprocess check).
    assert load_preprocess_rules(tmp_path).rules == []
    assert len(load_preprocess_rules(tmp_path, strict=True).rules) == 1

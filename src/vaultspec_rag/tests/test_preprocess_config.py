"""Unit tests for preprocess rule config loading and the TOFU trust gate (no GPU).

Exercises two layers over real ``.vaultragpreprocess.toml`` fixtures written to
a tmp project root:

- Rule resolution (D1/D2/D3): deterministic ordering, ignore-style matching,
  the command/entry_point constraint, and the degrade-vs-strict error policy.
- The tri-state preprocess mode and per-root trust-on-first-use store
  (index-drift-hardening ADR D4/D5/D6): ``off`` loads nothing, ``trust_all``
  loads without a record, ``default`` loads only for a trusted resolved-rule-set
  hash, the hash is stable across benign edits and changes on command edits, and
  a corrupt store degrades to untrusted.

Every test isolates ``VAULTSPEC_RAG_STATUS_DIR`` to a tmp path (the trust store
writes there) via the autouse fixture, which also defaults the mode to
``trust_all`` so the rule-resolution tests exercise parsing without threading
trust plumbing. The mode/trust tests override the env explicitly.
"""

import json
from collections.abc import Iterator
from pathlib import Path

import pytest

from ..config import EnvVar, reset_config
from ..indexer import _preprocess_trust
from ..indexer._preprocess_config import (
    PREPROCESS_CONFIG_FILENAME,
    PreprocessConfig,
    PreprocessConfigError,
    load_preprocess_rules,
)

pytestmark = [pytest.mark.unit]


@pytest.fixture(autouse=True)
def _isolate_status_dir_and_trust_all(  # pyright: ignore[reportUnusedFunction]
    tmp_path_factory: pytest.TempPathFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[None]:
    """Isolate the trust store to a tmp status dir and default to trust-all.

    The trust store lives under ``status_dir``; pointing it at a per-test tmp
    dir keeps a test from touching the real machine store. Defaulting the mode
    to ``trust_all`` lets the rule-resolution tests load rules without recording
    trust first; the mode/trust tests override these env vars themselves.
    """
    status = tmp_path_factory.mktemp("status")
    monkeypatch.setenv(EnvVar.STATUS_DIR.value, str(status))
    monkeypatch.setenv(EnvVar.PREPROCESS_TRUST_ALL.value, "1")
    reset_config()
    try:
        yield
    finally:
        reset_config()


def _write_config(root: Path, body: str) -> None:
    (root / PREPROCESS_CONFIG_FILENAME).write_text(body, encoding="utf-8")


def _default_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    """Switch the resolved preprocess mode to the trust-gated default."""
    monkeypatch.delenv(EnvVar.PREPROCESS_TRUST_ALL.value, raising=False)
    monkeypatch.delenv(EnvVar.PREPROCESS.value, raising=False)
    reset_config()


def _resolved_hash(root: Path) -> str:
    """Return the hash of a root's resolved rule set (strict bypasses the gate)."""
    return _preprocess_trust.hash_rule_set(
        load_preprocess_rules(root, strict=True).rules
    )


# --------------------------------------------------------------------------
# Rule resolution (D1/D2/D3) - exercised under the autouse trust-all mode.
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
# Tri-state mode enforcement (ADR D4/D6).
# --------------------------------------------------------------------------


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
    monkeypatch.delenv(EnvVar.PREPROCESS_TRUST_ALL.value, raising=False)
    monkeypatch.setenv(EnvVar.PREPROCESS.value, "off")
    reset_config()
    with caplog.at_level("DEBUG"):
        config = load_preprocess_rules(tmp_path)
    assert config.rules == []
    assert any("'off'" in rec.message for rec in caplog.records)


def test_off_wins_over_trust_all(
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
    monkeypatch.setenv(EnvVar.PREPROCESS_TRUST_ALL.value, "1")
    monkeypatch.setenv(EnvVar.PREPROCESS.value, "off")
    reset_config()
    assert load_preprocess_rules(tmp_path).rules == []


def test_trust_all_loads_without_record_and_warns(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """trust_all runs every root's rules without a trust record, loudly."""
    _write_config(
        tmp_path,
        """
        [[rule]]
        pattern = "*.pdf"
        command = "extract {path}"
        """,
    )
    # Autouse fixture already selected trust_all mode.
    assert _preprocess_trust.read_trust(tmp_path) is None
    with caplog.at_level("WARNING"):
        config = load_preprocess_rules(tmp_path)
    assert config.match("a.pdf") is not None
    assert any("trust_all" in rec.message for rec in caplog.records)


def test_default_untrusted_yields_empty_with_actionable_warning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """default + no trust record: rules skipped with a verb-naming warning."""
    _write_config(
        tmp_path,
        """
        [[rule]]
        pattern = "*.pdf"
        command = "extract {path}"
        """,
    )
    _default_mode(monkeypatch)
    with caplog.at_level("WARNING"):
        config = load_preprocess_rules(tmp_path)
    assert config.rules == []
    joined = "\n".join(rec.message for rec in caplog.records)
    assert "preprocess trust" in joined
    assert "1 preprocess rule" in joined


def test_default_trusted_loads(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """default: a matching trust record admits the resolved rules."""
    _write_config(
        tmp_path,
        """
        [[rule]]
        pattern = "*.pdf"
        command = "extract {path}"
        """,
    )
    _preprocess_trust.record_trust(
        tmp_path,
        rule_set_hash=_resolved_hash(tmp_path),
        trusted_at="2026-07-13T00:00:00",
    )
    _default_mode(monkeypatch)
    config = load_preprocess_rules(tmp_path)
    assert config.match("docs/a.pdf") is not None


def test_command_edit_reverts_trusted_root_to_untrusted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A command change produces a new hash, so a stale record no longer matches."""
    _write_config(
        tmp_path,
        """
        [[rule]]
        pattern = "*.pdf"
        command = "extract {path}"
        """,
    )
    _preprocess_trust.record_trust(tmp_path, rule_set_hash=_resolved_hash(tmp_path))
    _default_mode(monkeypatch)
    assert load_preprocess_rules(tmp_path).match("a.pdf") is not None

    # Edit the command: the old trust record is now stale.
    _write_config(
        tmp_path,
        """
        [[rule]]
        pattern = "*.pdf"
        command = "malicious {path}"
        """,
    )
    reset_config()
    assert load_preprocess_rules(tmp_path).rules == []


# --------------------------------------------------------------------------
# Rule-set hashing (ADR D5).
# --------------------------------------------------------------------------


def test_hash_stable_across_benign_edits(tmp_path: Path) -> None:
    """A comment/whitespace edit re-resolves to the same rule-set hash."""
    _write_config(
        tmp_path,
        """
        [[rule]]
        pattern = "*.pdf"
        command = "extract {path}"
        priority = 10
        """,
    )
    before = _resolved_hash(tmp_path)
    _write_config(
        tmp_path,
        """
        # a freshly added explanatory comment

        [[rule]]
        pattern   = "*.pdf"
        command   = "extract {path}"
        priority  = 10
        """,
    )
    assert _resolved_hash(tmp_path) == before


def test_hash_changes_on_command_edit(tmp_path: Path) -> None:
    _write_config(
        tmp_path,
        """
        [[rule]]
        pattern = "*.pdf"
        command = "extract {path}"
        """,
    )
    before = _resolved_hash(tmp_path)
    _write_config(
        tmp_path,
        """
        [[rule]]
        pattern = "*.pdf"
        command = "different {path}"
        """,
    )
    assert _resolved_hash(tmp_path) != before


def test_hash_changes_on_options_edit(tmp_path: Path) -> None:
    _write_config(
        tmp_path,
        """
        [[rule]]
        pattern = "*.xlsx"
        command = "xlsx {path}"

        [rule.options]
        sheet_limit = 5
        """,
    )
    before = _resolved_hash(tmp_path)
    _write_config(
        tmp_path,
        """
        [[rule]]
        pattern = "*.xlsx"
        command = "xlsx {path}"

        [rule.options]
        sheet_limit = 9
        """,
    )
    assert _resolved_hash(tmp_path) != before


# --------------------------------------------------------------------------
# Trust store durability and degradation (ADR D5).
# --------------------------------------------------------------------------


def test_corrupt_store_degrades_to_untrusted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """A corrupt trust store reads as empty (untrusted), never raises."""
    _write_config(
        tmp_path,
        """
        [[rule]]
        pattern = "*.pdf"
        command = "extract {path}"
        """,
    )
    # Trust the root, then clobber the store with garbage.
    _preprocess_trust.record_trust(tmp_path, rule_set_hash=_resolved_hash(tmp_path))
    _preprocess_trust.trust_store_path().write_text("{ not json", encoding="utf-8")
    _default_mode(monkeypatch)
    with caplog.at_level("WARNING"):
        config = load_preprocess_rules(tmp_path)
    assert config.rules == []
    assert _preprocess_trust.load_trust_store() == {}


def test_trust_record_round_trips_and_is_removable(tmp_path: Path) -> None:
    _write_config(
        tmp_path,
        """
        [[rule]]
        pattern = "*.pdf"
        command = "extract {path}"
        """,
    )
    rule_hash = _resolved_hash(tmp_path)
    record = _preprocess_trust.record_trust(
        tmp_path, rule_set_hash=rule_hash, trusted_at="2026-07-13T12:00:00"
    )
    assert record.rule_set_hash == rule_hash
    assert record.root == str(tmp_path.resolve())

    reread = _preprocess_trust.read_trust(tmp_path)
    assert reread is not None
    assert reread.rule_set_hash == rule_hash
    assert reread.trusted_at == "2026-07-13T12:00:00"
    assert _preprocess_trust.is_trusted(tmp_path, rule_hash)
    assert not _preprocess_trust.is_trusted(tmp_path, "deadbeef")

    assert _preprocess_trust.remove_trust(tmp_path) is True
    assert _preprocess_trust.read_trust(tmp_path) is None
    assert _preprocess_trust.remove_trust(tmp_path) is False


def test_trust_store_isolates_under_status_dir(tmp_path: Path) -> None:
    """The store lands under the isolated status dir, never in the repo."""
    _write_config(
        tmp_path,
        """
        [[rule]]
        pattern = "*.pdf"
        command = "extract {path}"
        """,
    )
    _preprocess_trust.record_trust(tmp_path, rule_set_hash=_resolved_hash(tmp_path))
    store = _preprocess_trust.trust_store_path()
    assert store.is_file()
    # Never written inside the (attacker-controlled) project root.
    assert tmp_path.resolve() not in store.resolve().parents
    assert not (tmp_path / "preprocess-trust.json").exists()
    payload = json.loads(store.read_text(encoding="utf-8"))
    assert payload["version"] == 1
    assert len(payload["roots"]) == 1

"""Unit tests for VaultSpecConfigWrapper backend-selection and related keys.

Split out of ``test_config.py`` (the module-length gate), which the memory
budget, CUDA ceiling, and resilience tests filled past the limit. This half
covers backend selection (the supervised Qdrant server vs. the on-disk
store), code-noise defaults, index reuse, malformed-value rejection,
preprocessing, storage-maintenance grace windows, and the model-repo
inventory - none of which touch a memory budget or a CUDA ceiling, so it
stands alone.
"""

from __future__ import annotations

import os

import pytest
from vaultspec_core.env_values import FALSE_TOKENS, TRUE_TOKENS

from ..config._schema import ENV_OVERRIDE_MAP, SETTING_BOUNDS
from ..config._settings import (
    VaultSpecConfigWrapper,
    configured_model_repos,
    get_config,
    reset_config,
)
from ..config._types import EnvVar
from ._scaffold import restore_env, set_env

pytestmark = [pytest.mark.unit]


def _clear_server_mode_env() -> dict[EnvVar, str | None]:
    """Snapshot and clear the two effective-server-mode env knobs.

    The test host may carry an ambient ``VAULTSPEC_RAG_QDRANT_SERVER``
    or ``VAULTSPEC_RAG_LOCAL_ONLY`` (the lifespan publishes server-mode
    state into the environment for the daemon's lifetime), so the
    default-resolution assertions must run from a known-clean slate.
    """
    saved: dict[EnvVar, str | None] = {}
    for var in (EnvVar.QDRANT_SERVER, EnvVar.LOCAL_ONLY):
        saved[var] = os.environ.pop(var.value, None)
    return saved


def _restore_server_mode_env(saved: dict[EnvVar, str | None]) -> None:
    for var, prev in saved.items():
        restore_env(var, prev)


def test_qdrant_server_default_is_true() -> None:
    saved = _clear_server_mode_env()
    try:
        reset_config()
        cfg = get_config()
        value = cfg.qdrant_server
        assert value is True
        assert isinstance(value, bool)
    finally:
        _restore_server_mode_env(saved)
        reset_config()


def test_local_only_default_is_false() -> None:
    saved = _clear_server_mode_env()
    try:
        reset_config()
        cfg = get_config()
        value = cfg.local_only
        assert value is False
        assert isinstance(value, bool)
    finally:
        _restore_server_mode_env(saved)
        reset_config()


def test_effective_server_mode_default_is_true() -> None:
    saved = _clear_server_mode_env()
    try:
        reset_config()
        cfg = get_config()
        assert cfg.effective_server_mode() is True
    finally:
        _restore_server_mode_env(saved)
        reset_config()


@pytest.mark.parametrize(
    "raw",
    ["1", "true", "TRUE", "yes"],
    ids=["one", "true-lower", "true-upper", "yes"],
)
def test_local_only_env_flips_effective_mode_off(raw: str) -> None:
    saved = _clear_server_mode_env()
    os.environ[EnvVar.LOCAL_ONLY.value] = raw
    try:
        reset_config()
        cfg = get_config()
        # local-only deterministically wins over the server default:
        # qdrant_server stays its default-true while effective mode is
        # forced off.
        assert cfg.qdrant_server is True
        assert cfg.local_only is True
        assert cfg.effective_server_mode() is False
    finally:
        _restore_server_mode_env(saved)
        reset_config()


@pytest.mark.parametrize("raw", ["0", "false", "no", ""])
def test_local_only_env_falsey_keeps_server_mode(raw: str) -> None:
    saved = _clear_server_mode_env()
    os.environ[EnvVar.LOCAL_ONLY.value] = raw
    try:
        reset_config()
        cfg = get_config()
        assert cfg.local_only is False
        assert cfg.effective_server_mode() is True
    finally:
        _restore_server_mode_env(saved)
        reset_config()


def test_qdrant_server_env_off_disables_effective_mode() -> None:
    saved = _clear_server_mode_env()
    os.environ[EnvVar.QDRANT_SERVER.value] = "0"
    try:
        reset_config()
        cfg = get_config()
        # The redundant server-mode env knob set off also disables
        # effective mode, independently of local_only.
        assert cfg.qdrant_server is False
        assert cfg.local_only is False
        assert cfg.effective_server_mode() is False
    finally:
        _restore_server_mode_env(saved)
        reset_config()


def test_local_only_wins_even_when_server_env_on() -> None:
    saved = _clear_server_mode_env()
    os.environ[EnvVar.QDRANT_SERVER.value] = "1"
    os.environ[EnvVar.LOCAL_ONLY.value] = "1"
    try:
        reset_config()
        cfg = get_config()
        assert cfg.qdrant_server is True
        assert cfg.local_only is True
        assert cfg.effective_server_mode() is False
    finally:
        _restore_server_mode_env(saved)
        reset_config()


def test_code_noise_profile_defaults() -> None:
    cfg = get_config()
    assert cfg.code_noise_hide_domains == frozenset({"worktree", "generated"})
    assert cfg.code_noise_demote_domains == frozenset(
        {"tests", "docs", "locale", "vendored"}
    )
    assert cfg.code_noise_demote_penalty == pytest.approx(0.3)
    assert cfg.dedup_locales_default is True


def test_parse_domain_set_drops_unknown_and_prod() -> None:
    from ..config._settings import VaultSpecConfigWrapper as W

    # ``prod`` is never noise; ``bogus`` is not a domain - both dropped.
    assert W._parse_domain_set("tests, prod, bogus, locale") == frozenset(
        {"tests", "locale"}
    )
    assert W._parse_domain_set("") == frozenset()
    assert W._parse_domain_set(None) == frozenset()


def test_hide_wins_over_demote() -> None:
    prev_hide = set_env(EnvVar.CODE_NOISE_HIDE_DOMAINS, "worktree,tests")
    prev_demote = set_env(EnvVar.CODE_NOISE_DEMOTE_DOMAINS, "tests,docs")
    try:
        reset_config()
        cfg = get_config()
        # ``tests`` is in both; hide takes it, so demote no longer lists it.
        assert "tests" in cfg.code_noise_hide_domains
        assert "tests" not in cfg.code_noise_demote_domains
        assert cfg.code_noise_demote_domains == frozenset({"docs"})
    finally:
        restore_env(EnvVar.CODE_NOISE_HIDE_DOMAINS, prev_hide)
        restore_env(EnvVar.CODE_NOISE_DEMOTE_DOMAINS, prev_demote)
        reset_config()


def test_code_noise_env_override_penalty_and_dedup() -> None:
    prev_pen = set_env(EnvVar.CODE_NOISE_DEMOTE_PENALTY, "0.5")
    prev_dedup = set_env(EnvVar.DEDUP_LOCALES_DEFAULT, "0")
    try:
        reset_config()
        cfg = get_config()
        assert cfg.code_noise_demote_penalty == pytest.approx(0.5)
        assert cfg.dedup_locales_default is False
    finally:
        restore_env(EnvVar.CODE_NOISE_DEMOTE_PENALTY, prev_pen)
        restore_env(EnvVar.DEDUP_LOCALES_DEFAULT, prev_dedup)
        reset_config()


def test_reranker_enabled_env_override() -> None:
    prev = set_env(EnvVar.RERANKER_ENABLED, "0")
    try:
        reset_config()
        assert get_config().reranker_enabled is False
    finally:
        restore_env(EnvVar.RERANKER_ENABLED, prev)
        reset_config()


def test_index_reuse_enabled_default() -> None:
    # Encode-seam vector reuse ships on: the fork-index GPU win is the default,
    # and the off-switch is the opt-out, not the opt-in.
    cfg = get_config()
    value = cfg.index_reuse_enabled
    assert value is True
    assert isinstance(value, bool)


@pytest.mark.parametrize(
    "raw",
    ["0", "false", "False", "no", "off"],
    ids=["zero", "false-lower", "false-title", "no", "off"],
)
def test_index_reuse_enabled_env_falsey(raw: str) -> None:
    # The off-switch parses off: a false word disables every donor lookup and
    # restores the encode-everything baseline in one flip. A blank value is
    # not one of them - it is unset, and covered by the test below.
    prev = set_env(EnvVar.INDEX_REUSE, raw)
    try:
        reset_config()
        cfg = get_config()
        value = cfg.index_reuse_enabled
        assert value is False
        assert isinstance(value, bool)
    finally:
        restore_env(EnvVar.INDEX_REUSE, prev)
        reset_config()


@pytest.mark.parametrize("raw", ["", "   "], ids=["empty", "whitespace"])
def test_index_reuse_enabled_env_blank_is_unset(raw: str) -> None:
    # A shell spells an unset variable blank whenever an expansion misses, so
    # blank falls through to the shipped default rather than reading as off.
    # Resolving it as off would silently disable the feature for anyone whose
    # deployment template exports a knob it has no value for.
    prev = set_env(EnvVar.INDEX_REUSE, raw)
    try:
        reset_config()
        assert get_config().index_reuse_enabled is True
    finally:
        restore_env(EnvVar.INDEX_REUSE, prev)
        reset_config()


@pytest.mark.parametrize(
    "raw",
    ["1", "true", "TRUE", "yes", "Yes"],
    ids=["one", "true-lower", "true-upper", "yes-lower", "yes-title"],
)
def test_index_reuse_enabled_env_truthy(raw: str) -> None:
    prev = set_env(EnvVar.INDEX_REUSE, raw)
    try:
        reset_config()
        cfg = get_config()
        value = cfg.index_reuse_enabled
        assert value is True
        assert isinstance(value, bool)
    finally:
        restore_env(EnvVar.INDEX_REUSE, prev)
        reset_config()


def test_index_reuse_enabled_not_gated_by_support_profile() -> None:
    # The indexing support profile shapes memory and support ceilings only;
    # selecting the lightweight profile must never flip the reuse knob off.
    try:
        cfg = get_config({"index_support_profile": "embedded-local"})
        assert cfg.index_support_profile == "embedded-local"
        assert cfg.index_reuse_enabled is True
    finally:
        reset_config()


def test_index_reuse_enabled_reset_config_picks_up_change() -> None:
    # reset_config clears the cached singleton so a fresh env value is served on
    # the next get_config(); this binds that the off-switch takes effect through
    # the same reset seam the other env-override knobs rely on.
    prev = set_env(EnvVar.INDEX_REUSE, "1")
    try:
        reset_config()
        first = get_config()
        assert first.index_reuse_enabled is True
        os.environ[EnvVar.INDEX_REUSE.value] = "0"
        reset_config()
        second = get_config()
        assert second is not first
        assert second.index_reuse_enabled is False
    finally:
        restore_env(EnvVar.INDEX_REUSE, prev)
        reset_config()


def test_malformed_numeric_env_is_rejected_at_construction_by_name() -> None:
    # The malformed value must not reach a caller as the shipped default, and
    # the message must be enough to fix the mistake without reading the source.
    # Mutation: returning the default instead of raising in _coerce_env's
    # except branch turns this into DID NOT RAISE.
    prev = set_env(EnvVar.CODE_NOISE_DEMOTE_PENALTY, "notanumber")
    try:
        reset_config()
        with pytest.raises(ValueError) as excinfo:
            get_config()
        message = str(excinfo.value)
        assert EnvVar.CODE_NOISE_DEMOTE_PENALTY.value in message
        assert "code_noise_demote_penalty" in message
        assert "notanumber" in message
        assert "finite non-negative number" in message
    finally:
        restore_env(EnvVar.CODE_NOISE_DEMOTE_PENALTY, prev)
        reset_config()


def test_negative_idle_ttl_is_rejected_while_zero_is_admitted() -> None:
    # Zero means "evict as soon as idle" and stays legal; a negative TTL is
    # meaningless and used to be returned verbatim. Mutation: widening the
    # service_idle_ttl_seconds bound below zero turns this into DID NOT RAISE.
    prev = set_env(EnvVar.SERVICE_IDLE_TTL_SECONDS, "0")
    try:
        reset_config()
        assert get_config().service_idle_ttl_seconds == 0

        os.environ[EnvVar.SERVICE_IDLE_TTL_SECONDS.value] = "-5"
        reset_config()
        with pytest.raises(ValueError, match="service_idle_ttl_seconds"):
            get_config()
    finally:
        restore_env(EnvVar.SERVICE_IDLE_TTL_SECONDS, prev)
        reset_config()


def test_construction_reports_every_unusable_setting_together() -> None:
    # Reporting only the first mistake makes an operator restart once per typo.
    # Mutation: raising problems[0] unconditionally drops the second name.
    prev_ttl = set_env(EnvVar.SERVICE_IDLE_TTL_SECONDS, "-5")
    prev_batch = set_env(EnvVar.EMBEDDING_BATCH_SIZE, "0")
    try:
        reset_config()
        with pytest.raises(ValueError) as excinfo:
            get_config()
        message = str(excinfo.value)
        assert "service_idle_ttl_seconds" in message
        assert "embedding_batch_size" in message
    finally:
        restore_env(EnvVar.SERVICE_IDLE_TTL_SECONDS, prev_ttl)
        restore_env(EnvVar.EMBEDDING_BATCH_SIZE, prev_batch)
        reset_config()


def test_every_ranged_setting_rejects_a_malformed_environment_value() -> None:
    # A sweep, so a knob added later cannot quietly opt out of coercion.
    # Mutation: returning the default instead of raising in _coerce_env's
    # except branch fails on the first key in the table.
    assert SETTING_BOUNDS, "expected the settings table to declare numeric ranges"
    for key, bound in SETTING_BOUNDS.items():
        env_var = ENV_OVERRIDE_MAP.get(key)
        assert env_var is not None, f"{key} declares a range but no env var"
        prev = set_env(env_var, "notavalue")
        try:
            reset_config()
            with pytest.raises(ValueError) as excinfo:
                get_config()
            message = str(excinfo.value)
            assert env_var.value in message, key
            assert bound.shape in message, key
        finally:
            restore_env(env_var, prev)
            reset_config()


def test_every_flag_rejects_an_unrecognised_token() -> None:
    # An unrecognised word used to read as false, so one typo silently turned a
    # feature off. Mutation: restoring membership in the truthy set as the whole
    # rule (unrecognised means false) turns this into DID NOT RAISE.
    defaults: dict[str, object] = VaultSpecConfigWrapper._RAG_DEFAULTS
    flags = [key for key, value in defaults.items() if isinstance(value, bool)]
    assert flags, "expected the settings table to carry boolean flags"
    for key in flags:
        env_var = ENV_OVERRIDE_MAP.get(key)
        assert env_var is not None, f"{key} is a flag with no env var"
        prev = set_env(env_var, "treu")
        try:
            reset_config()
            with pytest.raises(ValueError) as excinfo:
                get_config()
            assert env_var.value in str(excinfo.value), key
        finally:
            restore_env(env_var, prev)
            reset_config()


def test_document_chunk_ratio_resolves_through_the_canonical_map() -> None:
    prev = set_env(EnvVar.DOCUMENT_CHUNK_CHARS_PER_TOKEN, "4")
    try:
        reset_config()
        cfg = get_config()
        assert cfg.document_chunk_chars_per_token == 4
        assert cfg.document_chunk_chars == cfg.embedding_max_seq_length * 4
    finally:
        restore_env(EnvVar.DOCUMENT_CHUNK_CHARS_PER_TOKEN, prev)
        reset_config()


def test_document_chunk_overlap_stays_below_the_derived_budget() -> None:
    # The coupling no per-key range can express: an overlap at or above the
    # derived budget consumes a whole chunk and never advances the split.
    # Mutation: deleting the comparison in document_chunk_overlap_chars turns
    # the second half into DID NOT RAISE.
    prev = set_env(EnvVar.DOCUMENT_CHUNK_OVERLAP_CHARS, "512")
    try:
        reset_config()
        assert get_config().document_chunk_overlap_chars == 512

        os.environ[EnvVar.DOCUMENT_CHUNK_OVERLAP_CHARS.value] = "999999"
        reset_config()
        with pytest.raises(ValueError, match="smaller than the derived"):
            get_config()
    finally:
        restore_env(EnvVar.DOCUMENT_CHUNK_OVERLAP_CHARS, prev)
        reset_config()


def test_preprocess_kill_switch_beats_an_explicit_configured_mode() -> None:
    # Why preprocess_mode cannot be a plain map entry: the env var is a kill
    # switch, not a carrier of the setting's value, and it must win over an
    # explicit override that the generic path ranks ABOVE the environment.
    # Mutation: deleting the env check from the property returns "default".
    prev = set_env(EnvVar.PREPROCESS, "off")
    try:
        reset_config()
        assert get_config({"preprocess_mode": "default"}).preprocess_mode == "off"
    finally:
        restore_env(EnvVar.PREPROCESS, prev)
        reset_config()


@pytest.mark.parametrize("word", sorted(FALSE_TOKENS))
def test_every_false_word_kills_preprocessing(word: str) -> None:
    # The switch used to honour "off" alone, so an operator who typed 0 or
    # false got preprocessing anyway and nothing said so. Every word the
    # shared vocabulary spells off now means off.
    prev = set_env(EnvVar.PREPROCESS, word)
    try:
        reset_config()
        assert get_config().preprocess_mode == "off"
    finally:
        restore_env(EnvVar.PREPROCESS, prev)
        reset_config()


@pytest.mark.parametrize("word", [*sorted(TRUE_TOKENS), "", "   "])
def test_a_true_or_blank_switch_leaves_preprocessing_to_the_rungs_below(
    word: str,
) -> None:
    # A true word asks for the shipped behaviour, and blank asks for nothing
    # at all; neither may silence a root's rules.
    prev = set_env(EnvVar.PREPROCESS, word)
    try:
        reset_config()
        assert get_config().preprocess_mode == "default"
    finally:
        restore_env(EnvVar.PREPROCESS, prev)
        reset_config()


def test_an_unrecognised_switch_word_is_refused_with_the_other_settings() -> None:
    # Guessing which way an operator meant a kill switch is the guess that
    # matters most, so it is refused at construction with everything else
    # that is unusable rather than at the first document of a run.
    prev = set_env(EnvVar.PREPROCESS, "offf")
    try:
        reset_config()
        with pytest.raises(ValueError, match=EnvVar.PREPROCESS.value):
            get_config()
    finally:
        restore_env(EnvVar.PREPROCESS, prev)
        reset_config()


_GRACE_WINDOW_VARS = (
    EnvVar.STORAGE_AUTOPRUNE_GRACE_HOURS,
    EnvVar.STORAGE_AUTOPRUNE_GRACE_HOURS_DATA,
    EnvVar.STORAGE_AUTOPRUNE_GRACE_HOURS_EPHEMERAL,
)


@pytest.mark.parametrize("env_var", _GRACE_WINDOW_VARS)
def test_a_grace_window_refuses_a_same_cycle_value(env_var: EnvVar) -> None:
    """No grace window may be set short enough to act on a first sighting.

    A window is the interval an observation has to survive, so zero makes it
    no observation at all: the cycle that first sees a namespace stamps its
    clock, finds no elapsed time short of the window, and is cleared to
    destroy on that single scan. The floor is one maintenance interval at the
    shipped cadence, so the earliest a namespace can be reclaimed is the
    cycle after the one that first observed it.

    Mutation this catches: binding any of the three back to the non-negative
    bound, which turns each rejection below into DID NOT RAISE.
    """
    for raw in ("0", "0.5"):
        prev = set_env(env_var, raw)
        try:
            reset_config()
            with pytest.raises(ValueError) as excinfo:
                get_config()
            assert env_var.value in str(excinfo.value)
        finally:
            restore_env(env_var, prev)
            reset_config()


def test_the_ephemeral_idle_switch_still_accepts_its_disable_value() -> None:
    """The knob named almost identically to a window means the opposite at zero.

    Zero on the idle tier turns that tier off; zero on a grace window would
    have made its tier maximally aggressive. Asserted alongside the rejections
    above because the risk is not that either value is wrong on its own - it
    is that the two names are one word apart and an operator, or a later
    change to the bounds table, treats them as the same kind of number.
    """
    prev = set_env(EnvVar.STORAGE_AUTOPRUNE_EPHEMERAL_IDLE_HOURS, "0")
    try:
        reset_config()
        assert get_config().storage_autoprune_ephemeral_idle_hours == 0.0
    finally:
        restore_env(EnvVar.STORAGE_AUTOPRUNE_EPHEMERAL_IDLE_HOURS, prev)
        reset_config()


class TestConfiguredModelRepos:
    """``configured_model_repos`` is the single source every provisioning,

    warmup, and readiness consumer reads its required-model inventory from,
    so gating it here is what keeps a dense-only install from ever being
    asked to provision the SPARSEUP repo.
    """

    def test_sparse_enabled_includes_all_three_repos(self) -> None:
        prev = set_env(EnvVar.SPARSE_ENABLED, "1")
        try:
            reset_config()
            cfg = get_config()
            assert cfg.sparse_enabled is True
            repos = configured_model_repos()
            labels = [label for label, _repo in repos]
            values = [repo for _label, repo in repos]
            assert labels == [
                "Dense (Qwen3)",
                "Sparse (SPARSEUP)",
                "Reranker (CrossEncoder)",
            ]
            assert str(cfg.sparse_model) in values
            assert str(cfg.embedding_model) in values
            assert str(cfg.reranker_model) in values
        finally:
            restore_env(EnvVar.SPARSE_ENABLED, prev)
            reset_config()

    def test_sparse_disabled_excludes_only_the_sparse_repo(self) -> None:
        prev = set_env(EnvVar.SPARSE_ENABLED, "0")
        try:
            reset_config()
            cfg = get_config()
            assert cfg.sparse_enabled is False
            repos = configured_model_repos()
            labels = [label for label, _repo in repos]
            values = [repo for _label, repo in repos]
            # The sparse label and repo are gone entirely, not merely blanked -
            # a dense-only inventory must never mention the sparse repo at all.
            assert labels == ["Dense (Qwen3)", "Reranker (CrossEncoder)"]
            assert str(cfg.sparse_model) not in values
            assert str(cfg.embedding_model) in values
            assert str(cfg.reranker_model) in values
        finally:
            restore_env(EnvVar.SPARSE_ENABLED, prev)
            reset_config()

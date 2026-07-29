"""Structural guards keeping one logging backend for the whole package.

The defect these exist to prevent is not a crash. It is a producer that
writes into the managed log without passing through the configured root
handler: its records arrive unformatted and unfiltered, and in the worst
case unterminated, where they absorb the record written after them. Every
such producer looks harmless at its own call site, so the invariant has to
be asserted over the tree rather than reviewed one diff at a time.
"""

from __future__ import annotations

import ast

import pytest

from ._process_probe_guard_helpers import _PACKAGE_ROOT, every_production_file

pytestmark = [pytest.mark.unit]

#: The module that owns logging configuration. Everything the guards below
#: forbid is legitimate here and nowhere else.
_LOGGING_OWNER = "logging_config.py"

#: Methods that render a progress bar unless told not to.
_ENCODE_METHODS = frozenset(
    {"encode", "encode_document", "encode_query", "predict"},
)

#: Receiver names that denote a model rather than, say, a string being
#: encoded to bytes.
_MODEL_RECEIVER_TOKENS = ("model", "reranker", "encoder")

#: The package's own embedding facade. Its methods wrap the library calls
#: below and are scanned where they are defined, so requiring the keyword
#: again at every call into the facade would demand an argument its
#: signature does not accept.
_FACADE_RECEIVERS = frozenset({"model"})

#: Handler classes that open their own destination and so would write to a
#: file nothing else in the package rotates, bounds, or reads.
_SELF_OWNED_HANDLERS = frozenset(
    {
        "FileHandler",
        "RotatingFileHandler",
        "TimedRotatingFileHandler",
        "WatchedFileHandler",
    },
)

#: Entry points that install a whole logging configuration at once.
_CONFIGURATION_CALLS = frozenset({"basicConfig", "dictConfig", "fileConfig"})

#: Receivers those entry points are reached through: ``logging.basicConfig``
#: and ``logging.config.dictConfig``. Matching the receiver keeps an
#: unrelated ``basicConfig`` on some other object out of the result.
_CONFIGURATION_RECEIVERS = frozenset({"logging", "config"})


def _receiver_name(node: ast.expr) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Call):
        # An accessor rather than a stored handle: the model reached through
        # ``self._require_sparse_model()`` is as much a library call as one
        # reached through an attribute, and hiding it behind a call is
        # exactly how the last unguarded site escaped review.
        return _receiver_name(node.func)
    return ""


def _is_model_call(node: ast.Call) -> bool:
    func = node.func
    if not isinstance(func, ast.Attribute) or func.attr not in _ENCODE_METHODS:
        return False
    receiver = _receiver_name(func.value)
    if receiver in _FACADE_RECEIVERS:
        return False
    lowered = receiver.lower()
    return any(token in lowered for token in _MODEL_RECEIVER_TOKENS)


def _disables_progress(node: ast.Call) -> bool:
    for keyword in node.keywords:
        if keyword.arg != "show_progress_bar":
            continue
        return isinstance(keyword.value, ast.Constant) and keyword.value.value is False
    return False


def _calls_in_production() -> list[tuple[str, int, ast.Call]]:
    calls: list[tuple[str, int, ast.Call]] = []
    for path in every_production_file():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover - parsed elsewhere
            continue
        relative = path.relative_to(_PACKAGE_ROOT).as_posix()
        calls.extend(
            (relative, node.lineno, node)
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
        )
    return calls


def test_model_calls_never_draw_progress_into_the_log() -> None:
    """No encode or predict may leave progress rendering to a default.

    A progress bar redraws its line with a carriage return instead of ending
    it, so drawn into a file it produces a record nothing terminates. The
    default is worse than opt-in: the library turns the bar on when the
    effective log level is INFO, so raising verbosity silently changes how
    the log file is framed.
    """
    offenders = [
        f"{relative}:{line}"
        for relative, line, node in _calls_in_production()
        if _is_model_call(node) and not _disables_progress(node)
    ]

    assert not offenders, (
        f"model calls must pass show_progress_bar=False explicitly: {sorted(offenders)}"
    )


def test_only_the_logging_owner_installs_a_logging_configuration() -> None:
    """One module configures logging; a second would silently win or lose."""
    offenders = [
        f"{relative}:{line}"
        for relative, line, node in _calls_in_production()
        if relative != _LOGGING_OWNER
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in _CONFIGURATION_CALLS
        and _receiver_name(node.func.value) in _CONFIGURATION_RECEIVERS
    ]

    assert not offenders, (
        f"logging is configured outside {_LOGGING_OWNER}: {sorted(offenders)}"
    )


def test_no_module_opens_its_own_log_file() -> None:
    """Every managed byte reaches disk through the one rotating sink.

    A handler that opens its own file writes somewhere nothing rotates,
    bounds, or serves to an operator, so it grows without limit and is
    invisible to every reader the service ships.
    """
    offenders = [
        f"{relative}:{line}"
        for relative, line, node in _calls_in_production()
        if _receiver_name(node.func) in _SELF_OWNED_HANDLERS
    ]

    assert not offenders, (
        f"log file opened outside the managed sink: {sorted(offenders)}"
    )

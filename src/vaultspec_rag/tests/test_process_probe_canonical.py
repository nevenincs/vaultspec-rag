"""``_process_probe`` is the only home for OS process inspection.

Consolidating the duplicates was the easy half; keeping them consolidated is
this file's job. Before the merge there were four independent liveness
implementations, three ``ctypes`` declarations of the same kernel32 calls, two
start-time comparisons with different tolerances, and two image checks using
different mechanisms - and they drifted exactly as duplicated behaviour does.
A blanket ``suppress(OSError)`` that hid a refused kill was fixed in the CLI
copy while the identical swallow survived in the reap copy, so ``server stop``
reported success over a daemon it had no permission to kill.

A source scan is the right shape for that guard: the failure mode is a NEW
copy appearing in a module that never imported the canonical one, which no
behavioural test of the existing call sites can see.
"""

from __future__ import annotations

import ast
import hashlib
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import ClassVar
from unittest.mock import patch

import pytest

from .. import _process_probe
from .._operator_commands import index_command

pytestmark = [pytest.mark.unit]

_PACKAGE_ROOT = Path(_process_probe.__file__).parent
_CANONICAL = Path(_process_probe.__file__).name

#: Modules allowed to call a raw process primitive, each for a reason the
#: canonical module does not serve. Anything not listed here must import from
#: ``_process_probe`` instead of re-deriving the primitive.
_ALLOWED: dict[str, str] = {
    # Self-memory sampling. `psutil.Process(os.getpid()).memory_info()` asks
    # about THIS process's RSS, which is a memory concern, not process
    # identity: no pid to confuse, no liveness to get wrong.
    "memory_probe.py": "samples this process's own RSS",
    "jobs.py": "samples this process's own RSS",
    # Holds SYNCHRONIZE handles open to WAIT on ancestor death, and walks a
    # toolhelp snapshot to find them. That is handle lifetime management, not
    # a point-in-time probe, and it needs its own `use_last_error` WinDLL.
    "_stdio_lifetime.py": "holds waitable ancestor handles",
    # Windows Job Object management for the managed child; kernel32 here is
    # about job assignment, not about inspecting a pid.
    "_supervise.py": "manages a Job Object",
}


def _production_sources() -> list[Path]:
    """Every production module: the package minus tests and the canonical home."""
    return [
        path
        for path in _PACKAGE_ROOT.rglob("*.py")
        if "tests" not in path.parts and path.name != _CANONICAL
    ]


def _every_production_file() -> list[Path]:
    """Every production module, including the canonical home.

    ``_production_sources`` omits the canonical home, which is right for a
    "does anyone else do this" scan and wrong for building an index of who
    reads what: a file left out of that index reads as nobody.
    """
    return [path for path in _PACKAGE_ROOT.rglob("*.py") if "tests" not in path.parts]


def _module_name(path: Path) -> str:
    """Return the dotted module name for *path*, dropping a trailing package part."""
    parts = list(path.relative_to(_PACKAGE_ROOT).with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join([_PACKAGE_ROOT.name, *parts])


def _absolute_import(node: ast.ImportFrom, module: str, is_package: bool) -> str:
    """Resolve a possibly-relative ``ImportFrom`` to an absolute module name."""
    base = node.module or ""
    if not node.level:
        return base
    parts = module.split(".")
    if not is_package:
        parts = parts[:-1]
    above = node.level - 1
    if above:
        parts = parts[:-above] if above <= len(parts) else []
    return ".".join([*parts, base]) if base else ".".join(parts)


def _offenders(predicate) -> list[str]:
    found: list[str] = []
    for path in _production_sources():
        if path.name in _ALLOWED:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and predicate(node):
                rel = path.relative_to(_PACKAGE_ROOT).as_posix()
                found.append(f"{rel}:{node.lineno}")
    return found


def _is_attr_call(node: ast.Call, owner: str, attr: str) -> bool:
    func = node.func
    return (
        isinstance(func, ast.Attribute)
        and func.attr == attr
        and isinstance(func.value, ast.Name)
        and func.value.id == owner
    )


def test_no_module_signals_a_process_directly() -> None:
    # `os.kill` is how a refused kill gets swallowed. Routing every signal
    # through `send_signal` is what makes PermissionError a reportable outcome
    # instead of a silent pass, so a new raw call re-opens the original defect.
    offenders = _offenders(lambda n: _is_attr_call(n, "os", "kill"))
    assert not offenders, (
        f"raw os.kill outside _process_probe at {offenders}; "
        "use _process_probe.send_signal so a refused signal is reported"
    )


def test_no_module_builds_its_own_psutil_process_probe() -> None:
    offenders = _offenders(
        lambda n: (
            _is_attr_call(n, "psutil", "Process")
            or _is_attr_call(n, "psutil", "process_iter")
        )
    )
    assert not offenders, (
        f"raw psutil process inspection outside _process_probe at {offenders}; "
        "use pid_start_time / pid_is_zombie / iter_process_info"
    )


def test_no_module_redeclares_the_kernel32_process_calls() -> None:
    # Three modules once declared OpenProcess independently and only one got
    # the pointer-sized HANDLE restype right, so the others truncated it.
    offenders = _offenders(
        lambda n: (
            isinstance(n.func, ast.Attribute)
            and n.func.attr
            in {"OpenProcess", "GetExitCodeProcess", "QueryFullProcessImageNameW"}
        )
    )
    assert not offenders, (
        f"direct kernel32 process calls outside _process_probe at {offenders}; "
        "use win_kernel32() so the HANDLE widths are declared once"
    )


def test_allowlist_names_only_modules_that_exist() -> None:
    # An allowlist entry for a deleted or renamed module silently widens the
    # guard: the name stops matching anything and a real offender could take
    # its place unnoticed.
    names = {path.name for path in _production_sources()}
    stale = sorted(set(_ALLOWED) - names)
    assert not stale, f"allowlist names modules that no longer exist: {stale}"


class TestRuntimeIdentityHasOneHome:
    """The interpreter/process description resolves to ``_runtime_identity``.

    Four modules derived these fields independently - the job runtime context,
    the job-manager snapshot, the discovery pointer, and the health payload -
    and all four read ``VIRTUAL_ENV`` as a bare string despite ``EnvVar``
    declaring itself "the single source of truth" for env-var names. Four
    copies means a field added to one is missing from three.
    """

    def test_no_module_reads_virtual_env_as_a_bare_string(self) -> None:
        # EnvVar owns env-var names. A bare literal is how the four copies
        # drifted from the enum in the first place.
        offenders: list[str] = []
        for path in _production_sources():
            if path.name in {"config.py", "_runtime_identity.py"}:
                continue
            for number, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), start=1
            ):
                if '"VIRTUAL_ENV"' in line or "'VIRTUAL_ENV'" in line:
                    offenders.append(
                        f"{path.relative_to(_PACKAGE_ROOT).as_posix()}:{number}"
                    )
        assert not offenders, (
            f"bare VIRTUAL_ENV literal at {offenders}; read it through "
            "EnvVar.VIRTUAL_ENV, or better, _runtime_identity"
        )

    def test_no_module_rebuilds_the_interpreter_field_set(self) -> None:
        # sys.base_prefix is the fingerprint of this particular field set: it
        # appears for no other reason than describing which interpreter is
        # running, so a new use means a fifth copy is being assembled.
        offenders = [
            f"{path.relative_to(_PACKAGE_ROOT).as_posix()}:{number}"
            for path in _production_sources()
            if path.name != "_runtime_identity.py"
            for number, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), start=1
            )
            if "sys.base_prefix" in line
        ]
        assert not offenders, (
            f"interpreter field set rebuilt at {offenders}; splice "
            "_runtime_identity.interpreter_fields() instead"
        )


class TestLoopbackHttpHasOneOpener:
    """Loopback HTTP goes through ``_loopback_http.LOOPBACK_OPENER``.

    Two packages built this independently, each with a long comment explaining
    the same threat, and then diverged on the control that matters: the service
    transport refused redirects and the qdrant runtime did not. A 3xx to a
    qdrant probe was followed, and the redirect target's 200 was read as
    "ready" - the spoofed-readiness case the qdrant comment itself described.
    """

    #: Provisioning downloads the pinned binary over PUBLIC HTTPS and must let
    #: redirects happen so it can re-check scheme and host across each hop.
    #: That is a different threat from a loopback probe, and folding it into
    #: the no-redirect opener would delete a security control.
    _ALLOWED_OPENERS: ClassVar[dict[str, str]] = {
        "_provision.py": "host-pinned redirects for the binary download"
    }

    def test_no_module_builds_its_own_opener(self) -> None:
        offenders = [
            f"{path.relative_to(_PACKAGE_ROOT).as_posix()}:{number}"
            for path in _production_sources()
            if path.name != "_loopback_http.py"
            and path.name not in self._ALLOWED_OPENERS
            for number, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), start=1
            )
            if "build_opener(" in line
        ]
        assert not offenders, (
            f"second HTTP opener at {offenders}; loopback callers must use "
            "_loopback_http.LOOPBACK_OPENER so the proxy bypass and the "
            "redirect refusal cannot be applied to one path and forgotten on "
            "another"
        )

    def test_the_canonical_opener_carries_both_defences(self) -> None:
        # Asserting the object, not the source text: a future edit that drops
        # either handler from build_opener would leave the call site looking
        # correct while the defence is gone.
        import urllib.request

        from .._loopback_http import LOOPBACK_OPENER, NoRedirect

        # CPython's OpenerDirector.__init__ sets self.handlers, but typeshed
        # does not declare it, so it is read defensively rather than with a
        # type-check suppression. An empty default would fail both asserts
        # below, which is the correct outcome if the attribute ever goes.
        handlers: list[object] = getattr(LOOPBACK_OPENER, "handlers", [])
        assert any(isinstance(h, NoRedirect) for h in handlers), (
            "the loopback opener must refuse redirects"
        )
        # ProxyHandler.proxies is likewise a real attribute typeshed omits.
        proxy_maps = [
            getattr(h, "proxies", None)
            for h in handlers
            if isinstance(h, urllib.request.ProxyHandler)
        ]
        assert not any(proxy_maps), (
            f"the loopback opener must carry no proxy map, found {proxy_maps}; "
            "an operator's http_proxy would otherwise route a 127.0.0.1 "
            "request off the host"
        )

    def test_allowed_openers_name_only_modules_that_exist(self) -> None:
        names = {path.name for path in _production_sources()}
        stale = sorted(set(self._ALLOWED_OPENERS) - names)
        assert not stale, f"opener allowlist names missing modules: {stale}"


class TestDiscoveryFilenameHasOneSpelling:
    """``service.json`` is spelled once, in ``config``.

    Five sites hardcoded it while ``_machine_lock`` already had a private
    constant for the same string. The reader that makes this matter is the
    indexer's sensitive-pattern list: the discovery file carries the service
    token, and a rename that missed that one entry would start indexing a
    credential nobody remembered was in the file.
    """

    def test_no_module_hardcodes_the_discovery_filename(self) -> None:
        offenders = [
            f"{path.relative_to(_PACKAGE_ROOT).as_posix()}:{number}"
            for path in _production_sources()
            if path.name != "config.py"
            for number, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), start=1
            )
            if '"service.json"' in line or "'service.json'" in line
        ]
        assert not offenders, (
            f"hardcoded discovery filename at {offenders}; import "
            "config.SERVICE_STATUS_FILENAME so every reader renames together"
        )

    def test_every_reader_resolves_the_same_file(self) -> None:
        # The constant alone does not prove the readers agree - they resolve
        # the DIRECTORY separately, and that is where they could still diverge.
        from ..config import SERVICE_STATUS_FILENAME
        from ..server._lifecycle import _status_file_path
        from ..server._state import _SENSITIVE_PATTERNS
        from ..serviceclient._discovery import _status_file

        assert _status_file() == _status_file_path(), (
            "the client and the daemon must resolve one discovery file"
        )
        assert SERVICE_STATUS_FILENAME in _SENSITIVE_PATTERNS, (
            "the discovery file carries the service token and must stay in the "
            "indexer's sensitive-pattern list"
        )


class TestDiskFullVocabularyHasOneHome:
    """One list of what "the disk is full" looks like in an error string.

    ``_job_errors`` knew five spellings and ``_store_writes`` knew two, so
    three of them were classified transient by the write path and retried
    until the budget expired against a disk that was never going to free
    itself. The lists agreeing is the property; a second list is how they
    stopped agreeing.
    """

    def test_no_second_disk_full_vocabulary(self) -> None:
        # Only spellings that are FOREIGN error text - qdrant's WAL message and
        # the OS phrasing - so a module carrying one is quoting an error to match
        # it. Generic English like "not enough free disk space" is deliberately
        # NOT a fingerprint: this project raises its own disk-full error whose
        # operator-facing sentence reads that way, and flagging that would push
        # the next author to reword good prose instead of reusing the vocabulary.
        fingerprints = ("wal buffer size exceeds", "not enough space available")
        offenders = [
            f"{path.relative_to(_PACKAGE_ROOT).as_posix()}:{number}"
            for path in _production_sources()
            if path.name != "_job_errors.py"
            for number, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), start=1
            )
            if any(mark in line.lower() for mark in fingerprints)
        ]
        assert not offenders, (
            f"second disk-full vocabulary at {offenders}; import "
            "_job_errors.DISK_FULL_MARKERS so both readers agree"
        )

    def test_both_readers_agree_on_every_spelling(self) -> None:
        # The behavioural property the shared tuple exists to hold. Asserted
        # over the canonical list itself, so a spelling added later is covered
        # without anyone remembering to extend this test.
        from .._job_errors import DISK_FULL_MARKERS, JobErrorKind, classify_error_text
        from .._store_writes import classify_write_error

        for marker in DISK_FULL_MARKERS:
            text = f"the backend said: {marker} while writing"
            assert classify_error_text(text) is JobErrorKind.DISK_FULL, (
                f"{marker!r} must read as disk_full in a job record"
            )
            assert classify_write_error(RuntimeError(text)) == "unrecoverable", (
                f"{marker!r} must stop the write retry loop; retrying cannot "
                "free disk space"
            )

    def test_a_transient_error_is_still_retried(self) -> None:
        # The merge widened what counts as unrecoverable, so pin the other
        # direction: an ordinary blip must remain eligible for retry.
        from .._store_writes import classify_write_error

        assert classify_write_error(RuntimeError("connection reset by peer")) == (
            "transient"
        )


class TestFdLockHasOneImplementation:
    """The ``msvcrt``/``fcntl`` branch lives only in ``_fd_lock``.

    Three modules carried it: the machine singleton lock, the status-write
    lock, and the store's exclusive lock. Only the platform call was shared -
    each caller's policy around it (which file, which byte, what contention
    means) differs for real reasons and stayed where it was.
    """

    def test_no_module_calls_the_platform_lock_directly(self) -> None:
        offenders = [
            f"{path.relative_to(_PACKAGE_ROOT).as_posix()}:{number}"
            for path in _production_sources()
            if path.name != "_fd_lock.py"
            for number, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), start=1
            )
            if ("msvcrt.locking(" in line or "fcntl.flock(" in line)
            and not line.lstrip().startswith("#")
        ]
        assert not offenders, (
            f"direct advisory-lock call at {offenders}; use "
            "_fd_lock.lock_fd_exclusive / unlock_fd so the platform branch "
            "has one implementation"
        )

    @pytest.mark.skipif(
        sys.platform != "win32",
        reason="offset is a Windows-only parameter; POSIX flock is whole-file",
    )
    def test_the_offset_is_honoured_so_a_locked_payload_stays_readable(
        self, tmp_path: Path
    ) -> None:
        # The machine lock locks its OWN payload file, and relies on the byte
        # sitting past the JSON because a Windows lock makes the byte
        # unreadable. If offset were ignored, that file would become
        # unreadable to the contender that needs the holder pid for its
        # refusal message - a regression no import check would see.
        #
        # Windows-only by construction, and the skip above is load-bearing
        # rather than defensive: msvcrt locks a byte RANGE, so two ranges of
        # one file are independently lockable. POSIX flock locks the whole
        # file per open description, so the second acquisition below is
        # refused there - which is the documented contract, not a defect. The
        # POSIX half of that contract is asserted separately below.
        import os

        from .._fd_lock import lock_fd_exclusive, unlock_fd

        target = tmp_path / "payload.lock"
        held = os.open(target, os.O_RDWR | os.O_CREAT, 0o600)
        other = os.open(target, os.O_RDWR)
        try:
            os.ftruncate(held, 1 << 21)
            lock_fd_exclusive(held, offset=1 << 20)
            # A different byte of the same file is still lockable.
            lock_fd_exclusive(other, offset=0)
            unlock_fd(other, offset=0)
        finally:
            unlock_fd(held, offset=1 << 20)
            os.close(other)
            os.close(held)

    @pytest.mark.skipif(
        sys.platform == "win32",
        reason="asserts the POSIX half of the contract",
    )
    def test_posix_locks_the_whole_file_regardless_of_offset(
        self, tmp_path: Path
    ) -> None:
        """The offset is ignored on POSIX, and the helper says so.

        Asserting this keeps the platform split honest in both directions: a
        future change that made POSIX honour the offset would pass the Windows
        test above while silently breaking every caller that relies on the
        whole-file exclusion this side provides.
        """
        import os

        from .._fd_lock import lock_fd_exclusive, unlock_fd

        target = tmp_path / "payload.lock"
        held = os.open(target, os.O_RDWR | os.O_CREAT, 0o600)
        other = os.open(target, os.O_RDWR)
        try:
            os.ftruncate(held, 1 << 21)
            lock_fd_exclusive(held, offset=1 << 20)
            with pytest.raises(OSError):
                lock_fd_exclusive(other, offset=0)
        finally:
            unlock_fd(held, offset=1 << 20)
            os.close(other)
            os.close(held)


class TestOperatorAddressLineHasOneTemplate:
    """The "Address:" line is built by ``_render._address_line`` alone.

    ``_address_line`` already existed and already had eight callers while eight
    OTHER sites hand-built the identical f-string - a half-adopted canonical,
    which is worse than none: it reads as if the template is owned, so the next
    author copies whichever form they happened to see.
    """

    def test_no_module_hand_builds_the_address_line(self) -> None:
        offenders = [
            f"{path.relative_to(_PACKAGE_ROOT).as_posix()}:{number}"
            for path in _production_sources()
            if path.name != "_render.py"
            for number, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), start=1
            )
            if "Address: http://127.0.0.1:" in line
        ]
        assert not offenders, (
            f"hand-built operator address line at {offenders}; call "
            "_render._address_line(port) so the label and host rendering "
            "cannot disagree across the CLI's own output"
        )

    def test_the_template_still_renders_what_operators_parse(self) -> None:
        # The string itself is the contract - operators and docs read it - so
        # centralising must not quietly reword it.
        from ..cli._render import _address_line

        assert _address_line(8766) == "Address: http://127.0.0.1:8766"


class TestConfigDefaultsResolveInConfig:
    """A default belongs where the setting does, not at the point of use.

    Two settings had their fallback spelled at the call site instead: the
    Qdrant base URL (four identical expressions plus a variant) and the
    Hugging Face cache location (two). The HF one had already gone wrong -
    an operator who set ``HF_HOME`` was told a failed download's leftovers
    were in ``~/.cache/huggingface``, which is not where they are.
    """

    def test_no_module_rebuilds_the_qdrant_url_fallback(self) -> None:
        # Keys on the loopback fallback, not on reading qdrant_url: several
        # modules legitimately read it WITHOUT a fallback to ask a different
        # question - "is a remote configured?" - and must not be flagged.
        offenders = [
            f"{path.relative_to(_PACKAGE_ROOT).as_posix()}:{number}"
            for path in _production_sources()
            if path.name != "config.py"
            for number, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), start=1
            )
            if "qdrant_port}" in line and "127.0.0.1" in line
        ]
        assert not offenders, (
            f"inline Qdrant URL fallback at {offenders}; read "
            "get_config().effective_qdrant_url"
        )

    def test_no_module_hardcodes_the_hf_cache_default(self) -> None:
        offenders = [
            f"{path.relative_to(_PACKAGE_ROOT).as_posix()}:{number}"
            for path in _production_sources()
            if path.name != "config.py"
            for number, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), start=1
            )
            if "~/.cache/huggingface" in line
        ]
        assert not offenders, (
            f"hardcoded HF cache default at {offenders}; read "
            "get_config().hf_cache_location so a set HF_HOME is honoured"
        )

    def test_the_hf_cache_location_follows_the_environment(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The behaviour the hardcoded default got wrong. Asserted through the
        # config property, which is what every reporting site now calls.
        from ..config import EnvVar, get_config, reset_config

        monkeypatch.setenv(EnvVar.HF_HOME.value, "/tmp/hf-elsewhere")
        reset_config()
        try:
            assert get_config().hf_cache_location == "/tmp/hf-elsewhere"
        finally:
            monkeypatch.delenv(EnvVar.HF_HOME.value, raising=False)
            reset_config()
        assert get_config().hf_cache_location == "~/.cache/huggingface"


class TestNoStructurallyIdenticalFunctions:
    """No two production functions share a body that differs only by constants.

    Found by normalising every function body - identifiers, attributes,
    literals and docstrings replaced - and hashing it, which surfaces
    duplication no keyword search would: the store's code and document scroll
    pages were ~50 identical lines apart from the collection, the payload key,
    and the noun in two error messages.

    The allowlist below records groups that are structurally alike but
    semantically distinct - the same SHAPE applied to different domains, which
    merging would harm. Each entry names why.
    """

    #: (sorted tuple of "module:function") -> reason the shape is not shared
    #: behaviour. Shrink this as groups are merged; adding an entry to silence
    #: the check rather than to record a judgement defeats it.
    #: Why a group of identical-looking bodies is NOT shared behaviour. The
    #: reasons cluster, so they are named once and applied, rather than
    #: sixteen near-identical sentences - which would be this file committing
    #: the duplication it exists to prevent.
    _PARAMETERISATION = (
        "A named entry point supplying its own constants to an implementation "
        "that is ALREADY shared. Merging further would push those constants "
        "out to every call site, which is the opposite of the goal."
    )
    _OPTIONAL_ATTR = (
        "Python's missing optional-chaining: `x = self._attr; return x.f() if "
        "x is not None else None`. A generic helper reads worse than the two "
        "lines, and the classes involved share no base to hang it on."
    )
    _FIND_FIRST = (
        "Linear search for the first item matching an attribute. A generic "
        "finder costs more in indirection than the four lines it saves."
    )
    _DISTINCT_PROSE = (
        "Same rendering shape, different diagnosis. What differs is the "
        "operator-facing sentences, so merging would mean passing prose in as "
        "arguments."
    )
    _SMALL_GUARD = (
        "A two-line accessor or guard whose computation, return type, or "
        "error message differs. The shape is shared; nothing else is."
    )
    _SERIALISATION = (
        "Both build a dict literal from their own fields. The shape of "
        "`to_dict` is not behaviour that can be shared - the fields are "
        "unrelated."
    )

    _NAMED_SUBSET = (
        "A membership test against a named subset of one enum's members. The "
        "shape is `return self in {...}` and the whole content is WHICH "
        "members - parameterising it would mean a set of sets keyed by name, "
        "which is the enumeration these properties exist to remove."
    )

    _ALLOWED_SHAPES: ClassVar[dict[tuple[str, ...], str]] = {
        (
            "job_models.py:is_live_attempt",
            "job_models.py:is_retryable",
        ): _NAMED_SUBSET,
        (
            "cli/_search.py:_render_breadth_shortfall",
            "cli/_search.py:_render_file_breadth_shortfall",
        ): _DISTINCT_PROSE,
        (
            "_readiness.py:dimension",
            "commands/_provision.py:result_for",
        ): _FIND_FIRST,
        (
            "indexer/_preprocess_config.py:match",
            "indexer/_resolved_policy.py:match_preprocess",
        ): _FIND_FIRST,
        (
            "cli/_preprocess.py:_format_failure_handling",
            "cli/_preprocess.py:_status_effect_line",
        ): _SMALL_GUARD,
        (
            "commands/_mcp_topology.py:_require_identity",
            "commands/_mcp_topology.py:_require_unchanged",
        ): _SMALL_GUARD,
        (
            "watcher.py:dirty_paths",
            "watcher.py:pending_count",
        ): _SMALL_GUARD,
        (
            "commands/_provision.py:to_dict",
            "indexer/_drift_owner.py:snapshot",
        ): _SERIALISATION,
        (
            "indexer/_codebase_indexer.py:_reuse_snapshot",
            "indexer/_document_indexer.py:_reuse_snapshot",
            "indexer/_generation_lifecycle.py:drift_snapshot",
        ): _OPTIONAL_ATTR,
        (
            "indexer/_codebase_indexer.py:memory_budget_snapshot",
            "indexer/_document_indexer.py:memory_budget_snapshot",
        ): _OPTIONAL_ATTR,
        (
            "cli/_service_start.py:_fail_start",
            "cli/_service_stop.py:_fail_stop",
        ): _PARAMETERISATION,
        (
            "cli/_service_start.py:_start_success",
            "cli/_service_stop.py:_stop_success",
        ): _PARAMETERISATION,
        (
            "indexer/_content_discovery.py:resolve_policy",
            "indexer/_document_indexer.py:resolve_policy_snapshot",
        ): _PARAMETERISATION,
        (
            "store.py:_retrieve",
            "store.py:_scroll",
        ): _PARAMETERISATION,
        (
            "store.py:ensure_document_table",
            "store.py:ensure_table",
        ): _PARAMETERISATION,
        (
            "store.py:get_all_document_content_ids",
            "store.py:get_all_ids",
        ): _PARAMETERISATION,
        (
            "store.py:scroll_code_content",
            "store.py:scroll_document_content",
        ): _PARAMETERISATION,
    }

    _MIN_NODES: ClassVar[int] = 20

    def test_no_large_duplicate_function_bodies(self) -> None:
        import ast
        import hashlib
        from collections import defaultdict

        class _Norm(ast.NodeTransformer):
            def visit_Name(self, node: ast.Name) -> ast.Name:
                return ast.copy_location(ast.Name(id="_", ctx=node.ctx), node)

            def visit_arg(self, node: ast.arg) -> ast.arg:
                return ast.copy_location(ast.arg(arg="_", annotation=None), node)

            def visit_Attribute(self, node: ast.Attribute) -> ast.Attribute:
                self.generic_visit(node)
                return ast.copy_location(
                    ast.Attribute(value=node.value, attr="_", ctx=node.ctx), node
                )

            def visit_Constant(self, node: ast.Constant) -> ast.Constant:
                return ast.copy_location(ast.Constant(value=None), node)

        groups: dict[str, list[str]] = defaultdict(list)
        for path in _production_sources():
            tree = ast.parse(path.read_text(encoding="utf-8"))
            rel = path.relative_to(_PACKAGE_ROOT).as_posix()
            for fn in ast.walk(tree):
                if not isinstance(fn, ast.FunctionDef | ast.AsyncFunctionDef):
                    continue
                body = [
                    stmt
                    for stmt in fn.body
                    if not (
                        isinstance(stmt, ast.Expr)
                        and isinstance(stmt.value, ast.Constant)
                    )
                ]
                if not body:
                    continue
                normalised = ast.Module(
                    body=[
                        ast.fix_missing_locations(
                            _Norm().visit(ast.parse(ast.unparse(stmt)))
                        )
                        for stmt in body
                    ],
                    type_ignores=[],
                )
                if sum(1 for _ in ast.walk(normalised)) < self._MIN_NODES:
                    continue
                digest = hashlib.sha1(ast.dump(normalised).encode()).hexdigest()
                groups[digest].append(f"{rel}:{fn.name}")

        offenders = {
            tuple(sorted(set(members))): members
            for members in groups.values()
            if len(set(members)) > 1
        }
        unexplained = {
            key: members
            for key, members in offenders.items()
            if key not in self._ALLOWED_SHAPES
        }
        assert not unexplained, (
            f"functions with identical bodies at {sorted(unexplained)}; either "
            "merge them behind one implementation that takes the differing "
            "values, or add the group to _ALLOWED_SHAPES with the reason the "
            "shape is not shared behaviour"
        )


class TestAtomicReplaceHasOneImplementation:
    """Publishing a file goes through ``_atomic_write``, never bare ``os.replace``.

    Twenty-odd modules published state with a bare ``os.replace``. One - the
    job persistence layer - had learned that Windows Defender and the Search
    indexer open a freshly published file, so a replace landing in that window
    fails with ACCESS_DENIED or SHARING_VIOLATION, and had grown a retry
    ladder for it. The other twenty were still exposed to the exact condition
    that layer was hardened against.
    """

    def test_no_module_calls_os_replace_directly(self) -> None:
        offenders = [
            f"{path.relative_to(_PACKAGE_ROOT).as_posix()}:{number}"
            for path in _production_sources()
            if path.name != "_atomic_write.py"
            for number, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), start=1
            )
            if "os.replace(" in line and not line.lstrip().startswith("#")
        ]
        assert not offenders, (
            f"bare os.replace at {offenders}; use "
            "_atomic_write.replace_atomically, which retries the Windows "
            "sharing race and costs nothing when uncontended"
        )

    def test_the_retry_is_free_when_uncontended(self, tmp_path: Path) -> None:
        # The whole argument for applying this everywhere is that the ladder
        # exits on its first attempt. If a future edit made it sleep
        # unconditionally, every publish in the codebase would slow down and
        # no other test would notice.
        import time

        from .._atomic_write import replace_atomically

        source = tmp_path / "s.tmp"
        source.write_text("x", encoding="utf-8")
        started = time.perf_counter()
        replace_atomically(source, tmp_path / "d.json")
        elapsed = time.perf_counter() - started
        assert elapsed < 0.05, (
            f"an uncontended replace took {elapsed * 1000:.1f} ms; the retry "
            "ladder must not sleep when the first attempt succeeds"
        )

    def test_durability_is_opt_in_and_separate(self) -> None:
        # Keeping the two apart is what let every caller adopt the retry: a
        # per-file indexing write must not pay for an fsync it does not need.
        from .._atomic_write import replace_atomically, replace_durably

        assert replace_atomically is not replace_durably


class TestSearchPhaseKeysAreNamed:
    """A timings phase key is written once, not at every site that uses it.

    Seven keys were spelled as literals across twenty-three sites - at each
    recording site and again at each site that read one back to sum a total.
    Three of them were recorded from three different searches.

    A phase key is a wire name. Renaming one recording site and not its reader
    does not raise: the phase drops out of the total, and the search reports a
    smaller number than the work took. That is the failure this prevents, and
    it is invisible to every test that only checks results.
    """

    def test_no_search_module_spells_a_phase_key(self) -> None:
        """A literal key is a spelling the reader of the total cannot follow."""
        from ..search import _result_shaping

        owned = {
            value
            for name, value in vars(_result_shaping).items()
            if name.startswith("PHASE_") and isinstance(value, str)
        }
        assert owned, "no phase keys found; the scan is looking wrongly"
        offenders: list[str] = []
        for path in _every_production_file():
            if path.name == "_result_shaping.py":
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except SyntaxError:  # pragma: no cover - parsed elsewhere
                continue
            # Only STORE and LOOKUP positions. The same string is also an HTTP
            # response field name in the search route, and that is a separate
            # contract - the wire shape a consumer parses, not the internal
            # key a phase was recorded under. Flagging it would force the two
            # to move together, which is the opposite of what is wanted.
            #
            # Subscripts count. A phase is often recorded by assigning into the
            # mapping rather than through the recorder, and the first version
            # of this check read only calls - so four keys across three
            # modules, two of them crossing a module boundary, sat underneath
            # it untouched.
            offenders.extend(
                f"{path.name}:{node.slice.lineno} stores {node.slice.value!r}"
                for node in ast.walk(tree)
                if isinstance(node, ast.Subscript)
                and isinstance(node.slice, ast.Constant)
                and node.slice.value in owned
            )
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                callee = node.func
                name = (
                    callee.attr
                    if isinstance(callee, ast.Attribute)
                    else getattr(callee, "id", "")
                )
                # Suffix match, not equality: the searcher imports the
                # recorder aliased as ``_record_seconds``, and an earlier
                # version of this check matched only the bare name - so a
                # mutation putting the literal straight back sailed past it.
                if not (
                    name == "get"
                    or name.endswith("record_seconds")
                    or name.endswith("add_seconds")
                ):
                    continue
                offenders.extend(
                    f"{path.name}:{argument.lineno} looks up {argument.value!r}"
                    for argument in node.args
                    if isinstance(argument, ast.Constant) and argument.value in owned
                )
        assert not offenders, (
            f"a timings phase key is spelled outside its owner at {offenders}; "
            "use the constant, because a key renamed at one of its sites "
            "silently drops that phase out of the reported total"
        )

    def test_every_key_is_distinct_and_suffixed(self) -> None:
        """Two phases sharing a key would overwrite each other's measurement.

        Proven able to fail: pointing two of the constants at one string fails
        the distinctness assertion, which is what a copy-paste of a new phase
        constant produces.
        """
        from ..search import _result_shaping

        keys = {
            name: value
            for name, value in vars(_result_shaping).items()
            if name.startswith("PHASE_") and isinstance(value, str)
        }
        assert len(set(keys.values())) == len(keys), keys
        for name, value in keys.items():
            assert value.endswith("_seconds"), (name, value)


class TestEveryRegisteredRouteIsTokenGated:
    """No route reaches its body without the token check having run.

    Twenty-six handlers open with the same three lines - call ``require_token``,
    test the result, return it when set. The check itself is already one
    function; what is repeated is the call and the early return, and that is
    the part a new route can simply omit. Omitting it does not fail: the route
    works, and works for anyone who can reach the port.

    This asserts the property rather than the shape, so a handler that gets the
    gate some other way still passes. Two already do: ``pause`` and ``resume``
    delegate to the quiesce handler, which is gated - a check looking only for
    a literal ``require_token`` call in each registered handler would have
    called both of them unauthenticated and been wrong.

    A decorator would collapse the three lines to one and make the gate
    impossible to half-apply. That is the better shape and it is not done here:
    it rewrites twenty-five authentication call sites, and this guard is what
    makes doing that safely possible rather than hopefully.
    """

    @staticmethod
    def _routes_module() -> ast.Module:
        return ast.parse(
            (_PACKAGE_ROOT / "server" / "_routes.py").read_text(encoding="utf-8")
        )

    def test_no_registered_route_skips_the_token_check(self) -> None:
        """Directly or by delegation, every route must reach the gate."""
        tree = self._routes_module()

        bodies: dict[str, str] = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                bodies[node.name] = ast.unparse(node)

        gated = {
            name for name, body in bodies.items() if "require_token(request)" in body
        }
        # A handler that hands the request to a gated handler is gated too.
        changed = True
        while changed:
            changed = False
            for name, body in bodies.items():
                if name in gated:
                    continue
                if any(f"{peer}(request" in body for peer in gated):
                    gated.add(name)
                    changed = True

        registered = [
            node.args[1].id
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "Route"
            and len(node.args) >= 2
            and isinstance(node.args[1], ast.Name)
        ]
        assert registered, "no routes discovered; the scan is looking wrongly"
        ungated = sorted(name for name in registered if name not in gated)
        assert not ungated, (
            f"these registered routes never reach require_token: {ungated}; "
            "a route without the gate does not fail, it serves anyone who can "
            "reach the port"
        )


class TestRepeatedStatementRunsStayMerged:
    """No long run of statements is repeated inside two functions.

    Every other structural check here compares whole function bodies, so a run
    repeated INSIDE two larger functions was invisible to all of them. That is
    how a nine-statement pyproject write, a nine-statement incremental ingest
    phase, and an eleven-statement report section all survived earlier passes.

    The threshold is measured, not guessed. On the merged tree the repeated-run
    count by window size is: seven and above, none; six, four; five, ten; four,
    thirty-eight. The lower bands are dominated by constructor assignment
    sequences, which look alike once identifiers are blinded without being
    copies of anything, so a bound below seven would report noise and train its
    reader to ignore the check. Seven is the lowest bound that holds with no
    allowlist, which is the property worth having - an allowlist longer than
    the rule is how a guard stops meaning anything.

    Counting is by TOP-LEVEL statement, so a nested ``if`` or ``for`` body
    counts as one. A seven-statement run here is therefore a larger fragment
    than the number suggests.

    The two groups sitting just under the bound have been read, so the next
    person to lower it inherits the verdict rather than re-deriving it:

    * ``_progress`` and ``_run_policy`` constructors. Different classes,
      different fields, the same shape only because blinding erases the names -
      a run of attribute assignments is what every constructor looks like. Not
      duplication, and no bound distinguishes it from one that is.
    * ``job_dispatch`` code and document attempt runners. Genuine: two parallel
      implementations differing by which admission call and which indexer they
      use, where the sixth matched statement is the whole ``try`` body. Merging
      them means parameterising the job execution path by source, which is a
      real change to the path that runs every index job and wants its own
      iteration rather than a hurried one.
    """

    _MIN_RUN: ClassVar[int] = 7

    @staticmethod
    def _blinded_runs(node: ast.FunctionDef | ast.AsyncFunctionDef) -> list[str]:
        """Return the function's top-level statements, identifier-blinded."""

        class _Blind(ast.NodeTransformer):
            def visit_Name(self, node: ast.Name) -> ast.AST:
                return ast.copy_location(ast.Name(id="_", ctx=node.ctx), node)

            def visit_Attribute(self, node: ast.Attribute) -> ast.AST:
                self.generic_visit(node)
                return ast.copy_location(
                    ast.Attribute(value=node.value, attr="_", ctx=node.ctx), node
                )

            def visit_Constant(self, node: ast.Constant) -> ast.AST:
                return ast.copy_location(ast.Constant(value=None), node)

            def visit_ExceptHandler(self, node: ast.ExceptHandler) -> ast.AST:
                self.generic_visit(node)
                node.name = "_" if node.name else None
                return node

        rendered: list[str] = []
        for statement in node.body:
            if isinstance(statement, ast.Expr) and isinstance(
                statement.value, ast.Constant
            ):
                continue
            if isinstance(statement, ast.Import | ast.ImportFrom):
                continue
            try:
                reparsed = ast.parse(ast.unparse(statement)).body[0]
            except (SyntaxError, ValueError):  # pragma: no cover - unparseable
                continue
            rendered.append(ast.dump(_Blind().visit(reparsed)))
        return rendered

    def test_no_long_statement_run_appears_in_two_functions(self) -> None:
        """A repeated run is a copy that shares only part of its host."""
        runs: dict[str, set[str]] = {}
        for path in _every_production_file():
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except SyntaxError:  # pragma: no cover - parsed elsewhere
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                    continue
                body = self._blinded_runs(node)
                if len(body) < self._MIN_RUN:
                    continue
                where = f"{path.name}:{node.lineno} {node.name}"
                for start in range(len(body) - self._MIN_RUN + 1):
                    window = hashlib.sha256(
                        chr(31).join(body[start : start + self._MIN_RUN]).encode()
                    ).hexdigest()
                    runs.setdefault(window, set()).add(where)
        offenders = sorted(
            {tuple(sorted(sites)) for sites in runs.values() if len(sites) > 1}
        )
        assert not offenders, (
            f"a run of {self._MIN_RUN}+ statements is repeated inside these "
            f"functions: {offenders}; extract the shared phase, because a "
            "fragment copy is the one shape the whole-body scans cannot see"
        )


class TestPyprojectWritesGoThroughOneWriter:
    """Every pyproject rewrite preserves byte shape through one function.

    ``write_doc_preserving_shape`` already had seven callers in two other
    modules while ``apply_patch`` and ``remove_patch``, eight lines above it in
    its own file, still inlined the same nine-statement sequence. The
    repetition was not the worst of it: those two owe a stated promise to each
    other - apply followed by remove leaves the file byte-identical - and a
    promise between two hand-maintained copies of a byte-shaping routine holds
    only while someone keeps them aligned.

    Two shapes survive the round trip and neither is recoverable from the
    parsed document: ``tomlkit`` always emits LF, and always exactly one
    trailing newline. Both are read back off the file, which is why the
    routine cannot be replaced by a plain dump.
    """

    def test_no_caller_reassembles_the_shape_preserving_write(self) -> None:
        """The trailing-newline restore belongs to one writer."""
        offenders: list[str] = []
        for path in _every_production_file():
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except SyntaxError:  # pragma: no cover - parsed elsewhere
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                target = node.func
                name = target.id if isinstance(target, ast.Name) else None
                if name != "_match_trailing_newline":
                    continue
                enclosing = [
                    outer.name
                    for outer in ast.walk(tree)
                    if isinstance(outer, ast.FunctionDef)
                    and outer.lineno <= node.lineno <= (outer.end_lineno or 0)
                ]
                if "write_doc_preserving_shape" not in enclosing:
                    offenders.append(f"{path.name}:{node.lineno} in {enclosing}")
        assert not offenders, (
            f"a caller restores the trailing-newline shape itself at "
            f"{offenders}; call write_doc_preserving_shape, so the "
            "apply/remove byte-symmetry is one function's property rather "
            "than an agreement between copies"
        )

    def test_apply_then_remove_leaves_the_file_byte_identical(self) -> None:
        """The promise the two copies existed to keep, across every shape.

        Proven able to fail: dropping the ``_match_trailing_newline`` call from
        the writer fails this on the no-trailing-newline shapes, and dropping
        the CRLF restore fails it on the CRLF ones.
        """
        from ..torch_config._mutate import apply_patch, remove_patch

        newline = chr(10)
        carriage = chr(13) + newline
        base = newline.join(
            [
                "[project]",
                'name = "demo"',
                'version = "0.1.0"',
                "",
                "[tool.other]",
                "keep = true",
            ]
        )
        shapes = [
            base + newline,
            base,
            base + newline + newline,
            base.replace(newline, carriage) + carriage,
            base.replace(newline, carriage),
            base.replace(newline, carriage) + carriage + carriage,
        ]
        for text in shapes:
            with tempfile.TemporaryDirectory() as workspace:
                pyproject = Path(workspace) / "pyproject.toml"
                pyproject.write_text(text, encoding="utf-8", newline="")
                before = pyproject.read_bytes()
                apply_patch(pyproject)
                assert pyproject.read_bytes() != before, "apply changed nothing"
                remove_patch(pyproject)
                assert pyproject.read_bytes() == before, repr(text[:40])


class TestPublishGateAndRefusalAreShared:
    """The manifest admission gate and the feedback refusal each have one home.

    Two publishers opened their write loop with the same five-statement gate -
    refuse unconverged, refuse out-of-order, remember the path, skip
    non-indexed, assert the survivor has a hash - and then did entirely
    different things with the survivor. Only the gate was shared; the loops
    stayed. It had already drifted where drift is cheapest: the ordering
    refusal was two sentences for one violation, so the explanation an operator
    got depended on which index was publishing.

    The feedback refusal is the more interesting shape. The HTTP route and the
    service client each carried the same source set, the same "did the caller
    name any points" test, and the same three-key envelope. The client builds
    it locally to refuse without a round trip - worth doing, and exactly what
    makes the copy dangerous, because the two are a request apart and a
    server-side change leaves the client refusing on the old terms with nothing
    observing the disagreement.
    """

    def test_no_publisher_writes_its_own_admission_gate(self) -> None:
        """A second gate is a second definition of publishable evidence."""
        offenders: list[str] = []
        for path in _every_production_file():
            if path.name == "_file_state.py":
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except SyntaxError:  # pragma: no cover - parsed elsewhere
                continue
            offenders.extend(
                f"{path.name}:{node.lineno}"
                for node in ast.walk(tree)
                if isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and (
                    "cannot publish unresolved file state" in node.value
                    or "ledger file states must be" in node.value
                )
            )
        assert not offenders, (
            f"a publisher states the admission rule itself at {offenders}; "
            "iterate with iter_publishable_states, so one violation is not "
            "explained two ways depending on which index published"
        )

    def test_the_gate_refuses_unconverged_and_unordered_evidence(self) -> None:
        """Both refusals, and the skip that is not a refusal.

        Proven able to fail: dropping the ``converged`` clause fails on the
        unconverged case; dropping the ordering clause fails on the duplicate.
        """
        from .._job_errors import JobErrorKind
        from ..indexer._content_policy import AdmissionReason, ContentKind
        from ..indexer._file_state import (
            FileState,
            FileStateKind,
            iter_publishable_states,
        )

        digest = "a" * 128

        def indexed(rel_path: str) -> FileState:
            return FileState(
                rel_path=rel_path,
                state=FileStateKind.INDEXED,
                kind=ContentKind.CODE,
                content_hash=digest,
            )

        def skipped(rel_path: str) -> FileState:
            return FileState(
                rel_path=rel_path,
                state=FileStateKind.POLICY_REJECTED,
                kind=None,
                admission_reason=AdmissionReason.IGNORED,
            )

        assert [
            rel
            for rel, _ in iter_publishable_states([indexed("a.py"), skipped("b.py")])
        ] == ["a.py"]
        with pytest.raises(ValueError, match="unique and ordered"):
            list(iter_publishable_states([indexed("a.py"), indexed("a.py")]))
        with pytest.raises(ValueError, match="unique and ordered"):
            list(iter_publishable_states([indexed("b.py"), indexed("a.py")]))

        unconverged = FileState(
            rel_path="pending.py",
            state=FileStateKind.EXTRACT_RETRYABLE,
            kind=ContentKind.CODE,
            error_kind=JobErrorKind.EXTRACTION_RETRYABLE,
            detail="transient",
        )
        assert not unconverged.converged
        with pytest.raises(ValueError, match="cannot publish unresolved"):
            list(iter_publishable_states([unconverged]))

    def test_no_surface_builds_the_feedback_refusal_itself(self) -> None:
        """The client and the route must refuse on identical terms."""
        offenders: list[str] = []
        for path in _every_production_file():
            if path.name == "_source_types.py":
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except SyntaxError:  # pragma: no cover - parsed elsewhere
                continue
            offenders.extend(
                f"{path.name}:{node.lineno}"
                for node in ast.walk(tree)
                if isinstance(node, ast.Constant)
                and node.value == "unsupported_feedback_for_search_type"
            )
        assert not offenders, (
            f"the feedback refusal is built outside its owner at {offenders}; "
            "call unsupported_feedback_envelope, because the client refuses "
            "locally and would otherwise drift a request behind the server"
        )

    def test_the_refusal_covers_exactly_the_identity_free_sources(self) -> None:
        """Which sources refuse, asserted rather than left to two copies.

        Proven able to fail: adding or removing a source from the refusing set
        fails this, as does refusing when the caller named no point ids.
        """
        from .._source_types import PublicSourceType, unsupported_feedback_envelope

        refusing = {
            source
            for source in PublicSourceType
            if unsupported_feedback_envelope(source, has_point_ids=True) is not None
        }
        assert refusing == {PublicSourceType.DOCUMENT, PublicSourceType.COMBINED}
        for source in PublicSourceType:
            assert unsupported_feedback_envelope(source, has_point_ids=False) is None, (
                source
            )


class TestVectorWidthAndCapHaveOneResolver:
    """The sparse width and the emitted-output cap are decided in one place.

    Both indexers resolved the sparse width inline, in blocks identical down to
    the strict ``type(...) is not int`` test - seven statements each, inside
    two different methods in two files that never import each other. That shape
    is why no earlier scan saw it: every structural comparison here reads whole
    function bodies, and this was a fragment of two larger ones.

    The cap was worse than duplicated, it was divergent. The resolved policy
    rejected anything that was not an ``int``; the cache identity only rejected
    ``bool`` and non-positive values, so a float passed the cache check and
    compared fine against zero. The shared validator uses the stricter rule,
    which narrows the cache path - the only safe direction for a check that
    exists to catch a value config did not coerce.
    """

    def test_no_indexer_resolves_the_sparse_width_itself(self) -> None:
        """A second resolver is a second answer to the collection's width."""
        offenders: list[str] = []
        for path in _every_production_file():
            if path.name == "store_schema.py":
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except SyntaxError:  # pragma: no cover - parsed elsewhere
                continue
            offenders.extend(
                f"{path.name}:{node.lineno}"
                for node in ast.walk(tree)
                if isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and "no valid output dimension" in node.value
            )
        assert not offenders, (
            f"the sparse width is resolved outside store_schema at {offenders}; "
            "call effective_sparse_dim, so the width a collection is built "
            "with comes from one place like the dense width already does"
        )

    def test_a_model_reporting_true_is_not_read_as_width_one(self) -> None:
        """Why the resolver tests ``type`` rather than ``isinstance``.

        ``bool`` subclasses ``int``, so an ``isinstance`` check would accept
        ``True`` and build a collection accepting exactly one sparse term.

        Proven able to fail: relaxing ``type(value) is not int`` to
        ``not isinstance(value, int)`` fails this on the ``True`` case.
        """
        from .._store_models import root_collection_prefix  # noqa: F401
        from ..store_schema import effective_sparse_dim

        class _Model:
            def __init__(self, value: object) -> None:
                self.sparse_dimension = value

        for bad in (True, False, 2.5, "30522", None, 0, -1):
            with pytest.raises(RuntimeError, match="no valid output dimension"):
                effective_sparse_dim(_Model(bad))
        assert effective_sparse_dim(_Model(30522)) == 30522

    def test_the_cap_check_is_the_strict_one_everywhere(self) -> None:
        """The divergence the two copies had: a float passed one of them.

        Proven able to fail: dropping the ``isinstance(value, int)`` clause
        reproduces the cache's weaker check and fails this on the float.
        """
        from ..indexer._preprocess_schema import validate_max_emitted_bytes

        assert validate_max_emitted_bytes(10 * 1024 * 1024) == 10 * 1024 * 1024
        for bad in (2.5, 1e7, True, False, 0, -1, "5", None):
            with pytest.raises(ValueError, match="positive integer"):
                validate_max_emitted_bytes(bad)

    def test_the_cap_rule_is_stated_once(self) -> None:
        """A second statement of the rule is how the two drifted apart."""
        offenders: list[str] = []
        for path in _every_production_file():
            if path.name == "_preprocess_schema.py":
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except SyntaxError:  # pragma: no cover - parsed elsewhere
                continue
            offenders.extend(
                f"{path.name}:{node.lineno}"
                for node in ast.walk(tree)
                if isinstance(node, ast.Constant)
                and node.value == "max_emitted_bytes must be a positive integer"
            )
        assert not offenders, (
            f"the emitted-cap rule is stated outside its validator at "
            f"{offenders}; call validate_max_emitted_bytes, because the two "
            "copies it replaced did not agree on what an integer is"
        )


class TestMcpFailureIsRecordedOneWay:
    """The install/uninstall pair words a topology refusal once, and records it once.

    Both verbs built the same three sentences for themselves and then appended
    each to two lists by hand. Both halves matter. The pair has to stay
    symmetric, because the same condition worded one way when installing and
    another when removing is a difference an operator has to work out is not
    real. And the two-channel record is load-bearing: ``mcp_errors`` drives the
    exit path while ``warnings`` drives the human report, so a failure written
    to only one either exits without explaining itself or explains itself
    without failing.

    The two copies had already settled on opposite append orders, which is the
    visible end of that drift rather than a bug in itself.
    """

    def test_no_verb_builds_a_topology_sentence_itself(self) -> None:
        """A prefix written anywhere but its owner is a second wording."""
        from ..commands import _mcp_topology

        owned = (
            _mcp_topology.TOPOLOGY_PREFLIGHT_FAILED,
            _mcp_topology.TOPOLOGY_MATERIALIZATION_FAILED,
        )
        offenders: list[str] = []
        for path in _every_production_file():
            if path.name == "_mcp_topology.py":
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except SyntaxError:  # pragma: no cover - parsed elsewhere
                continue
            offenders.extend(
                f"{path.name}:{node.lineno}"
                for node in ast.walk(tree)
                if isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and any(prefix in node.value for prefix in owned)
            )
        assert not offenders, (
            f"a topology refusal is worded outside the module that owns it at "
            f"{offenders}; build it with the shared helper so installing and "
            "removing describe one condition the same way"
        )

    def test_no_verb_records_the_two_channels_by_hand(self) -> None:
        """Both lists are reached through one function, or one gets forgotten."""
        offenders: list[str] = []
        # The verbs only. ``_mcp_topology`` holds ``record_mcp_failure``, whose
        # body is the two appends this forbids everywhere else.
        for name in ("_install.py", "_uninstall.py"):
            path = _PACKAGE_ROOT / "commands" / name
            lines = path.read_text(encoding="utf-8").splitlines()
            for number, line in enumerate(lines, start=1):
                nxt = lines[number] if number < len(lines) else ""
                first, second = line.strip(), nxt.strip()
                # Both orders count: the two copies had settled on opposite
                # ones, so matching only errors-then-warnings would have seen
                # half the sites.
                channels = {
                    suffix
                    for suffix in (
                        "mcp_errors.append(message)",
                        "warnings.append(message)",
                    )
                    if first.endswith(suffix) or second.endswith(suffix)
                }
                if len(channels) == 2:
                    offenders.append(f"{name}:{number}")
        assert not offenders, (
            f"a failure is appended to both channels by hand at {offenders}; "
            "call record_mcp_failure, because the pair is what makes a refusal "
            "both exit and explain itself"
        )

    def test_both_report_shapes_satisfy_the_recorder(self) -> None:
        """The structural contract, exercised on the real report objects.

        Proven able to fail: dropping either append from ``record_mcp_failure``
        fails this on the channel it stopped writing.
        """
        from pathlib import Path as _Path

        from ..commands._mcp_topology import record_mcp_failure
        from ..commands._models import InstallReport, UninstallReport

        for shape in (InstallReport, UninstallReport):
            report = shape(action="x", target=_Path("."))
            record_mcp_failure(report, "a failure")
            assert report.mcp_errors == ["a failure"], shape.__name__
            assert report.warnings == ["a failure"], shape.__name__


class TestValidationRulesAreStatedOnce:
    """A rejection rule lives in one function, not one per caller.

    Two validations were written twice. The rel_path check - nine clauses
    deciding whether a stored path is canonical and project-relative - existed
    as a row's own method and again as a ledger function, byte-identical. The
    content-route pattern check existed at the configuration boundary and again
    in the compiled policy vocabulary.

    Neither had drifted, and that is the whole difficulty: a duplicated
    rejection rule does not fail when it diverges, it just starts accepting
    different things in different places. Four of the rel_path clauses are
    containment checks - a backslash, a drive letter, an absolute path, and
    ``..`` each name a file outside the project the row claims to describe -
    so the copy that loses one accepts a path the other rejects, and which one
    runs depends on whether the value arrived as a row or through the ledger.

    Checked by message, because the message is what a second copy must
    reproduce to be a copy at all, and because the two rel_path bodies were
    identical while living in different shapes - a method and a function - that
    a body-comparison scan with a statement-count floor never compared.
    """

    #: Rejection message -> the module allowed to raise it.
    _OWNERS: ClassVar[dict[str, str]] = {
        "rel_path must be canonical project-relative POSIX syntax": "_file_state.py",
        "content route pattern must not be empty": "_content_route_syntax.py",
        "content route pattern must not contain NUL": "_content_route_syntax.py",
    }

    def test_no_module_but_the_owner_raises_the_rule(self) -> None:
        """A second module raising the same rejection is a second rule."""
        offenders: list[str] = []
        for path in _every_production_file():
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except SyntaxError:  # pragma: no cover - parsed elsewhere
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.Constant):
                    continue
                if not isinstance(node.value, str):
                    continue
                owner = self._OWNERS.get(node.value)
                if owner is not None and path.name != owner:
                    offenders.append(f"{path.name}:{node.lineno} raises {node.value!r}")
        assert not offenders, (
            f"a validation rule is stated outside the module that owns it: "
            f"{offenders}; call the shared validator, because a duplicated "
            "rejection does not fail when it drifts - it just starts "
            "accepting different things on different paths"
        )

    def test_the_ledger_and_the_row_share_one_validator(self) -> None:
        """Not equal behaviour - the same function, reached from both.

        Proven able to fail: giving the ledger its own copy again fails the
        message guard above, and rebinding the name here to an equivalent
        local function fails this identity assertion.
        """
        from ..indexer import _file_state, _run_ledger

        assert _run_ledger.validate_rel_path is _file_state.validate_rel_path

    def test_containment_clauses_all_still_reject(self) -> None:
        """The four clauses that keep a row inside the project.

        Proven able to fail: dropping any one of the ``..``, backslash, drive,
        or absolute clauses from the canonical validator fails this on the
        case that clause is the only one catching.
        """
        from ..indexer._file_state import validate_rel_path

        validate_rel_path("src/a.py")
        for escaping in (
            "..",
            "../escape",
            "a/../../etc/passwd",
            "/abs/path",
            "C:/win/path",
            "back" + chr(92) + "slash",
            "nul" + chr(0) + "byte",
        ):
            with pytest.raises(ValueError, match="canonical project-relative"):
                validate_rel_path(escaping)


class TestPinnedAssetNamesAreNamedOnce:
    """Every release asset filename is written once and pinned once.

    The digest table is keyed by asset filename, and the platform resolver
    wrote those filenames out again as literals to pick one. The resolver
    already refused an asset with no committed digest, so a typo could not
    reach a download - but that check only runs for the platform the typo is
    on, so a bad edit surfaced as a provisioning failure on one architecture
    instead of as a bad edit.

    The reverse direction had no check at all, and the two lists do differ:
    six assets are pinned, five are reachable. The x86-64 musl build is pinned
    and no platform selects it. That is deliberate - dropping a reviewed pin is
    how an unpinned asset later becomes reachable - so it is asserted as the
    one known exception rather than left as an unexplained gap.
    """

    #: Pinned but deliberately unreachable; see the constant's comment.
    _UNREACHABLE: ClassVar[frozenset[str]] = frozenset(
        {"qdrant-x86_64-unknown-linux-musl.tar.gz"}
    )

    #: Every pair the resolver accepts today.
    _PLATFORMS: ClassVar[tuple[tuple[str, str], ...]] = (
        ("win32", "amd64"),
        ("win32", "x86_64"),
        ("darwin", "arm64"),
        ("darwin", "aarch64"),
        ("darwin", "x86_64"),
        ("linux", "x86_64"),
        ("linux", "amd64"),
        ("linux", "aarch64"),
        ("linux", "arm64"),
    )

    def test_no_module_but_the_constants_spells_an_asset_filename(self) -> None:
        """A literal asset name anywhere else is a second spelling."""
        pattern = re.compile(r"^qdrant-[a-z0-9_]+-[a-z0-9-]+\.(tar\.gz|zip)$")
        offenders: list[str] = []
        for path in _every_production_file():
            if path.name == "_constants.py":
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except SyntaxError:  # pragma: no cover - parsed elsewhere
                continue
            offenders.extend(
                f"{path.name}:{node.lineno} spells {node.value!r}"
                for node in ast.walk(tree)
                if isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and pattern.match(node.value)
            )
        assert not offenders, (
            f"a release asset filename is spelled outside the pin table at "
            f"{offenders}; import the named constant, so the name the digest "
            "is keyed by and the name the resolver picks cannot diverge"
        )

    def test_every_selectable_asset_is_pinned_and_the_gap_is_declared(self) -> None:
        """Both directions, so neither list can drift unnoticed.

        Proven able to fail: adding a pin with no selecting platform, or
        making the musl build selectable, fails the second assertion.

        The first assertion needs the resolver's OWN pin check removed before
        it can be reached - pointing a branch at an unpinned asset raises
        inside ``asset_for_platform`` first, so a one-line mutation fails this
        test on that RuntimeError rather than on the assertion, which proves
        nothing about the assertion. It is deliberately kept as the check that
        survives if that guard is ever loosened.
        """
        from ..qdrant_runtime._constants import QDRANT_ASSET_SHA256
        from ..qdrant_runtime._resolve import asset_for_platform

        selectable = {
            asset_for_platform(platform, machine)
            for platform, machine in self._PLATFORMS
        }
        assert not selectable - set(QDRANT_ASSET_SHA256), (
            "the resolver can select an asset with no committed SHA256 pin"
        )
        assert set(QDRANT_ASSET_SHA256) - selectable == self._UNREACHABLE, (
            "the set of pinned-but-unreachable assets changed; either a "
            "platform gained an asset or a pin became dead - both need saying "
            "out loud rather than drifting"
        )


class TestNoOptionIsDeclaredTwice:
    """No two commands declare the same flag for themselves.

    A repeated ``Annotated[T, typer.Option(...)]`` repeats a contract: the flag
    name, its type, and the sentence an operator reads in ``--help``. Twenty-
    five duplicate declarations had accumulated, and one had already drifted -
    ``--port`` was described two ways, sixteen verbs calling it "Service port
    (defaults to running service)." and ``index``/``search`` calling it "Use
    the service running on this port." for the identical flag and type.

    Nothing fails when that happens. An operator comparing two ``--help``
    screens simply reads a difference that is not there, and the next verb to
    need the flag copies whichever neighbour it happened to look at.

    The package already fixed this once for ``--json``, whose shared constant
    records that thirty-three declarations had reached four wordings. This is
    the same rule applied to the flags that were still spelled per verb.

    Scoped to IDENTICAL declarations on purpose. A companion check asserting
    that one flag name carries one description was written and deleted: it
    fails on sixteen flags, and it is wrong to. ``--port`` names the Qdrant
    HTTP port on one verb, the port ``server start`` binds on another, and the
    port to stop a service by identity on a third; ``--dry-run`` and ``--yes``
    each name what that specific verb previews or confirms. Same flag name,
    genuinely different contracts. Only a repeated declaration - same name,
    same type, same sentence - is evidence of a copy.
    """

    def test_no_annotated_option_declaration_repeats(self) -> None:
        """Two commands wanting one flag share a declaration, or drift."""
        declarations: dict[str, list[str]] = {}
        cli_root = _PACKAGE_ROOT / "cli"
        for path in sorted(cli_root.rglob("*.py")):
            if path.name == "_app.py":
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except SyntaxError:  # pragma: no cover - parsed elsewhere
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                    continue
                arguments = [*node.args.args, *node.args.kwonlyargs]
                for argument in arguments:
                    if argument.annotation is None:
                        continue
                    rendered = ast.unparse(argument.annotation)
                    if "typer.Option" not in rendered and (
                        "typer.Argument" not in rendered
                    ):
                        continue
                    key = " ".join(rendered.split())
                    declarations.setdefault(key, []).append(
                        f"{path.name}:{argument.lineno}"
                    )
        offenders = {
            key: sites for key, sites in declarations.items() if len(sites) > 1
        }
        assert not offenders, (
            f"these option declarations are written more than once: "
            f"{ {k[:60]: v for k, v in offenders.items()} }; declare the "
            "shared ones in _app and annotate with the alias, so one flag "
            "cannot end up documented two ways"
        )


class TestRootPrefixFormatHasOneSpelling:
    """The root-prefix shape is written once, by the module that builds it.

    Four modules recognised the prefix by writing ``r[0-9a-f]{12}_`` out for
    themselves. The twelve is not a free choice: it is the builder's six-byte
    blake2b digest rendered as hex, restated as a digit count somewhere nothing
    connects it to the digest. Widening the digest leaves every reader matching
    a prefix the writer no longer produces, and nothing raises - an unmatched
    collection name just looks like it belongs to no root.

    The fourth copy is why this is checked by shape rather than by string. It
    was ``^r[0-9a-f]{12}_$`` where the others were ``^(r[0-9a-f]{12}_)``, so a
    scan comparing pattern text saw three copies and one unrelated pattern.
    """

    def test_no_module_but_the_builder_writes_the_prefix_shape(self) -> None:
        """Any regex naming a 12-hex run after ``r`` is another copy."""
        shape = re.compile(r"r\[0-9a-f\]\{\d+\}_")
        offenders: list[str] = []
        for path in _every_production_file():
            if path.name == "_store_models.py":
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except SyntaxError:  # pragma: no cover - parsed elsewhere
                continue
            offenders.extend(
                f"{path.name}:{node.lineno}"
                for node in ast.walk(tree)
                if isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and shape.search(node.value)
            )
        assert not offenders, (
            f"the root-prefix shape is written outside its builder at "
            f"{offenders}; use ROOT_COLLECTION_PREFIX_RE, or the digit count "
            "and the builder's digest size drift apart silently"
        )

    def test_the_pattern_matches_what_the_builder_emits(self) -> None:
        """The coupling itself, asserted rather than trusted.

        Proven able to fail: changing ``_ROOT_PREFIX_DIGEST_BYTES`` alone fails
        this, because the builder's output length moves and the pattern -
        derived from the same constant - moves with it only if the derivation
        is real. Hard-coding the pattern back to ``{12}`` fails it too.
        """
        from .._store_models import ROOT_COLLECTION_PREFIX_RE, root_collection_prefix

        emitted = root_collection_prefix(Path(tempfile.gettempdir()))
        assert ROOT_COLLECTION_PREFIX_RE.fullmatch(emitted), emitted
        assert ROOT_COLLECTION_PREFIX_RE.match(emitted + "vault")

    def test_the_delete_gate_rejects_a_trailing_newline(self) -> None:
        """``$`` accepts one; a gate guarding a wipe must not.

        The copy this replaced was ``$``-anchored and matched with ``match``,
        and ``$`` also matches immediately before a trailing newline - so a
        prefix ending in one passed the canonical check. The shared pattern is
        used with ``fullmatch``, which does not.

        Proven able to fail: swapping ``fullmatch`` for ``match`` in
        ``_is_canonical_prefix`` fails this on the newline assertion below.
        """
        from ..storage_ops import _is_canonical_prefix

        assert _is_canonical_prefix("r0123456789ab_")
        assert not _is_canonical_prefix("r0123456789ab_\n")
        assert not _is_canonical_prefix("")
        assert not _is_canonical_prefix("r")


class TestOperatorVerdictVocabularyHasOneHome:
    """The words and exit codes an operator sees are the service domain's.

    The service composes a verdict; the CLI walks its own signal ladder and
    reaches a finer state token - a dead pid told apart from a reused one,
    where the service says ``crashed`` for both. That difference is real and
    stays. What was duplicated is everything around it: three labels typed out
    in both places, and the broker-facing exit codes written as bare integers
    in the entry point while the domain module defined them as constants and
    documented them as a contract.

    Both costs are quiet. Two wordings for one condition means the same daemon
    is explained differently depending on which path an operator arrived
    through. A bare ``4`` in a return tuple is unsearchable, so a contract
    change reaches the constant and misses every literal spelling of it.
    """

    #: Verdict exit codes, and the module allowed to write them as integers.
    _CONTRACT_OWNER = "_status.py"
    _CONTRACT_CODES: ClassVar[frozenset[int]] = frozenset({3, 5})

    def test_no_entry_point_respells_a_verdict_label(self) -> None:
        """A second spelling of a label the service already produces."""
        from ..serviceclient import _status

        owned = {
            _status.LABEL_WARMING,
            _status.LABEL_CRASHED_PORT_SILENT,
            _status.LABEL_CRASHED_HEARTBEAT_STALE,
        }
        offenders: list[str] = []
        for path in _every_production_file():
            if path.name == self._CONTRACT_OWNER:
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except SyntaxError:  # pragma: no cover - parsed elsewhere
                continue
            offenders.extend(
                f"{path.name}:{node.lineno} spells {node.value!r}"
                for node in ast.walk(tree)
                if isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and node.value in owned
            )
        assert not offenders, (
            f"an operator verdict label is spelled outside the service domain "
            f"at {offenders}; import it, so one condition cannot be described "
            "in two wordings depending on which surface reported it"
        )

    def test_the_status_renderer_names_its_exit_codes(self) -> None:
        """The renderer must not restate the contract as bare integers.

        Restricted to the codes that only ever mean a verdict. ``0`` and ``4``
        are excluded deliberately: they are ordinary integers that appear all
        over any module, so requiring a name for them would flag arithmetic
        and indices rather than the contract.
        """
        from ..cli import _status_render

        source = Path(_status_render.__file__).read_text(encoding="utf-8")
        tree = ast.parse(source)
        offenders: list[str] = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Return) or node.value is None:
                continue
            if not isinstance(node.value, ast.Tuple):
                continue
            offenders.extend(
                f"line {node.lineno} returns a bare {element.value}"
                for element in node.value.elts
                if isinstance(element, ast.Constant)
                and isinstance(element.value, int)
                and not isinstance(element.value, bool)
                and element.value in self._CONTRACT_CODES
            )
        assert not offenders, (
            f"the status renderer returns a verdict exit code as a literal: "
            f"{offenders}; use the EXIT_* constant, because a bare integer is "
            "unsearchable when the broker-facing contract changes"
        )


class TestSidecarKeysAreNamedNotSpelled:
    """A reserved sidecar key is written as a literal in exactly one module.

    The code side kept its keys in a module both the writer and the reader
    import. The vault side kept them private to the indexer, so the donor
    reader spelled them out again - and said so, calling itself a mirror of
    keys "private to the vault indexer, which owns the write side". The same
    function imported the code keys from their owner two lines above. A test
    made a third copy, and an integration test a fourth and fifth.

    A mirrored payload key fails in the worst available way: renaming one does
    not raise, it makes the reader's lookup return ``None``, every vault donor
    falls to ineligible, and vector reuse quietly stops. Every answer stays
    correct, there are just fewer of them, so no correctness test notices.

    Checked as literals rather than as names, because the mirror was never a
    shared name - it was the same string typed twice under two spellings
    (``_SCHEMA_KEY`` here, ``_VAULT_POINT_SCHEMA_KEY`` there).
    """

    #: Reserved sidecar keys and the one module each may be spelled in.
    _OWNERS: ClassVar[dict[str, str]] = {
        "__vault_point_schema__": "_vault_meta.py",
        "__vault_content_epoch__": "_vault_meta.py",
        "__code_embed_schema__": "_code_meta.py",
        "__code_content_epoch__": "_code_meta.py",
        "__code_membership_epoch__": "_code_meta.py",
    }

    def test_no_module_but_the_owner_spells_a_reserved_key(self) -> None:
        """A second spelling is a mirror, whatever name it is bound to."""
        offenders: list[str] = []
        for path in _every_production_file():
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except SyntaxError:  # pragma: no cover - parsed elsewhere
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.Constant):
                    continue
                if not isinstance(node.value, str):
                    continue
                owner = self._OWNERS.get(node.value)
                if owner is not None and path.name != owner:
                    offenders.append(
                        f"{path.name}:{node.lineno} spells {node.value!r} "
                        f"(owned by {owner})"
                    )
        assert not offenders, (
            f"a reserved sidecar key is spelled outside the module that owns "
            f"it: {offenders}; import the constant, because a renamed key does "
            "not raise - it silently makes every donor ineligible"
        )

    def test_the_reader_and_the_writer_share_one_object(self) -> None:
        """Not equal strings - the same constant, reached from both sides.

        Proven able to fail: rebinding either name in the donor reader to a
        fresh literal of the same text fails this on the identity assertion
        below, which equality would not catch.
        """
        from ..indexer import _donor_candidates, _vault_indexer, _vault_meta

        assert (
            _donor_candidates.VAULT_CONTENT_EPOCH_KEY
            is _vault_meta.VAULT_CONTENT_EPOCH_KEY
        )
        assert (
            _donor_candidates.VAULT_POINT_SCHEMA_KEY
            is _vault_meta.VAULT_POINT_SCHEMA_KEY
        )
        assert (
            _vault_indexer.VAULT_POINT_SCHEMA_KEY is _vault_meta.VAULT_POINT_SCHEMA_KEY
        )
        assert _vault_indexer.VAULT_POINT_SCHEMA is _vault_meta.VAULT_POINT_SCHEMA


class TestManagedLogFiltersHaveOneRule:
    """Which log filters exist, and what makes one empty, is stated once.

    The CLI verb asked the logging domain. The HTTP route had its own copy,
    reading the two query parameters and applying its own strip-and-drop-empty
    test - the same rule, restated at the boundary, in a module whose whole
    contents were that one function.

    Nothing failed while they agreed. The cost is that they had to keep
    agreeing by hand: a third filter, or a change to what counts as empty,
    lands in one and not the other, and then a whitespace-only ``--contains``
    filters nothing over HTTP and everything from the CLI, for the same
    service and the same contract.
    """

    def test_only_the_logging_domain_builds_the_filter_mapping(self) -> None:
        """A second builder of these keys is a second definition of the rule."""
        offenders: list[str] = []
        for path in _production_sources():
            if path.name == "logging_config.py":
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except SyntaxError:  # pragma: no cover - parsed elsewhere
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.Subscript):
                    continue
                target = node.slice
                if (
                    isinstance(node.value, ast.Name)
                    and "filter" in node.value.id.lower()
                    and isinstance(target, ast.Constant)
                    and target.value in {"job_id", "contains"}
                    and isinstance(node.ctx, ast.Store)
                ):
                    offenders.append(f"{path.name}:{node.lineno} sets {target.value!r}")
        assert not offenders, (
            f"a managed-log filter mapping is built outside the logging "
            f"domain at {offenders}; call managed_log_filters, so the HTTP "
            "boundary and the CLI cannot disagree about what an empty filter is"
        )

    def test_a_whitespace_only_filter_is_dropped_not_carried(self) -> None:
        """The behaviour both copies happened to share, pinned to one home.

        Proven able to fail: dropping the ``.strip()`` test so any truthy
        string is kept fails this on the whitespace assertion below - which is
        the divergence a second copy would eventually introduce, since a bare
        ``if job_id:`` reads as obviously correct.
        """
        from ..logging_config import managed_log_filters

        assert managed_log_filters(job_id="   ", contains="\t") == {}
        assert managed_log_filters(job_id="  j1  ") == {"job_id": "j1"}
        assert managed_log_filters() == {}
        # "0" is falsy-looking to a careless rewrite but is a real filter.
        assert managed_log_filters(contains="0") == {"contains": "0"}


class TestNoFacadeReExportServesOnlyTests:
    """A package ``__init__`` re-exports a private name only if production reads it.

    Twenty-eight such entries had accumulated across the ``cli`` and ``server``
    packages, and not one had a production reader by any route. Production
    already imported each from the module that owns it, so the facade entry
    existed for tests alone - and a symbol reachable only that way tells you
    nothing about the code that ships, while making the package look like the
    home of behaviour defined elsewhere.

    Reads are resolved, not guessed, because two shapes count and missing
    either one gives the wrong answer in opposite directions. A from-import
    must resolve to EXACTLY the facade package. An attribute read must go
    through a name the AST shows bound to that same package - the discipline
    ``server`` uses deliberately, where submodules reach mutable globals via
    ``import vaultspec_rag.server as _m`` so a rebind is observed. Thirty-two
    ``server`` entries are load-bearing for that reason and must survive this.

    Scoped to private names. A public name in a package ``__init__`` is API
    for consumers outside this tree, and no internal reader is expected.
    """

    @staticmethod
    def _facade_reads() -> set[tuple[str, str]]:
        """Return every ``(package, name)`` production reaches through a facade."""
        reads: set[tuple[str, str]] = set()
        for path in _every_production_file():
            module = _module_name(path)
            is_package = path.name == "__init__.py"
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except SyntaxError:  # pragma: no cover - parsed elsewhere
                continue
            aliases: dict[str, str] = {}
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for entry in node.names:
                        if entry.name.startswith("vaultspec_rag"):
                            bound = entry.asname or entry.name.split(".")[0]
                            aliases[bound] = entry.name
                    continue
                if not isinstance(node, ast.ImportFrom):
                    continue
                target = _absolute_import(node, module, is_package)
                for entry in node.names:
                    reads.add((target, entry.name))
                    aliases[entry.asname or entry.name] = f"{target}.{entry.name}"
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.Attribute)
                    and isinstance(node.value, ast.Name)
                    and node.value.id in aliases
                ):
                    reads.add((aliases[node.value.id], node.attr))
        return reads

    def test_no_private_re_export_lacks_a_production_reader(self) -> None:
        reads = self._facade_reads()
        offenders: list[str] = []
        for path in _every_production_file():
            if path.name != "__init__.py":
                continue
            package = _module_name(path)
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except SyntaxError:  # pragma: no cover - parsed elsewhere
                continue
            used_here = {
                node.id for node in ast.walk(tree) if isinstance(node, ast.Name)
            } | {
                node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)
            }
            for node in ast.walk(tree):
                if not isinstance(node, ast.ImportFrom) or not (node.module or ""):
                    continue
                for entry in node.names:
                    name = entry.asname or entry.name
                    if not name.startswith("_") or name.startswith("__"):
                        continue
                    if name in used_here:
                        continue
                    if (package, name) in reads:
                        continue
                    offenders.append(f"{package}.{name} (line {node.lineno})")
        assert not offenders, (
            f"these private names are re-exported with no production reader: "
            f"{offenders}; import them from the module that owns them and "
            "delete the entry, so a test cannot be the only reason one exists"
        )


class TestNoSymbolKeptAliveForTests:
    """No private production symbol exists only because a test calls it.

    ``CodebaseIndexer`` carried ``_resolve_operation_policy`` and
    ``resolve_policy_snapshot`` with byte-identical bodies forwarding to the
    same collaborator. Production used the public one; fourteen test call
    sites used the private one. So the path the tests exercised was not the
    path production ran - which is the whole reason the rule forbids keeping a
    symbol alive for tests.
    """

    #: Client-transport calls that reach a real service route this project's
    #: own CLI has not adopted yet. They are not test conveniences duplicating
    #: a production path - each covers a capability no production caller can
    #: otherwise reach - so deleting them would drop client coverage of a live
    #: route. An entry needs that justification, not merely a passing test.
    _CLIENT_SURFACE: ClassVar[dict[str, str]] = {
        "_try_http_create_job": (
            "creates a job with start_paused and an idempotency key; "
            "_try_http_reindex, the path the CLI uses, has neither parameter, "
            "so no production caller can create a paused job"
        ),
    }

    def test_no_private_symbol_is_reachable_only_from_tests(self) -> None:
        import ast
        import collections
        import re

        definitions: dict[str, list[str]] = {}
        production: list[str] = []
        for path in _production_sources():
            text = path.read_text(encoding="utf-8")
            tree = ast.parse(text)
            # An __all__ listing is a declaration of intent, not a use.
            # Counting it as one hid an exported symbol that nothing imported
            # and only tests called - the case this test exists to catch.
            exported = [
                (node.lineno, node.end_lineno or node.lineno)
                for node in ast.walk(tree)
                if isinstance(node, ast.Assign)
                and any(
                    isinstance(target, ast.Name) and target.id == "__all__"
                    for target in node.targets
                )
            ]
            production.append(
                "\n".join(
                    line
                    for number, line in enumerate(text.split("\n"), start=1)
                    if not any(lo <= number <= hi for lo, hi in exported)
                )
            )
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
                    and node.name.startswith("_")
                    and not node.name.startswith("__")
                ):
                    definitions.setdefault(node.name, []).append(
                        f"{path.relative_to(_PACKAGE_ROOT).as_posix()}:{node.lineno}"
                    )

        tests_dir = _PACKAGE_ROOT / "tests"
        test_blob = "\n".join(
            p.read_text(encoding="utf-8") for p in tests_dir.rglob("*.py")
        )
        production_blob = "\n".join(production)

        # Count identifiers once per blob rather than scanning both blobs once
        # per symbol. A `\b`-anchored search for an identifier matches exactly
        # the `\w+` tokens equal to it, so the tally is the same one the
        # per-symbol regex produced - but it is read off a dict instead of
        # re-walking megabytes of source for every name. The old shape was
        # quadratic in a way that grew with the codebase, and at ~1600 private
        # symbols over ~7 MB of source it cost over two minutes on its own.
        production_mentions = collections.Counter(re.findall(r"\w+", production_blob))
        test_mentions = collections.Counter(re.findall(r"\w+", test_blob))
        orphans = {
            name: sites
            for name, sites in definitions.items()
            # every production mention minus the definition lines themselves
            if production_mentions[name] - len(sites) == 0 and test_mentions[name]
        }

        unexplained = {
            name: sites
            for name, sites in orphans.items()
            if name not in self._CLIENT_SURFACE
        }
        assert not unexplained, (
            f"private symbol(s) reachable only from tests: {unexplained}. "
            "Delete them and repoint the tests at the production entry point - "
            "a test-only path proves nothing about the path production runs"
        )


class TestSchemaDeclarationsAreNotCopied:
    """A payload-index declaration lives in ``store_schema``, nowhere else.

    ``_store_search._build_document_filter`` re-listed the six document
    keyword indexes its own docstring said it must take from the schema. A
    keyword index added to the schema would have been rejected there as an
    unknown filter key - logged as a warning, the filter silently dropped, and
    the search returning UNFILTERED results rather than failing.
    """

    def test_no_module_relists_a_schema_index_set(self) -> None:
        from .. import store_schema

        declared = {
            name: frozenset(getattr(store_schema, name))
            for name in dir(store_schema)
            if name.endswith(("_KEYWORD_INDEXES", "_INTEGER_INDEXES"))
        }
        assert declared, "store_schema declares no index sets; has it moved?"

        import ast

        offenders: list[str] = []
        for path in _production_sources():
            if path.name == "store_schema.py":
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Set | ast.Tuple | ast.List):
                    continue
                literal = {
                    element.value
                    for element in node.elts
                    if isinstance(element, ast.Constant)
                    and isinstance(element.value, str)
                }
                if len(literal) < 2 or len(literal) != len(node.elts):
                    continue
                for name, values in declared.items():
                    if literal == values:
                        rel = path.relative_to(_PACKAGE_ROOT).as_posix()
                        offenders.append(f"{rel}:{node.lineno} == {name}")
        assert not offenders, (
            f"schema index set copied at {offenders}; import it from "
            "store_schema so a new index reaches every reader"
        )


class TestFinalizationPhaseWalkHasOneCopy:
    """The durable metadata-publication transition exists once, on the base.

    ``CodeRunCheckpoint`` and ``DocumentRunCheckpoint`` each carried the same
    phase walk: INGESTING to STALE_RECONCILED, bail unless STALE_RECONCILED,
    publish, advance to METADATA_PUBLISHED. Only the publish call differed.

    The duplicated part is a DURABLE transition - it survives a restart - so
    two copies could disagree about when metadata is publishable and the
    disagreement would persist across runs. The base already declared
    ``_content_kind`` and ``_kind_label`` for exactly this, and its docstring
    already promised subclasses inherit the generation-publication decisions.
    """

    def test_only_the_base_advances_the_finalization_phase(self) -> None:
        # Keys on STALE_RECONCILED: it appears only in the walk that advances
        # through it, so a second mention means a second copy of the durable
        # transition. Reading the phase elsewhere is fine and stays uncaught.
        offenders = [
            f"{path.relative_to(_PACKAGE_ROOT).as_posix()}:{number}"
            for path in _production_sources()
            if path.name != "_checkpoint_common.py"
            for number, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), start=1
            )
            if "FinalizationPhase.STALE_RECONCILED" in line
        ]
        assert not offenders, (
            f"the finalization phase walk is duplicated at {offenders}; call "
            "RunCheckpointBase.publish_metadata_transition so the durable "
            "transition has one definition"
        )

    def test_each_subclass_supplies_only_its_publish_call(self) -> None:
        import inspect

        from ..indexer._checkpoint_common import RunCheckpointBase
        from ..indexer._document_checkpoint import DocumentRunCheckpoint
        from ..indexer._run_checkpoint import CodeRunCheckpoint

        assert hasattr(RunCheckpointBase, "publish_metadata_transition")
        for cls in (CodeRunCheckpoint, DocumentRunCheckpoint):
            source = inspect.getsource(cls.publish_metadata)
            assert "publish_metadata_transition" in source, (
                f"{cls.__name__}.publish_metadata must go through the shared "
                "transition rather than walking the phases itself"
            )
            # The label the envelope emits is built from _kind_label, so each
            # subclass must still declare the one it had.
            assert cls._kind_label in {"code", "document"}


class TestShortfallProseHasOneHome:
    """The words warning an operator their index is short have one source.

    Three renderers described the same deficits: two on the command line and
    one in the service summary. They had already drifted - the summary named
    the point shortfall alone, so a publication covering a fraction of the
    files it named reached an agent as an unqualified count, and the two
    surfaces disagreed on the noun. Both the consequence clause and the
    remediation command now live beside the figures they describe.
    """

    def test_only_the_breadth_module_spells_the_consequence(self) -> None:
        from .._index_breadth import SHORTFALL_CONSEQUENCE

        offenders = [
            f"{path.name}:{number}"
            for path in _production_sources()
            if path.name != "_index_breadth.py"
            for number, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), start=1
            )
            if "not evidence that no such" in line
        ]
        assert not offenders, (
            f"the shortfall consequence is spelled again at {offenders}; import "
            f"SHORTFALL_CONSEQUENCE ({SHORTFALL_CONSEQUENCE!r}) so both surfaces "
            "cannot describe one deficit differently"
        )

    def test_only_the_breadth_module_spells_the_remediation(self) -> None:
        from .._index_breadth import SHORTFALL_REMEDIATION

        offenders = [
            f"{path.name}:{number}"
            for path in _production_sources()
            if path.name != "_index_breadth.py"
            for number, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), start=1
            )
            if SHORTFALL_REMEDIATION in line
        ]
        assert not offenders, (
            f"the shortfall remediation is spelled again at {offenders}; import "
            "SHORTFALL_REMEDIATION so an operator is never sent to a command a "
            "rename removed from one copy"
        )

    def test_every_surface_walks_both_shortfall_kinds(self) -> None:
        """Neither renderer may read one key and stay blind to the other."""
        import inspect

        from ..cli._search import _render_shortfall_warnings
        from ..server._routes import _search_summary

        for renderer in (_render_shortfall_warnings, _search_summary):
            source = inspect.getsource(renderer)
            assert "shortfall_warnings" in source, (
                f"{renderer.__name__} must walk the shared reader; keying on one "
                "shortfall name is how the summary went silent on file breadth"
            )
            assert '"file_shortfall"' not in source, (
                f"{renderer.__name__} reaches for a shortfall key directly, which "
                "is what lets one kind be handled and the other forgotten"
            )


class TestBackoffMathHasOneHome:
    """Capped exponential backoff is computed in ``_backoff`` and nowhere else.

    Five sites grew their own: the file-replacement ladder, the watcher retry
    policy, and three copies inside the watcher's replacement scheduler. They
    had already diverged where it counts - the retry policy clamped the
    exponent so a long failure streak could not overflow, and the three
    scheduler copies, written from the same idea, did not.
    """

    def test_only_the_backoff_module_raises_two_to_a_power(self) -> None:
        """A new capped exponential anywhere else is a new copy."""
        offenders: list[str] = []
        for path in _production_sources():
            if path.name == "_backoff.py":
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except SyntaxError:  # pragma: no cover - parsed elsewhere
                continue
            offenders.extend(
                f"{path.name}:{node.lineno}"
                for node in ast.walk(tree)
                if isinstance(node, ast.BinOp)
                and isinstance(node.op, ast.Pow)
                and isinstance(node.left, ast.Constant)
                and node.left.value in (2, 2.0)
            )
        assert not offenders, (
            f"base-2 exponentiation outside the backoff module at {offenders}; "
            "call capped_exponential or jittered_backoff so the exponent clamp "
            "cannot be present in one copy and absent in the next"
        )

    def test_the_replacement_constants_feed_one_scheduler(self) -> None:
        """Only ``defer_replacement`` may turn the streak into a deadline."""
        from .. import watcher

        source = Path(watcher.__file__).read_text(encoding="utf-8")
        uses = [
            number
            for number, line in enumerate(source.splitlines(), start=1)
            if "_WATCH_REPLACEMENT_BACKOFF_BASE_SECONDS" in line
            and not line.startswith("_WATCH_REPLACEMENT_BACKOFF_BASE_SECONDS")
        ]
        assert len(uses) == 1, (
            f"the replacement backoff base is read at {uses}; exactly one "
            "reader (defer_replacement) may exist, or the streak increment and "
            "the deadline drift apart again"
        )

    def test_a_long_failure_streak_returns_the_cap_instead_of_overflowing(
        self,
    ) -> None:
        """The defect the three scheduler copies carried.

        ``2 ** (streak - 1)`` builds an integer before the float multiply, so a
        streak past 1024 raised ``OverflowError`` instead of returning the cap
        - reachable after about eight and a half hours of sustained
        replacement failure at the thirty-second cap.

        Proven able to fail: dropping the ``min(exponent, _MAX_EXPONENT)``
        clamp in ``capped_exponential`` fails this test on the ``pytest.fail``
        below, which is why the overflow is caught rather than left to error
        the test out.
        """
        from .._backoff import capped_exponential

        for streak in (1025, 100_000):
            try:
                delay = capped_exponential(streak - 1, base=1.0, cap=30.0)
            except OverflowError as exc:
                pytest.fail(f"streak {streak} overflowed instead of capping: {exc}")
            assert delay == 30.0

    def test_jitter_cannot_push_a_wait_past_the_cap(self) -> None:
        """A cap is a cap; an upward draw must not exceed it.

        The replacement ladder previously applied jitter to an already-capped
        nominal without re-clamping, so its longest sleep ran a quarter over
        the maximum it declared.

        Proven able to fail: returning ``max(0.0, nominal + jitter)`` without
        the outer ``min(cap, ...)`` fails this test on the upper-bound
        assertion below.
        """
        from .._backoff import jittered_backoff

        for exponent in range(0, 12):
            for unit in (0.0, 0.5, 1.0):
                delay = jittered_backoff(
                    exponent, base=0.005, cap=0.15, fraction=0.25, random_unit=unit
                )
                assert 0.0 <= delay <= 0.15, (exponent, unit, delay)


class TestNoCompatibilityAliases:
    """A canonical name is imported and used, never rebound under a second one.

    Fourteen module-level aliases had accumulated - ``_WIN_CREATE_NO_WINDOW =
    WIN_CREATE_NO_WINDOW`` and friends - each giving one fact a second name in
    a module that did not own it. Two carried comments admitting the motive:
    "Kept under the existing names so importers and tests are unaffected" and
    "Compatibility aliases for the established focused rollback tests". An
    alias reads as an abstraction, hides the real owner, and survives every
    later refactor, so there must not be one.

    The scan is structural rather than name-based, because the next alias will
    not be spelled like the last one.
    """

    #: Empty, and meant to stay that way. It is the staging mechanism, not a
    #: permission list: an entry records an alias a cleanup has not reached
    #: yet, and the companion test below fails once that alias is gone so the
    #: entry cannot outlive it and quietly re-permit the name.
    KNOWN: ClassVar[frozenset[tuple[str, str]]] = frozenset()

    def test_no_module_rebinds_an_imported_name(self) -> None:
        offenders: list[str] = []
        for path in _production_sources():
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except SyntaxError:  # pragma: no cover - parsed elsewhere
                continue
            imported: set[str] = set()
            for node in tree.body:
                if isinstance(node, ast.ImportFrom):
                    imported.update(a.asname or a.name for a in node.names)
                elif isinstance(node, ast.Import):
                    imported.update(
                        a.asname or a.name.split(".")[0] for a in node.names
                    )
            for node in tree.body:
                if not (
                    isinstance(node, ast.Assign)
                    and len(node.targets) == 1
                    and isinstance(node.targets[0], ast.Name)
                ):
                    continue
                target = node.targets[0].id
                value = node.value
                # X = Y, or X = mod.Y, where the right-hand side is imported.
                rebinds = (isinstance(value, ast.Name) and value.id in imported) or (
                    isinstance(value, ast.Attribute)
                    and isinstance(value.value, ast.Name)
                    and value.value.id in imported
                )
                if not rebinds or (path.name, target) in self.KNOWN:
                    continue
                offenders.append(
                    f"{path.name}:{node.lineno} {target} = {ast.unparse(value)}"
                )
        assert not offenders, (
            f"compatibility aliases at {offenders}; import the canonical name "
            "and use it, rather than giving one fact a second name in a module "
            "that does not own it"
        )

    def test_every_allowlisted_alias_still_exists(self) -> None:
        """The allowlist must not outlive what it allows.

        An entry left behind after its alias is gone would silently permit a
        fresh alias of that name in that module. Vacuously true while KNOWN is
        empty, which is the intended resting state.
        """
        stale = [
            f"{module}:{name}"
            for module, name in sorted(self.KNOWN)
            if not any(
                path.name == module and f"{name} = " in path.read_text(encoding="utf-8")
                for path in _production_sources()
            )
        ]
        assert not stale, (
            f"allowlist entries with no alias behind them: {stale}; drop them "
            "so the scan covers those modules fully again"
        )


class TestAtomicJsonPublishHasOneWriter:
    """Publishing a JSON document goes through ``write_json_atomically``.

    Thirteen sites wrote the sequence out: serialize, write a temp sibling,
    replace. Two had learned to unlink the temp in a ``finally`` and to give
    it a name two writers could not collide on; the other eleven had not, so a
    failed write or a replace outlasting the sharing ladder left the temp on
    disk forever. The suite already asserted no temp survives in several
    places, which is exactly how the careful and naive versions sat side by
    side without the gap being visible.
    """

    #: Streams its sidecar entry by entry and fsyncs the handle, so the whole
    #: document is never held in memory. That is a different operation, not a
    #: copy of this one: it exists because the code sidecar can be large.
    STREAMING: ClassVar[str] = "_code_meta.py"

    #: Writes its recovery marker to a temp whose NAME a reaper globs, so the
    #: spelling is a contract rather than an implementation detail. Delegating
    #: it would leave the sweeper matching nothing and its test vacuously
    #: green. Its durability step is shared; only the naming is its own.
    NAMED_TEMP_CONTRACT: ClassVar[str] = "watcher_retry.py"

    def test_no_function_hand_rolls_the_serialize_and_replace(self) -> None:
        """Structural, not textual: the first version of this scan missed four.

        It keyed on ``json.dumps`` within a few lines of a replace, so it saw
        neither the ``json.dump(stream)`` form nor the sites whose serialize
        and replace sat further apart. Both shapes were live. This walks each
        function and asks whether it does BOTH, at any distance and in either
        spelling.
        """
        offenders: list[str] = []
        for path in _production_sources():
            if path.name in {
                "_atomic_write.py",
                self.STREAMING,
                self.NAMED_TEMP_CONTRACT,
            }:
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except SyntaxError:  # pragma: no cover - parsed elsewhere
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                    continue
                serializes = False
                replaces = False
                for inner in ast.walk(node):
                    if not isinstance(inner, ast.Call):
                        continue
                    func = inner.func
                    if (
                        isinstance(func, ast.Attribute)
                        and func.attr in {"dump", "dumps"}
                        and isinstance(func.value, ast.Name)
                        and func.value.id == "json"
                    ):
                        serializes = True
                    if isinstance(func, ast.Name) and func.id in {
                        "replace_atomically",
                        "replace_durably",
                    }:
                        replaces = True
                if serializes and replaces:
                    offenders.append(f"{path.name}:{node.lineno} {node.name}")
        assert not offenders, (
            f"hand-rolled atomic JSON publish at {offenders}; call "
            "write_json_atomically so the temp file is named without collision "
            "and removed when the write or the replace fails"
        )

    def test_the_directory_fsync_has_one_implementation(self) -> None:
        """Forcing a directory entry to disk belongs to ``_atomic_write``.

        A second copy no-opped on Windows, so a crash-recovery record got a
        replace with no write-through on the platform this project targets
        first - the weaker half of a guarantee its own name promised. A third
        synced freshly created directories, a different purpose built from the
        identical three syscalls.

        Keyed on the shape only a directory sync has: opened with a bare
        ``os.O_RDONLY`` and fsynced by descriptor. A file sync passes
        ``stream.fileno()``, and a file opened for writing ORs its flags, so
        neither matches. Two looser predicates were tried first and both
        flagged modules that merely open a file - one on ``os.O_RDONLY``
        appearing anywhere in a line, one on any ``os.open`` plus any
        descriptor fsync.
        """

        def _opens_a_directory(call: ast.Call) -> bool:
            if not _is_attr_call(call, "os", "open") or len(call.args) != 2:
                return False
            flags = call.args[1]
            return (
                isinstance(flags, ast.Attribute)
                and flags.attr == "O_RDONLY"
                and isinstance(flags.value, ast.Name)
                and flags.value.id == "os"
            )

        offenders: list[str] = []
        for path in _production_sources():
            if path.name == "_atomic_write.py":
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except SyntaxError:  # pragma: no cover - parsed elsewhere
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                    continue
                calls = [
                    inner for inner in ast.walk(node) if isinstance(inner, ast.Call)
                ]
                opens_directory = any(_opens_a_directory(call) for call in calls)
                syncs_descriptor = any(
                    _is_attr_call(call, "os", "fsync")
                    and call.args
                    and isinstance(call.args[0], ast.Name)
                    for call in calls
                )
                if opens_directory and syncs_descriptor:
                    offenders.append(f"{path.name}:{node.lineno} {node.name}")
        assert not offenders, (
            f"a directory fsync outside _atomic_write at {offenders}; call "
            "fsync_directory, which replace_durably also uses, so the Windows "
            "no-op and the POSIX sync are decided in one place"
        )

    def test_the_temp_file_is_removed_when_the_replace_fails(self) -> None:
        """The defect the eleven naive copies carried.

        Proven able to fail: dropping the ``finally`` in
        ``write_json_atomically`` fails this test on the leftovers assertion
        below, not on a crash.
        """
        from unittest.mock import patch

        from .. import _atomic_write

        directory = Path(tempfile.mkdtemp())
        target = directory / "sidecar.json"

        def _refuse(*_args: object, **_kwargs: object) -> None:
            raise OSError(28, "No space left on device")

        with (
            patch.object(_atomic_write, "replace_atomically", _refuse),
            pytest.raises(OSError, match="No space left"),
        ):
            _atomic_write.write_json_atomically(target, {"a": 1})

        leftovers = sorted(p.name for p in directory.iterdir())
        assert leftovers == [], f"temp file survived a failed replace: {leftovers}"

    def test_the_temp_name_cannot_collide_between_writers(self) -> None:
        """Two writers of one target must not choose the same temp path.

        ``path.with_suffix(".tmp")`` gave them the same name, and gave anyone
        watching the directory a predictable one to pre-plant.

        Proven able to fail: replacing the random component with a constant
        fails this test on the distinctness assertion below.
        """
        from .. import _atomic_write

        directory = Path(tempfile.mkdtemp())
        target = directory / "sidecar.json"
        seen: set[str] = set()
        real_replace = _atomic_write.replace_atomically

        def _capture(source: Path | str, destination: Path | str) -> None:
            seen.add(Path(str(source)).name)
            real_replace(source, destination)

        with patch.object(_atomic_write, "replace_atomically", _capture):
            for index in range(8):
                _atomic_write.write_json_atomically(target, {"n": index})

        assert len(seen) == 8, f"temp names repeated across writers: {sorted(seen)}"
        assert all(name.startswith(".sidecar.json.") for name in seen), sorted(seen)


class TestOperatorCommandsHaveOneSpelling:
    """A command we tell an operator to run is spelled in one place.

    A remediation line is an instruction someone pastes into a shell, so every
    flag in it promises that flag exists. ``server jobs`` once took
    ``--running``; the option became ``--state active`` and two tests now
    exist for no reason other than asserting the old spelling stays gone. A
    guard against a renamed flag reappearing is a guard against copies that
    were missed the first time.
    """

    def test_no_module_builds_its_own_port_option(self) -> None:
        """Four modules computed this one conditional; three identically.

        Proven able to fail: reintroducing the inline conditional in any
        module fails this test on the offender list below.
        """
        offenders = [
            f"{path.name}:{number}"
            for path in _production_sources()
            if path.name != "_operator_commands.py"
            for number, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), start=1
            )
            if '" --port {' in line or '" --port %' in line
        ]
        assert not offenders, (
            f"a hand-built --port option at {offenders}; call port_option so "
            "one rule decides when a port is known enough to name"
        )

    def test_no_module_spells_the_jobs_command(self) -> None:
        """Its flags are the ones with a demonstrated history of changing."""
        offenders = [
            f"{path.name}:{number}"
            for path in _production_sources()
            if path.name != "_operator_commands.py"
            for number, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), start=1
            )
            if "vaultspec-rag server jobs " in line
        ]
        assert not offenders, (
            f"a hand-spelled server-jobs command at {offenders}; call "
            "server_jobs_command so a renamed flag changes in one place"
        )

    def test_no_module_spells_a_bare_status_or_start_command(self) -> None:
        """A command handed over as a whole string must come from the builder.

        Scoped to a string that IS the command, which is what a caller passes
        as a next action. A sentence that mentions the tool in passing is
        prose and keeps its own words; the sites that hand an operator
        something to run do not.
        """
        offenders: list[str] = []
        for path in _production_sources():
            if path.name == "_operator_commands.py":
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except SyntaxError:  # pragma: no cover - parsed elsewhere
                continue
            for node in ast.walk(tree):
                if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
                    continue
                text = node.value
                if text.startswith(
                    ("vaultspec-rag server status", "vaultspec-rag server start")
                ):
                    offenders.append(f"{path.name}:{node.lineno} {text!r}")
        assert not offenders, (
            f"a hand-spelled status/start command at {offenders}; call "
            "server_status_command or server_start_command so a renamed flag "
            "changes in one place"
        )

    def test_the_not_running_message_has_one_wording(self) -> None:
        """Ten modules carried this sentence verbatim.

        An operator meeting it from two different verbs must not be told two
        different things, and the command inside it has to survive a rename.
        """
        offenders = [
            f"{path.name}:{number}"
            for path in _production_sources()
            if path.name != "_operator_commands.py"
            for number, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), start=1
            )
            if "Service is not running. Start it with" in line
        ]
        assert not offenders, (
            f"the service-not-running sentence is spelled again at {offenders}; "
            "import SERVICE_NOT_RUNNING_MESSAGE"
        )

    def test_no_module_spells_an_index_command(self) -> None:
        """The index verb is a family, not a set of unrelated one-offs.

        Counting repeats made this look like it was not duplication - each of
        the thirteen sites named a different flag combination. What repeats is
        the VOCABULARY: the verb, its flag names and their order, and which
        source spellings exist.
        """
        offenders = [
            f"{path.name}:{number}"
            for path in _production_sources()
            if path.name != "_operator_commands.py"
            for number, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), start=1
            )
            if "vaultspec-rag index" in line
        ]
        assert not offenders, (
            f"a hand-spelled index command at {offenders}; call index_command "
            "so a renamed flag changes in one place"
        )

    def test_every_source_reaches_the_rebuild_remediation(self) -> None:
        """A source the flag accepts must be a source the operator is offered.

        The four spellings were hand-enumerated, so a new member of
        PublicSourceType would have been accepted by --type and silently
        missing from the rebuild remediation - the operator would never be
        told the command that fixes their index.

        Proven able to fail: pinning that remediation to a fixed list fails
        this test on the missing-source assertion below.
        """
        import inspect

        from .._source_types import PublicSourceType
        from ..cli import _index

        source = inspect.getsource(_index)
        rendered = {index_command(member, rebuild=True) for member in PublicSourceType}
        assert len(rendered) == len(PublicSourceType), (
            "two source types render the same rebuild command"
        )
        assert "for source in PublicSourceType" in source, (
            "the rebuild remediation must be derived from PublicSourceType, "
            "not enumerated, or a new source type is accepted by --type and "
            "never offered to the operator"
        )

    def test_the_renamed_flag_is_not_reachable(self) -> None:
        """``--running`` was replaced by ``--state active`` and must stay gone.

        The builder is the only thing that can emit this command now, so this
        asks the builder rather than scanning for a string: no argument
        combination may produce the retired option.
        """
        from .._operator_commands import server_jobs_command

        rendered = [
            server_jobs_command(),
            server_jobs_command(8766),
            server_jobs_command(8766, failed=True),
            server_jobs_command(8766, index="code"),
            server_jobs_command(8766, state="finished"),
        ]
        assert all("--running" not in command for command in rendered), rendered
        assert all(
            command.startswith("vaultspec-rag server jobs") for command in rendered
        )


class TestSearchFilterVocabularyHasOneHome:
    """Which payload keys a search may filter on is declared once.

    ``store_schema`` opens by claiming the shape "cannot drift between the
    writer, the reader, the wire, and the reference" - and that held for
    ``store.py``, which builds payloads and index sets from it. The FILTER side
    did not: three builders and a validator each re-listed the key names.

    The document filter learned why first. It re-listed its keys, so a keyword
    index the schema had added was rejected as unknown and the condition was
    dropped - handing back UNFILTERED results to a caller who had asked to
    narrow. Its fix stopped at that one builder; the code filter and the
    validator kept their copies until now.
    """

    def test_every_filter_key_is_backed_by_an_index(self) -> None:
        """A filter key with no index is a full scan or silently unsupported.

        Proven able to fail: adding an unindexed name to any of the three
        tuples fails this test on the unbacked list below.
        """
        from .. import store_schema

        for keys, indexes, label in (
            (store_schema.CODE_FILTER_KEYS, store_schema.CODE_KEYWORD_INDEXES, "code"),
            (
                store_schema.VAULT_FILTER_KEYS,
                store_schema.VAULT_KEYWORD_INDEXES,
                "vault",
            ),
            (
                store_schema.DOCUMENT_FILTER_KEYS,
                store_schema.DOCUMENT_KEYWORD_INDEXES,
                "document",
            ),
        ):
            unbacked = [
                key
                for key in keys
                if store_schema.FILTER_KEY_PAYLOAD_FIELD.get(key, key) not in indexes
            ]
            assert not unbacked, (
                f"{label} filter keys with no payload index behind them: "
                f"{unbacked}; index the field or drop it from the vocabulary"
            )

        # DOCUMENT_QUERY_FILTER_KEYS splats the argument set, so containment
        # between the two holds by construction and asserting it would prove
        # nothing. What is NOT guaranteed is that the keys it adds on top are
        # indexed - the loop above only walks the argument set - so that is
        # the assertion worth making.
        unbacked_query_keys = [
            key
            for key in store_schema.DOCUMENT_QUERY_FILTER_KEYS
            if key not in store_schema.DOCUMENT_KEYWORD_INDEXES
        ]
        assert not unbacked_query_keys, (
            f"query-token filter keys with no payload index: "
            f"{unbacked_query_keys}; the store will reject them as unknown"
        )

    def test_no_module_relists_the_filter_vocabulary(self) -> None:
        """A collection literal holding the vocabulary is a second copy of it.

        Scoped to collection literals on purpose: these field names appear all
        over the search path as keyword arguments, payload keys and dataclass
        fields, and those are uses of one field, not a restatement of the set.
        What matters is a tuple or set that enumerates the vocabulary, because
        that is what gets consulted as a whitelist and then goes stale.
        """
        from .. import store_schema

        vocabularies = {
            "CODE_FILTER_KEYS": frozenset(store_schema.CODE_FILTER_KEYS),
            "VAULT_FILTER_KEYS": frozenset(store_schema.VAULT_FILTER_KEYS),
            "DOCUMENT_FILTER_KEYS": frozenset(store_schema.DOCUMENT_FILTER_KEYS),
            "DOCUMENT_QUERY_FILTER_KEYS": frozenset(
                store_schema.DOCUMENT_QUERY_FILTER_KEYS
            ),
        }
        offenders: list[str] = []
        for path in _production_sources():
            if path.name == "store_schema.py":
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except SyntaxError:  # pragma: no cover - parsed elsewhere
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.Tuple | ast.List | ast.Set):
                    continue
                literals = {
                    element.value
                    for element in node.elts
                    if isinstance(element, ast.Constant)
                    and isinstance(element.value, str)
                }
                if not literals:
                    continue
                for name, keys in vocabularies.items():
                    if keys <= literals:
                        offenders.append(f"{path.name}:{node.lineno} re-lists {name}")
        assert not offenders, (
            f"{offenders}; import the tuple from store_schema so a key added "
            "to the schema cannot be rejected as unknown by a stale copy"
        )

    def test_the_code_filter_admits_exactly_the_declared_keys(self) -> None:
        """The builder must read the schema, not a list of its own."""
        import inspect

        from .._store_search import _VaultSearchMixin

        source = inspect.getsource(_VaultSearchMixin._build_code_filter)
        assert "CODE_FILTER_KEYS" in source, (
            "the code filter must take its whitelist from store_schema, the "
            "same way the document filter does"
        )


class TestJsonOptionHasOneDeclaration:
    """Every verb's ``--json`` flag is declared in one place.

    Thirty-three verbs declared it for themselves and had reached four
    wordings and two declaration styles: the storage verbs were still on the
    pre-``Annotated`` form with a terser sentence, so ``--help`` described the
    same flag differently depending on which verb an operator ran it on.

    One wording is deliberately kept separate. The lifecycle verbs promise
    exactly one structured envelope on every exit path, success or failure -
    a stronger contract than "machine-readable output", not a reworded one.
    """

    def test_no_verb_spells_the_json_help_text(self) -> None:
        """Composing on the shared sentence is fine; restating it is not.

        Keyed on the exact canonical sentences rather than the words they
        start with: a first attempt matched any string opening "Emit one
        structured" and flagged a dry-run docstring that happens to begin the
        same way.
        """
        from ..cli._app import JSON_ENVELOPE_OPTION_HELP, JSON_OPTION_HELP

        sentences = (JSON_OPTION_HELP, JSON_ENVELOPE_OPTION_HELP)
        offenders = [
            f"{path.name}:{number}"
            for path in _production_sources()
            if path.name != "_app.py"
            for number, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), start=1
            )
            if any(f'"{sentence}' in line for sentence in sentences)
        ]
        assert not offenders, (
            f"a hand-written --json help string at {offenders}; annotate the "
            "parameter with JsonMode or JsonEnvelopeMode, or compose on "
            "JSON_OPTION_HELP when the verb has more to say"
        )

    def test_no_verb_builds_its_own_json_option(self) -> None:
        """A second ``typer.Option("--json", ...)`` is a second declaration."""
        offenders: list[str] = []
        for path in _production_sources():
            if path.name == "_app.py":
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except SyntaxError:  # pragma: no cover - parsed elsewhere
                continue
            for node in ast.walk(tree):
                if not (
                    isinstance(node, ast.Call)
                    and _is_attr_call(node, "typer", "Option")
                ):
                    continue
                if not any(
                    isinstance(arg, ast.Constant) and arg.value == "--json"
                    for arg in node.args
                ):
                    continue
                # Composing on a canonical constant is the supported way for a
                # verb to say more; restating the sentence is not.
                composes = any(
                    isinstance(inner, ast.Name)
                    and inner.id in {"JSON_OPTION_HELP", "JSON_ENVELOPE_OPTION_HELP"}
                    for inner in ast.walk(node)
                )
                if not composes:
                    offenders.append(f"{path.name}:{node.lineno}")
        assert not offenders, (
            f"a second --json option declaration at {offenders}; use the "
            "JsonMode / JsonEnvelopeMode annotations from _app"
        )

    def test_the_two_contracts_stay_distinct(self) -> None:
        """Flattening the lifecycle promise into the general one loses it.

        Proven able to fail: pointing JSON_ENVELOPE_OPTION_HELP at
        JSON_OPTION_HELP fails this test on the inequality below.
        """
        from ..cli._app import JSON_ENVELOPE_OPTION_HELP, JSON_OPTION_HELP

        assert JSON_ENVELOPE_OPTION_HELP != JSON_OPTION_HELP
        assert "one structured" in JSON_ENVELOPE_OPTION_HELP


class TestOneVocabularyHasOneType:
    """No two enums carry the same member set.

    ``ProvisionAction`` existed twice - once in the install front door, once in
    the qdrant runtime - with identical members, each docstring saying it
    "mirrors the project-wide sync vocabulary" that neither owned. Keeping the
    mirror aligned needed a six-entry translation whose every entry mapped a
    member onto the member of the same name.

    An identity map is the clearest signal two types are one type, and it has
    to be edited whenever either side gains a member: a missed edit raises
    ``KeyError`` the first time the new outcome occurs, on the least-tested
    path there is.
    """

    def test_no_two_enums_share_a_member_set(self) -> None:
        import collections

        by_members: collections.defaultdict[frozenset[str], list[str]] = (
            collections.defaultdict(list)
        )
        for path in _production_sources():
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except SyntaxError:  # pragma: no cover - parsed elsewhere
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.ClassDef):
                    continue
                if not any(
                    isinstance(base, ast.Name) and "Enum" in base.id
                    for base in node.bases
                ):
                    continue
                values = {
                    stmt.value.value
                    for stmt in node.body
                    if isinstance(stmt, ast.Assign)
                    and isinstance(stmt.value, ast.Constant)
                    and isinstance(stmt.value.value, str)
                }
                # Two-member enums are too small for a shared set to mean
                # anything; a boolean-ish pair collides by coincidence.
                if len(values) >= 3:
                    by_members[frozenset(values)].append(f"{path.name}:{node.name}")
        # tuple(), not sorted(): a list is unhashable, so the dict
        # comprehension raised TypeError instead of reporting - which only
        # showed up when a twin actually existed.
        twins = {
            tuple(sorted(members)): names
            for members, names in by_members.items()
            if len(names) > 1
        }
        assert not twins, (
            f"enums with identical member sets: {twins}; one vocabulary is one "
            "type, or the copies need a hand-written translation that goes "
            "stale the moment either side gains a member"
        )


class TestDesiredJobStateHasOneStatement:
    """The operator-intent vocabulary is stated by its enum and nowhere else.

    ``DesiredJobState`` has three members, and they were written out five
    times: the enum, two ``Literal`` aliases mirroring it for typing (one
    sharing the enum's own name), a runtime membership set in the HTTP route,
    and again inside that route's error sentence.

    The set was the one that mattered. The route already called
    ``DesiredJobState(state)`` two lines further down, so the enum was the
    real validator and the set was a pre-check restating it - a fourth member
    would have been accepted by the domain and rejected at the API boundary
    with ``invalid_desired_state``.
    """

    def test_no_module_relists_the_desired_states(self) -> None:
        from ..job_models import DesiredJobState

        members = frozenset(member.value for member in DesiredJobState)
        offenders: list[str] = []
        for path in _production_sources():
            if path.name == "job_models.py":
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except SyntaxError:  # pragma: no cover - parsed elsewhere
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.Tuple | ast.List | ast.Set):
                    continue
                literals = {
                    element.value
                    for element in node.elts
                    if isinstance(element, ast.Constant)
                    and isinstance(element.value, str)
                }
                if members <= literals:
                    offenders.append(f"{path.name}:{node.lineno}")
        assert not offenders, (
            f"the desired-state vocabulary is relisted at {offenders}; check "
            "membership against DesiredJobState so a new intent is not "
            "accepted by the domain and refused at the route"
        )

    def test_the_route_admits_exactly_the_declared_states(self) -> None:
        """Adding a member must widen the route with no edit to the route.

        Proven able to fail: restoring the literal set in ``_set_desired_state``
        fails the relist scan above, and pinning this assertion to today's
        three members would pass a stale check - so it asks the module for
        them instead.
        """
        import inspect

        from ..job_models import DesiredJobState
        from ..server import _routes

        source = inspect.getsource(_routes)
        assert "set(DesiredJobState)" in source, (
            "the route must test membership against the enum, not a literal set"
        )
        # The sentence an operator reads is built from the same members.
        assert all(
            f"'{member}'" in source or "for member in DesiredJobState" in source
            for member in DesiredJobState
        )


class TestStatusDirHasOneResolver:
    """The managed service directory is resolved in one place.

    Nine sites resolved it: five inline, plus named helpers in the manifest
    and the discovery client. They had settled on two spellings -
    ``Path(cfg.status_dir)`` and ``Path(str(cfg.status_dir))``. The attribute
    is a ``str``, so both are identical and the ``str()`` was defensive typing
    that spread by copying rather than by need.

    One resolver stays separate, and its own docstring says why:
    ``config._status_dir_path`` reads the environment DIRECTLY because it
    belongs to the layer that feeds the config. Every consumer goes through
    the config instead, so a ``--status-dir`` override on the command line is
    honoured - the manifest helper's docstring warned that reading the
    environment there would "silently ignore a --status-dir override and split
    the manifest from the rest of the service's durable state".
    """

    def test_no_module_resolves_the_status_dir_itself(self) -> None:
        """A consumer builds the path from the config, or it drifts.

        Proven able to fail: restoring the inline expression in any consumer
        fails this test on the offender list below.
        """
        offenders = [
            f"{path.name}:{number}"
            for path in _production_sources()
            if path.name != "config.py"
            for number, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), start=1
            )
            if "status_dir)" in line and ".expanduser()" in line
        ]
        assert not offenders, (
            f"the status directory is resolved inline at {offenders}; call "
            "config.managed_status_dir so a --status-dir override reaches "
            "every file the service keeps there"
        )

    def test_every_managed_path_sits_under_the_one_directory(self) -> None:
        """The files the service keeps must land in the same place.

        Splitting them is the failure the manifest helper's docstring
        describes: an override honoured by some writers and not others leaves
        durable state in two directories, one of which nothing reads.
        """
        from ..config import managed_status_dir
        from ..serviceclient._discovery import _status_file
        from ..storage_manifest import manifest_path

        root = managed_status_dir()
        for path in (_status_file(), manifest_path()):
            assert path.parent == root, (path, root)


class TestWorkspaceLayoutHasOneOwner:
    """Where the workspace keeps its files is declared once.

    ``.vaultspec`` was spelled thirty-one times across five modules, and the
    names inside it fared no better - ``rules`` seven times, ``mcps`` six,
    ``mcp-ownership.json`` four. Nothing owned the layout, so installing it,
    projecting it, uninstalling it and seeding a synthetic copy each carried
    their own idea of what it contains.

    Two of those ideas were the same six directories written out twice: the
    scaffolder's list and the topology projection's. A directory added to one
    and not the other is how a projected workspace comes out missing a tree
    the real one has - and the projection exists precisely to be a faithful
    copy.
    """

    def test_no_module_spells_a_workspace_path(self) -> None:
        offenders = [
            f"{path.name}:{number}"
            for path in _production_sources()
            if path.name != "_workspace_layout.py"
            for number, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), start=1
            )
            if '".vaultspec"' in line or '".vault"' in line
        ]
        assert not offenders, (
            f"a workspace path spelled inline at {offenders}; join the "
            "constants from _workspace_layout so the install, the projection "
            "and the uninstall cannot disagree about what a workspace is"
        )

    def test_the_projection_covers_what_the_scaffolder_creates(self) -> None:
        """The two lists must be one list, not two that happen to match.

        Proven able to fail: pinning either side to its own tuple fails this
        on the identity assertion below. Comparing today's six names would
        pass two hand-written lists for exactly as long as nobody edited one.
        """
        from .._workspace_layout import workspace_directories
        from ..commands._mcp_topology import _WORKSPACE_CONTAINERS

        assert tuple(_WORKSPACE_CONTAINERS) == tuple(workspace_directories())

        import inspect

        from ..commands import _workspace

        source = inspect.getsource(_workspace._ensure_workspace_dirs)
        assert "workspace_directories()" in source, (
            "the scaffolder must build from the shared tuple, or it and the "
            "projection drift the next time either gains a directory"
        )


class TestJobVocabulariesHaveOneStatement:
    """The job enums are the only statement of their own members.

    ``DesiredJobState`` was fixed three iterations ago and its siblings were
    not, because that pass looked at one enum instead of the shape. ``JobMode``
    existed twice - the domain ``StrEnum`` and a ``Literal`` of the same name
    in the service client, which the server's availability adapter imported in
    preference to the domain's. ``JobSource``'s four members were restated as
    a ``Literal`` in the jobs module, and the route enumerated ``JobMode``'s
    two members by hand rather than asking the enum.
    """

    def test_no_literal_restates_a_job_enum(self) -> None:
        """A ``Literal`` mirroring an enum is a second declaration of it."""
        from ..job_models import DesiredJobState, JobMode, JobSource

        vocabularies = {
            name: frozenset(member.value for member in enum)
            for name, enum in (
                ("JobMode", JobMode),
                ("JobSource", JobSource),
                ("DesiredJobState", DesiredJobState),
            )
        }
        offenders: list[str] = []
        for path in _production_sources():
            if path.name == "job_models.py":
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except SyntaxError:  # pragma: no cover - parsed elsewhere
                continue
            for node in ast.walk(tree):
                if not (
                    isinstance(node, ast.Subscript)
                    and isinstance(node.value, ast.Name)
                    and node.value.id == "Literal"
                ):
                    continue
                elements = (
                    node.slice.elts
                    if isinstance(node.slice, ast.Tuple)
                    else [node.slice]
                )
                literals = {
                    element.value
                    for element in elements
                    if isinstance(element, ast.Constant)
                    and isinstance(element.value, str)
                }
                for name, members in vocabularies.items():
                    if members and members == literals:
                        offenders.append(f"{path.name}:{node.lineno} restates {name}")
        assert not offenders, (
            f"{offenders}; annotate with the enum so a new member is legal "
            "everywhere at once instead of being refused by whichever mirror "
            "was not updated"
        )

    def test_no_route_enumerates_a_job_enum_by_hand(self) -> None:
        """Membership comes from the enum, so a new member widens the route.

        Proven able to fail: restoring either literal member set in the job
        routes fails this on the offender list below.
        """
        import inspect

        from ..server import _routes

        source = inspect.getsource(_routes)
        for enum_name in ("JobMode", "DesiredJobState"):
            assert f"set({enum_name})" in source, (
                f"the route must test membership against {enum_name} rather "
                "than listing its members, or a new member is accepted by the "
                "domain and refused at the API boundary"
            )


class TestNoTwoModulesGrewTheSameHelper:
    """No two unrelated modules define the same function with the same body.

    The other guards here catch a copy that keeps its shape (the structural
    scan) or one that keeps its name (the alias scan). This catches the case
    neither sees on its own: two modules with no import path between them,
    each having grown a helper of the same name and the same body, because
    neither could see the other's.

    "Unrelated" is resolved rather than guessed. An earlier version of this
    analysis matched module STEMS, so ``api`` importing ``.search`` looked
    like a link to ``search._searcher`` and hid pairs behind false ones; it
    also counted methods as functions, so a facade function looked like a copy
    of the method it delegates to. Both cost a real finding to a false one.
    """

    @staticmethod
    def _shape(node: ast.FunctionDef | ast.AsyncFunctionDef) -> tuple[str, int]:
        """Return a name-blind hash of *node*'s body, and its statement count."""
        body = [
            statement
            for statement in node.body
            if not (
                isinstance(statement, ast.Expr)
                and isinstance(statement.value, ast.Constant)
            )
        ]

        class _Blind(ast.NodeTransformer):
            def visit_Name(self, node: ast.Name) -> ast.AST:
                return ast.copy_location(ast.Name(id="_", ctx=node.ctx), node)

            def visit_Attribute(self, node: ast.Attribute) -> ast.AST:
                self.generic_visit(node)
                return ast.copy_location(
                    ast.Attribute(value=node.value, attr="_", ctx=node.ctx), node
                )

            def visit_Constant(self, node: ast.Constant) -> ast.AST:
                return ast.copy_location(ast.Constant(value=None), node)

            def visit_ExceptHandler(self, node: ast.ExceptHandler) -> ast.AST:
                # An ``except ... as`` alias is a bare string on the handler,
                # not a Name node, so the visitors above never reached it. Two
                # byte-identical bodies that spelled the caught exception
                # differently therefore hashed differently, and one such pair
                # sat undetected in the tree until a separate scan found it.
                self.generic_visit(node)
                node.name = "_" if node.name else None
                return node

        count = sum(
            1
            for _ in ast.walk(ast.Module(body=body, type_ignores=[]))
            if isinstance(_, ast.stmt)
        )
        blinded = ast.Module(
            body=[_Blind().visit(ast.parse(ast.unparse(s)).body[0]) for s in body],
            type_ignores=[],
        )
        return hashlib.sha256(ast.dump(blinded).encode()).hexdigest(), count

    @staticmethod
    def _reached_modules(tree: ast.Module, owner: list[str], package: str) -> set[str]:
        """Return every in-package module this one imports, at any nesting."""
        reached: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                reached.update(a.name for a in node.names if a.name.startswith(package))
                continue
            if not isinstance(node, ast.ImportFrom):
                continue
            if node.level:
                depth = len(owner) - (node.level - 1) if node.level > 1 else len(owner)
                base = owner[:depth]
                target = (
                    ".".join([*base, node.module]) if node.module else ".".join(base)
                )
            else:
                target = node.module or ""
            if target.startswith(package):
                reached.add(target)
                reached.update(f"{target}.{a.name}" for a in node.names)
        return reached

    def test_no_unrelated_pair_shares_a_name_and_a_body(self) -> None:
        package = "vaultspec_rag"
        imports: dict[str, set[str]] = {}
        defined: dict[str, list[tuple[str, int, str]]] = {}

        for path in _production_sources():
            relative = path.relative_to(_PACKAGE_ROOT).with_suffix("")
            module = ".".join(
                [package, *(p for p in relative.parts if p != "__init__")]
            )
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except SyntaxError:  # pragma: no cover - parsed elsewhere
                continue
            imports[module] = self._reached_modules(
                tree, module.split(".")[:-1], package
            )
            for node in ast.walk(tree):
                if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                    continue
                first = node.args.args[0].arg if node.args.args else ""
                if first in {"self", "cls"} or node.name.startswith("__"):
                    continue
                shape, count = self._shape(node)
                if count >= 3:
                    defined.setdefault(node.name, []).append(
                        (module, node.lineno, shape)
                    )

        def reaches(source: str, target: str, seen: set[str] | None = None) -> bool:
            seen = set() if seen is None else seen
            if source == target or target in imports.get(source, ()):
                return True
            if source in seen:
                return False
            seen.add(source)
            return any(
                reaches(step, target, seen)
                for step in imports.get(source, ())
                if step in imports
            )

        offenders: list[str] = []
        for name, sites in sorted(defined.items()):
            for index, (module, line, shape) in enumerate(sites):
                for other, other_line, other_shape in sites[index + 1 :]:
                    if module == other or shape != other_shape:
                        continue
                    if reaches(module, other) or reaches(other, module):
                        continue
                    offenders.append(
                        f"{name}: {module}:{line} and {other}:{other_line}"
                    )
        assert not offenders, (
            f"the same helper grew twice in modules that cannot see each "
            f"other: {offenders}; give it one home both can import"
        )


class TestNoGuardedReturnRepeatsItsFallback:
    """A guarded return whose value equals the fallback decides nothing.

    ``_network_label`` took ``pid_alive`` and branched on it to the string its
    fallback already returned, so the argument could not change the answer.
    The reader of that code sees three outcomes; the operator gets two. Either
    the branch was meant to say something and does not, or it is dead - and
    both readings need the same edit.

    Not the same defect as the structural scan's: that one compares two
    FUNCTIONS. This compares two branches inside one, which no cross-function
    comparison can reach.
    """

    def test_no_branch_returns_what_the_fallback_returns(self) -> None:
        offenders: list[str] = []
        for path in _production_sources():
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except SyntaxError:  # pragma: no cover - parsed elsewhere
                continue
            for function in ast.walk(tree):
                if not isinstance(function, ast.FunctionDef | ast.AsyncFunctionDef):
                    continue
                body = function.body
                for index, statement in enumerate(body[:-1]):
                    following = body[index + 1]
                    if not (
                        isinstance(statement, ast.If)
                        and not statement.orelse
                        and len(statement.body) == 1
                        and isinstance(statement.body[0], ast.Return)
                        and isinstance(following, ast.Return)
                    ):
                        continue
                    guarded = statement.body[0].value
                    fallback = following.value
                    if guarded is None or fallback is None:
                        continue
                    if ast.dump(guarded) == ast.dump(fallback):
                        offenders.append(
                            f"{path.name}:{statement.lineno} in {function.name}()"
                        )
        assert not offenders, (
            f"a guarded return repeats its fallback at {offenders}; the "
            "condition cannot change the answer, so either the branch owes a "
            "different one or it and whatever it tests are dead"
        )


class TestParseErrorEnvelopeHasOneShape:
    """A rejected source type is reported in one envelope, built by the error.

    Five call sites assembled it: two HTTP routes and three service-client
    calls, each spreading ``as_payload()`` into the same three keys. The
    exception already knew its kind and how it reads; what it did not own was
    how it gets reported, so every new caller learned the shape by copying an
    older one - and a caller copying a stale example reports a shape the
    others do not.

    Deliberately not caught here: the job-create route classifies the same
    exception as ``invalid_job_spec`` and routes it through the jobs envelope
    helper. A bad source inside a job spec is a job-spec error, so that is a
    different report, not a copy of this one.
    """

    def test_no_module_assembles_the_parse_error_envelope(self) -> None:
        offenders: list[str] = []
        for path in _production_sources():
            if path.name == "_source_types.py":
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except SyntaxError:  # pragma: no cover - parsed elsewhere
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.Dict):
                    continue
                names = {
                    key.value
                    for key in node.keys
                    if isinstance(key, ast.Constant) and isinstance(key.value, str)
                }
                spreads_payload = any(
                    key is None
                    and isinstance(value, ast.Call)
                    and isinstance(value.func, ast.Attribute)
                    and value.func.attr == "as_payload"
                    for key, value in zip(node.keys, node.values, strict=True)
                )
                if spreads_payload and {"ok", "message"} <= names:
                    offenders.append(f"{path.name}:{node.lineno}")
        assert not offenders, (
            f"the parse-error envelope is assembled by hand at {offenders}; "
            "call SourceTypeParseError.as_error_envelope so every adapter "
            "reports the rejection the same way"
        )

    def test_the_envelope_carries_what_the_adapters_relied_on(self) -> None:
        """The keys the five call sites emitted must all still be there."""
        from .._source_types import SourceTypeParseError, parse_source_type

        with pytest.raises(SourceTypeParseError) as caught:
            parse_source_type("bogus", allow_aliases=True)
        envelope = caught.value.as_error_envelope()

        assert envelope["ok"] is False
        assert envelope["error"] == caught.value.error_kind
        assert envelope["message"] == str(caught.value)
        # The payload is spread in, not nested: an adapter reads received and
        # allowed off the top level.
        for key, value in caught.value.as_payload().items():
            assert envelope[key] == value


class TestCrossModuleLiteralTwins:
    """No data literal of three or more elements is written out twice.

    A scan for identical multi-element literals across modules found six: a
    failure envelope in five places, the sync-counter labels, the managed-log
    source vocabulary, the document-filter projection, the dry-run sample
    shape, and the probe-unavailable block - the last of which already had a
    helper in the transport that the status renderer simply did not call.

    Each had a natural owner that already existed. The sample now reports
    itself, the way the breadth figures already did; the counters and the log
    sources were declared once and re-listed; the filter projection sits with
    the type it produces.
    """

    def test_no_literal_collection_is_defined_in_two_modules(self) -> None:
        import collections

        seen: collections.defaultdict[str, list[str]] = collections.defaultdict(list)
        for path in _production_sources():
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except SyntaxError:  # pragma: no cover - parsed elsewhere
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.Tuple | ast.List | ast.Set | ast.Dict):
                    continue
                elements = node.keys if isinstance(node, ast.Dict) else node.elts
                present = [e for e in elements if e is not None]
                if len(present) < 3 or not all(
                    isinstance(e, ast.Constant) for e in present
                ):
                    continue
                seen[ast.unparse(node)].append(f"{path.name}:{node.lineno}")
        offenders = {
            literal: sites
            for literal, sites in seen.items()
            if len({site.split(":")[0] for site in sites}) > 1
        }
        assert not offenders, (
            f"the same literal collection is written in two modules: "
            f"{offenders}; give it one owner both can import"
        )

    def test_the_sample_reports_itself(self) -> None:
        """The projection lives with the data, not in each adapter.

        Proven able to fail: dropping a key from ``as_payload`` fails this on
        the field comparison below.
        """
        from ..indexer._content_discovery import AdmissionReason, AdmissionSample
        from ..indexer._content_policy import ContentKind

        sample = AdmissionSample(
            path="p.py",
            kind=ContentKind.CODE,
            admitted=True,
            reason=next(iter(AdmissionReason)),
        )
        assert sample.as_payload() == {
            "path": sample.path,
            "kind": sample.kind.value if sample.kind is not None else None,
            "admitted": sample.admitted,
            "reason": sample.reason.value,
        }


class TestJobEnumGroupingsAreDeclared:
    """A named subset of an enum's members is declared on the enum.

    ``JobState`` already carried ``is_terminal`` as a property, so the
    mechanism existed and the code was written around it: three more
    groupings were enumerated at call sites instead. Nine sites listed
    members to ask one of three questions - is an attempt in flight, may this
    be retried, is this a corpus rather than housekeeping.

    Naming them also fixed an imprecision. The retry route rejected a job with
    "Only terminal jobs can be retried" while testing the narrower retryable
    set: a succeeded job is terminal and has nothing to retry. A grouping with
    no name gets described by whichever nearby word is close enough.
    """

    def test_no_module_enumerates_a_job_enum_grouping(self) -> None:
        from ..job_models import JobSource, JobState

        groupings = {
            "JobState.is_live_attempt": frozenset(
                m.name for m in JobState if m.is_live_attempt
            ),
            "JobState.is_retryable": frozenset(
                m.name for m in JobState if m.is_retryable
            ),
            "JobState.is_terminal": frozenset(
                m.name for m in JobState if m.is_terminal
            ),
            "JobSource.is_corpus": frozenset(m.name for m in JobSource if m.is_corpus),
        }
        offenders: list[str] = []
        for path in _production_sources():
            if path.name == "job_models.py":
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except SyntaxError:  # pragma: no cover - parsed elsewhere
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.Set | ast.Tuple | ast.List):
                    continue
                members = {
                    element.attr
                    for element in node.elts
                    if isinstance(element, ast.Attribute)
                    and isinstance(element.value, ast.Name)
                    and element.value.id in {"JobState", "JobSource"}
                }
                if not members:
                    continue
                for name, expected in groupings.items():
                    if members == expected:
                        offenders.append(f"{path.name}:{node.lineno} relists {name}")
        assert not offenders, (
            f"{offenders}; ask the enum, so a member added to the grouping "
            "reaches every caller instead of whichever ones get remembered"
        )

    def test_retryable_is_narrower_than_terminal(self) -> None:
        """The distinction the enumerated version kept losing.

        Proven able to fail: widening ``is_retryable`` to ``is_terminal``
        fails this on the strict-subset assertion below.
        """
        from ..job_models import JobState

        terminal = {state for state in JobState if state.is_terminal}
        retryable = {state for state in JobState if state.is_retryable}
        assert retryable < terminal
        assert JobState.SUCCEEDED in terminal
        assert JobState.SUCCEEDED not in retryable


class TestTimestampReadingHasOneHome:
    """Only ``_timestamps`` turns a stored ISO string back into an instant.

    The writing side was made canonical long ago - one helper stamps both
    discovery fields so their format cannot drift. The reading side was not,
    and five sites parsed a stamp back, two of them the same function under
    the same name in modules one of which imports the other.

    The rule that mattered was the one for a value carrying no offset. Four
    readers called it UTC; the fifth handed it to ``astimezone``, which reads
    a naive value as local. Same string, two instants, differing by the
    machine's offset - and nothing failed, because the canonical writer always
    emits an offset. It would have surfaced first on a hand-edited file.
    """

    #: The typed round-trip for preprocess config scalars is not this. It
    #: dispatches across ``date``/``time``/``datetime`` and must RAISE on bad
    #: input, where every timestamp reader returns ``None`` and carries on.
    #: Merging them would force one contract onto both.
    _TYPED_SCALAR_THAW = "_resolved_policy.py"

    def test_only_the_timestamp_module_parses_an_iso_instant(self) -> None:
        """A new ``fromisoformat`` elsewhere is a sixth reader."""
        offenders: list[str] = []
        for path in _production_sources():
            if path.name in {"_timestamps.py", self._TYPED_SCALAR_THAW}:
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except SyntaxError:  # pragma: no cover - parsed elsewhere
                continue
            offenders.extend(
                f"{path.name}:{node.lineno}"
                for node in ast.walk(tree)
                if isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "fromisoformat"
            )
        assert not offenders, (
            f"an ISO timestamp is parsed outside the timestamp module at "
            f"{offenders}; call parse_iso_timestamp, so the rule for a value "
            "carrying no offset is stated once instead of guessed per reader"
        )

    def test_only_the_timestamp_module_calls_a_naive_value_utc(self) -> None:
        """The coercion is the rule itself, so it may exist in one place."""
        offenders: list[str] = []
        for path in _production_sources():
            if path.name == "_timestamps.py":
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except SyntaxError:  # pragma: no cover - parsed elsewhere
                continue
            offenders.extend(
                f"{path.name}:{node.lineno}"
                for node in ast.walk(tree)
                if isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "replace"
                and any(kw.arg == "tzinfo" for kw in node.keywords)
            )
        assert not offenders, (
            f"a naive timestamp is given a timezone outside the timestamp "
            f"module at {offenders}; whichever offset it picks becomes a "
            "second answer to the question that module exists to answer once"
        )

    def test_a_naive_stamp_reads_as_utc_and_not_as_local(self) -> None:
        """The divergence the fifth reader carried.

        ``astimezone`` on a naive value assumes LOCAL time, so the label path
        placed the same string at a different instant from every other reader
        whenever the machine was not on UTC.

        Proven able to fail: returning ``parsed`` unchanged instead of
        ``parsed.replace(tzinfo=UTC)`` fails this on the ``tzinfo`` assertion
        below; making the fallback ``astimezone()`` fails it on the equality.
        """
        from datetime import UTC, datetime

        from .._timestamps import parse_iso_timestamp

        naive = parse_iso_timestamp("2026-07-26T10:00:00")
        assert naive is not None
        assert naive.tzinfo is UTC
        assert naive == datetime(2026, 7, 26, 10, 0, 0, tzinfo=UTC)

    def test_no_module_rewrites_a_z_suffix_before_parsing(self) -> None:
        """The dead workaround one reader still carried, kept out.

        ``fromisoformat`` has accepted ``Z`` since 3.11 and this package
        requires later, so substituting ``+00:00`` first is a no-op that reads
        as a necessary step. Asserting the parser accepts ``Z`` would test
        CPython rather than this codebase; asserting nothing performs the
        substitution tests the thing that was actually wrong.
        """
        offenders: list[str] = []
        for path in _production_sources():
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except SyntaxError:  # pragma: no cover - parsed elsewhere
                continue
            offenders.extend(
                f"{path.name}:{node.lineno}"
                for node in ast.walk(tree)
                if isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "replace"
                and [
                    argument.value
                    for argument in node.args
                    if isinstance(argument, ast.Constant)
                ]
                == ["Z", "+00:00"]
            )
        assert not offenders, (
            f"a Z suffix is rewritten before parsing at {offenders}; the "
            "parser has accepted it since 3.11, and a no-op that looks "
            "load-bearing is how the copy carrying it escaped notice"
        )


class TestTreeRemovalHasOneHandler:
    """Only ``_rmtree`` decides what to do with a link found mid-tree.

    Two modules had grown the handler independently, byte-for-byte identical
    apart from the name each gave the caught exception - and that rename is
    exactly why the structural scan could not see them. It blinds identifiers
    and constants, but an ``except ... as`` alias is a plain string on the
    handler node, so two identical bodies hashed differently.
    """

    def test_no_module_passes_its_own_onexc_handler(self) -> None:
        """A second handler is a second policy for following a link."""
        offenders: list[str] = []
        for path in _production_sources():
            if path.name == "_rmtree.py":
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except SyntaxError:  # pragma: no cover - parsed elsewhere
                continue
            offenders.extend(
                f"{path.name}:{node.lineno}"
                for node in ast.walk(tree)
                if isinstance(node, ast.Call)
                and any(kw.arg in {"onexc", "onerror"} for kw in node.keywords)
            )
        assert not offenders, (
            f"a tree removal supplies its own error handler at {offenders}; "
            "call remove_tree, so descending through a link is refused by one "
            "policy rather than by whichever copy the caller reached for"
        )

    def test_the_handler_clears_a_link_instead_of_following_it(self) -> None:
        """The branch, exercised directly rather than through a tree.

        A tree-shaped test cannot reach this on Windows: ``rmtree`` there
        walks with ``scandir`` and removes both link shapes itself, so the
        handler is never invoked and the test passes whatever the handler
        does. Only the POSIX fd-walk raises on a link found mid-tree. Calling
        the handler with the arguments ``rmtree`` would pass it exercises the
        real branch on either platform.

        Proven able to fail: dropping the ``is_symlink`` branch so the handler
        only re-raises fails this on the ``pytest.fail`` below.
        """
        from .._rmtree import _unlink_link_or_reraise

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            outside = root / "outside"
            outside.mkdir()
            kept = outside / "precious.txt"
            kept.write_text("must survive", encoding="utf-8")
            link = root / "link"
            try:
                link.symlink_to(outside, target_is_directory=True)
            except OSError as exc:  # pragma: no cover - unprivileged Windows
                pytest.skip(f"symlink creation not permitted here: {exc}")
            try:
                _unlink_link_or_reraise(os.rmdir, str(link), OSError("refused"))
            except OSError as exc:
                pytest.fail(
                    f"the handler re-raised over a link instead of clearing it: {exc}"
                )
            assert not link.is_symlink()
            assert kept.read_text(encoding="utf-8") == "must survive"

    def test_the_handler_re_raises_anything_that_is_not_a_link(self) -> None:
        """A real failure must not be swallowed by the link branch.

        Proven able to fail: returning instead of ``raise exc`` fails this on
        the ``pytest.raises`` below, and every genuine removal error would
        then be reported as a successful delete.
        """
        from .._rmtree import _unlink_link_or_reraise

        with tempfile.TemporaryDirectory() as td:
            ordinary = Path(td) / "ordinary.txt"
            ordinary.write_text("not a link", encoding="utf-8")
            with pytest.raises(OSError, match="disk went away"):
                _unlink_link_or_reraise(
                    os.unlink, str(ordinary), OSError("disk went away")
                )

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
import sys
from pathlib import Path
from typing import ClassVar

import pytest

from .. import _process_probe

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

    _ALLOWED_SHAPES: ClassVar[dict[tuple[str, ...], str]] = {
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
            "server/_search_availability.py:_normalized_mode",
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

        orphans: dict[str, list[str]] = {}
        for name, sites in definitions.items():
            word = rf"\b{re.escape(name)}\b"
            # every production mention minus the definition lines themselves
            used = len(re.findall(word, production_blob)) - len(sites)
            if used == 0 and re.search(word, test_blob):
                orphans[name] = sites

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

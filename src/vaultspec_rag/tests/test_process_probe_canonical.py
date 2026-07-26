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

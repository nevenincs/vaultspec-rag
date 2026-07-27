"""Canonical ownership guard tests for the process-probe split."""

from __future__ import annotations

import ast
import os
import sys
from typing import TYPE_CHECKING, ClassVar

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from ._process_probe_guard_helpers import (
    _ALLOWED,
    _PACKAGE_ROOT,
    _production_sources,
    find_offenders,
    is_attr_call,
)

pytestmark = [pytest.mark.unit]


def test_no_module_signals_a_process_directly() -> None:
    # `os.kill` is how a refused kill gets swallowed. Routing every signal
    # through `send_signal` is what makes PermissionError a reportable outcome
    # instead of a silent pass, so a new raw call re-opens the original defect.
    found = find_offenders(lambda n: is_attr_call(n, "os", "kill"))
    assert not found, (
        f"raw os.kill outside _process_probe at {found}; "
        "use _process_probe.send_signal so a refused signal is reported"
    )


def test_no_module_builds_its_own_psutil_process_probe() -> None:
    found = find_offenders(
        lambda n: (
            is_attr_call(n, "psutil", "Process")
            or is_attr_call(n, "psutil", "process_iter")
        )
    )
    assert not found, (
        f"raw psutil process inspection outside _process_probe at {found}; "
        "use pid_start_time / pid_is_zombie / iter_process_info"
    )


def test_no_module_redeclares_the_kernel32_process_calls() -> None:
    # Three modules once declared OpenProcess independently and only one got
    # the pointer-sized HANDLE restype right, so the others truncated it.
    found = find_offenders(
        lambda n: (
            isinstance(n.func, ast.Attribute)
            and n.func.attr
            in {"OpenProcess", "GetExitCodeProcess", "QueryFullProcessImageNameW"}
        )
    )
    assert not found, (
        f"direct kernel32 process calls outside _process_probe at {found}; "
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
        find_offenders: list[str] = []
        for path in _production_sources():
            if path.relative_to(_PACKAGE_ROOT).as_posix() in {
                "config/_types.py",
                "_runtime_identity.py",
            }:
                continue
            for number, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), start=1
            ):
                if '"VIRTUAL_ENV"' in line or "'VIRTUAL_ENV'" in line:
                    find_offenders.append(
                        f"{path.relative_to(_PACKAGE_ROOT).as_posix()}:{number}"
                    )
        assert not find_offenders, (
            f"bare VIRTUAL_ENV literal at {find_offenders}; read it through "
            "EnvVar.VIRTUAL_ENV, or better, _runtime_identity"
        )

    def test_no_module_rebuilds_the_interpreter_field_set(self) -> None:
        # sys.base_prefix is the fingerprint of this particular field set: it
        # appears for no other reason than describing which interpreter is
        # running, so a new use means a fifth copy is being assembled.
        find_offenders = [
            f"{path.relative_to(_PACKAGE_ROOT).as_posix()}:{number}"
            for path in _production_sources()
            if path.name != "_runtime_identity.py"
            for number, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), start=1
            )
            if "sys.base_prefix" in line
        ]
        assert not find_offenders, (
            f"interpreter field set rebuilt at {find_offenders}; splice "
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
        find_offenders = [
            f"{path.relative_to(_PACKAGE_ROOT).as_posix()}:{number}"
            for path in _production_sources()
            if path.name != "_loopback_http.py"
            and path.name not in self._ALLOWED_OPENERS
            for number, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), start=1
            )
            if "build_opener(" in line
        ]
        assert not find_offenders, (
            f"second HTTP opener at {find_offenders}; loopback callers must use "
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
        find_offenders = [
            f"{path.relative_to(_PACKAGE_ROOT).as_posix()}:{number}"
            for path in _production_sources()
            if path.relative_to(_PACKAGE_ROOT).as_posix() != "config/_paths.py"
            for number, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), start=1
            )
            if '"service.json"' in line or "'service.json'" in line
        ]
        assert not find_offenders, (
            f"hardcoded discovery filename at {find_offenders}; import "
            "config.SERVICE_STATUS_FILENAME so every reader renames together"
        )

    def test_every_reader_resolves_the_same_file(self) -> None:
        # The constant alone does not prove the readers agree - they resolve
        # the DIRECTORY separately, and that is where they could still diverge.
        from ..config._paths import SERVICE_STATUS_FILENAME
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
        find_offenders = [
            f"{path.relative_to(_PACKAGE_ROOT).as_posix()}:{number}"
            for path in _production_sources()
            if path.name != "_job_errors.py"
            for number, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), start=1
            )
            if any(mark in line.lower() for mark in fingerprints)
        ]
        assert not find_offenders, (
            f"second disk-full vocabulary at {find_offenders}; import "
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
        find_offenders = [
            f"{path.relative_to(_PACKAGE_ROOT).as_posix()}:{number}"
            for path in _production_sources()
            if path.name != "_fd_lock.py"
            for number, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), start=1
            )
            if ("msvcrt.locking(" in line or "fcntl.flock(" in line)
            and not line.lstrip().startswith("#")
        ]
        assert not find_offenders, (
            f"direct advisory-lock call at {find_offenders}; use "
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

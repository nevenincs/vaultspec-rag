"""CLI rendering of real storage headroom refusals."""

from __future__ import annotations

import json
import typing

import pytest

from ._cli_helpers import (
    _plain_lines,
    app,
    runner,
)
from ._production_service import production_service

if typing.TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

pytestmark = [pytest.mark.unit]


# Exceeds the free space on any test volume so production refuses the preflight.
_UNSATISFIABLE_FLOOR_BYTES = 1 << 60


def _index_refused_by_the_real_disk_preflight(
    storage_path: Path,
) -> Callable[..., object]:
    """Return an index entry point that fails the production headroom check.

    The in-process index cannot be driven to a genuine out-of-disk condition
    from a unit test: reaching the preflight means loading the models and
    filling the store volume first. So the refusal is raised by the store's
    own ``ensure_disk_headroom`` against a floor no volume satisfies - the
    exception class, the classification, and the operator wording are all
    production's, and what the tests below bind is what the CLI does with
    them rather than anything written here.
    """
    from .._store_writes import ensure_disk_headroom

    def _index(*_args: object, **_kwargs: object) -> object:
        ensure_disk_headroom(storage_path, floor_bytes=_UNSATISFIABLE_FLOOR_BYTES)
        raise AssertionError(
            "the disk preflight accepted a floor no volume can satisfy"
        )

    return _index


@pytest.fixture
def project_refused_by_the_disk_preflight(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Path:
    """A project whose in-process index run fails the real disk preflight.

    One trigger site shared by both refusal tests rather than one apiece. The
    setup is identical for the two, and this is the only place in this file
    that stands anything in for production, so duplicating it would have
    doubled that surface to say the same thing twice.
    """
    project = tmp_path / "project"
    (project / ".vaultspec").mkdir(parents=True)
    monkeypatch.setattr(
        "vaultspec_rag.index",
        _index_refused_by_the_real_disk_preflight(project),
    )
    return project


class TestDiskPreflightRefusal:
    """The in-process index path surfaces a disk-preflight refusal as one
    structured non-zero envelope - never the GPU-error diagnosis.

    The in-process path is reached the way an operator reaches it, which now
    means passing the borrower gate rather than falling through it: local GPU
    indexing requires ``--borrow-gpu`` and a live compatible service to
    quiesce, so each test stands up the real authenticated route host, lets
    real discovery find it, and lets the production coordinator take its lease
    and pause. Nothing rehearses the refusal that follows.

    Both tests below therefore also fail if the borrower coordination stops
    reaching local indexing at all - a refusal from the gate carries neither
    the classification nor the wording they assert.
    """

    def test_json_mode_emits_disk_preflight_failed(
        self,
        isolated_singleton_dirs: Path,
        project_refused_by_the_disk_preflight: Path,
    ) -> None:
        """A refused preflight is one classified envelope, exit 1.

        The real progress rendering runs; its stream is pointed at a buffer
        because Rich interleaves cursor control bytes with the envelope on
        stdout and this test parses that envelope. The reporter itself is
        the production one, built by the production call site from the
        console it reads at call time.

        Proven able to fail: deleting the ``except InsufficientDiskSpaceError``
        branch in the in-process index path drops the refusal into the
        ``(ImportError, RuntimeError)`` GPU handler. That handler takes no
        JSON mode and always renders human prose, so the run emits no
        envelope at all and the one-envelope assertion below is what fails -
        not the ``disk_preflight_failed`` one, which is never reached.
        Restoring the branch passes. The classification assertion still binds
        the branch's verdict wherever an envelope is produced; both are kept
        because the mutation is caught earlier only by accident of how the
        GPU handler writes.
        """

        project = project_refused_by_the_disk_preflight
        with production_service(isolated_singleton_dirs):
            result = runner.invoke(
                app,
                [
                    "--target",
                    str(project),
                    "index",
                    "--type",
                    "vault",
                    "--borrow-gpu",
                    "--json",
                ],
            )
        assert result.exit_code == 1
        # No console redirect: a --json run reports no progress at all, so
        # stdout carries the envelope and nothing else. Before that, this had
        # to redirect the console to keep the progress lines out of the result
        # channel, which hid the fact that they were being written there.
        assert result.output.lstrip().startswith("{"), (
            "--json must answer with one envelope on every exit path, "
            f"got: {result.output!r}"
        )
        payload = typing.cast("dict[str, object]", json.loads(result.output))
        assert payload["ok"] is False
        assert payload["error"] == "disk_preflight_failed"
        assert "disk space" in str(payload["message"])
        remediation = typing.cast("list[str]", payload["remediation"])
        assert any("storage survey" in r for r in remediation)

    def test_human_mode_prints_the_refusal(
        self,
        isolated_singleton_dirs: Path,
        project_refused_by_the_disk_preflight: Path,
    ) -> None:
        """Human mode prints the store's own wording, exit 1.

        Proven able to fail: replacing the refusal's ``_plain(f"Error: {exc}")``
        with a bare ``_plain("Error")`` fails the assertion below; restoring
        it passes.

        What this does NOT bind, checked rather than assumed: deleting the
        dedicated disk branch entirely still passes here, because on a host
        whose torch and GPU are both healthy the GPU handler's fallback
        prints the same ``Error: {exc}`` line. Human text cannot tell the two
        apart, so the classification is bound by the ``--json`` sibling and
        this test binds only the wording that reaches the operator.
        """
        project = project_refused_by_the_disk_preflight
        with production_service(isolated_singleton_dirs):
            result = runner.invoke(
                app,
                [
                    "--target",
                    str(project),
                    "index",
                    "--type",
                    "vault",
                    "--borrow-gpu",
                ],
            )
        assert result.exit_code == 1
        assert "not enough free disk space" in " ".join(_plain_lines(result.output))

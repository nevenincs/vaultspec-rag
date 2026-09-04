"""What real uv does to a tool environment under hostile conditions.

These are the proofs the tool-mode CUDA work deferred: no test had ever watched
real uv act on a held environment, nor checked the production receipt matcher
against a receipt uv itself wrote. Both gaps are closed here, and neither can
touch a live installation - every uv invocation runs in a sandbox whose tool,
bin and cache directories are inside ``tmp_path``.

The destruction proof is Windows-only by nature rather than by choice: a
blocked removal is what turns a forced reinstall destructive, and POSIX unlink
semantics do not produce one. It is skipped elsewhere rather than weakened into
something that passes everywhere and proves nothing.
"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

import pytest

from ..commands._tool_torch import _receipt_has_cuda_requirement
from ._uv_env_harness import (
    UvSandbox,
    WheelTags,
    build_wheel,
    hold_environment,
    index_arguments,
    installed_distributions,
    receipt_text,
    sandbox_from,
    serve_wheels,
)

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

pytestmark = [pytest.mark.unit]

_TOOL = "provtool"
# The production matcher only recognises a requirement NAMED torch, so the
# stand-in carries that name. It is a locally built pure-Python wheel served
# from a loopback index with --no-index, so nothing resolves to real torch.
_STANDIN = "torch"
_STANDIN_VERSION = "2.14.0+cu130"


@pytest.fixture
def sandbox(tmp_path: Path) -> UvSandbox:
    """A uv installation redirected entirely inside this test's temp tree."""
    return sandbox_from(tmp_path)


@pytest.fixture
def wheel_index(tmp_path: Path) -> Iterator[str]:
    """Serve the stand-in distributions over loopback HTTP."""
    wheels = tmp_path / "wheels"
    build_wheel(wheels, name=_TOOL, version="1.0.0")
    build_wheel(wheels, name=_STANDIN, version=_STANDIN_VERSION)
    build_wheel(
        wheels,
        name="badtag",
        version="1.0.0",
        tags=WheelTags(python="cp299", abi="cp299", platform="win_amd64"),
    )
    with serve_wheels(wheels) as base_url:
        yield base_url


def _standin_url(base_url: str) -> str:
    return f"{base_url}/{_STANDIN}-{_STANDIN_VERSION}-py3-none-any.whl"


def _install(sandbox: UvSandbox, base_url: str, *extra: str) -> None:
    """Install the tool with the stand-in pinned by direct URL."""
    completed = sandbox.run(
        "tool",
        "install",
        "--force",
        _TOOL,
        "--with",
        f"{_STANDIN} @ {_standin_url(base_url)}",
        *index_arguments(base_url),
        *extra,
    )
    assert completed.returncode == 0, completed.stderr


def test_a_receipt_written_by_uv_satisfies_the_production_matcher(
    sandbox: UvSandbox, wheel_index: str
) -> None:
    """The shipped matcher accepts a receipt uv actually wrote.

    This is the assertion the earlier work could not make: its receipt tests
    hand-wrote the TOML they then parsed, so a change in how uv serialises a
    direct requirement would have gone unnoticed until an operator hit it.
    """
    _install(sandbox, wheel_index)

    assert _receipt_has_cuda_requirement(
        sandbox.receipt(_TOOL), _standin_url(wheel_index)
    )


def test_the_matcher_rejects_a_receipt_pinning_a_different_wheel(
    sandbox: UvSandbox, wheel_index: str
) -> None:
    """A receipt naming another wheel is not accepted as the pin.

    Guard assertion: a matcher that ignored the URL would report every
    receipt as pinned, which is exactly the failure its caller exists to catch.
    """
    _install(sandbox, wheel_index)

    other = f"{wheel_index}/{_STANDIN}-9.9.9-py3-none-any.whl"
    assert not _receipt_has_cuda_requirement(sandbox.receipt(_TOOL), other)


def test_a_direct_url_requirement_is_recorded_as_a_url(
    sandbox: UvSandbox, wheel_index: str
) -> None:
    """uv records an http requirement under ``url``, which production reads.

    A receipt always carries ``path`` keys for entry-point install paths, so
    the requirement's own line is what must be inspected.
    """
    _install(sandbox, wheel_index)

    lines = [
        line.strip()
        for line in receipt_text(sandbox, _TOOL).splitlines()
        if _STANDIN in line and "name =" in line
    ]
    assert lines, receipt_text(sandbox, _TOOL)
    assert 'url = "http://127.0.0.1' in lines[0]
    assert "path = " not in lines[0]


def test_an_unreachable_wheel_leaves_the_environment_intact(
    sandbox: UvSandbox, wheel_index: str
) -> None:
    """A resolve-stage failure is not a destructive one.

    uv resolves and fetches before it replaces, so a bad pin costs the
    operator an error rather than an environment. This is what separates the
    conditions a preflight must guard from the ones uv already handles safely.
    """
    _install(sandbox, wheel_index)
    before = installed_distributions(sandbox, _TOOL)
    receipt_before = receipt_text(sandbox, _TOOL)

    completed = sandbox.run(
        "tool",
        "install",
        "--force",
        _TOOL,
        "--with",
        f"{_STANDIN} @ {wheel_index}/{_STANDIN}-9.9.9-py3-none-any.whl",
        *index_arguments(wheel_index),
    )

    assert completed.returncode != 0
    assert installed_distributions(sandbox, _TOOL) == before
    assert receipt_text(sandbox, _TOOL) == receipt_before


def test_a_wheel_tagged_for_another_interpreter_is_refused(
    sandbox: UvSandbox, wheel_index: str
) -> None:
    """An ABI mismatch is refused, and refused without touching the install."""
    _install(sandbox, wheel_index)
    before = installed_distributions(sandbox, _TOOL)

    completed = sandbox.run(
        "tool",
        "install",
        "--force",
        _TOOL,
        "--with",
        f"badtag @ {wheel_index}/badtag-1.0.0-cp299-cp299-win_amd64.whl",
        *index_arguments(wheel_index),
    )

    assert completed.returncode != 0
    assert installed_distributions(sandbox, _TOOL) == before


def test_an_offline_run_without_a_cache_fails_rather_than_reaching_out(
    sandbox: UvSandbox, wheel_index: str
) -> None:
    """Restricted egress is a deterministic refusal, not a hang."""
    completed = sandbox.run(
        "tool", "install", _TOOL, "--offline", *index_arguments(wheel_index)
    )

    assert completed.returncode != 0
    assert installed_distributions(sandbox, _TOOL) == set()


@pytest.mark.skipif(
    sys.platform != "win32",
    reason="a blocked removal is what makes the reinstall destructive, and "
    "POSIX unlink semantics do not produce one",
)
def test_a_forced_reinstall_destroys_a_held_environment(
    sandbox: UvSandbox, wheel_index: str
) -> None:
    """The field failure, reproduced: held environment in, wreckage out.

    A process running the environment's own interpreter blocks removal of
    ``Scripts``. uv has already removed the installed distributions by then, so
    what survives is an environment that cannot run and a receipt describing
    one that no longer exists. Everything downstream of this - the holder
    preflight, the refusal, the handed-over command - exists because of it.
    """
    _install(sandbox, wheel_index)
    assert installed_distributions(sandbox, _TOOL)

    with hold_environment(sandbox.tool_root(_TOOL), by_image=True):
        completed = sandbox.run(
            "tool", "install", "--force", _TOOL, *index_arguments(wheel_index)
        )

        assert completed.returncode != 0
        assert "failed to remove" in completed.stderr
        assert installed_distributions(sandbox, _TOOL) == set()
        assert sandbox.receipt(_TOOL).exists()

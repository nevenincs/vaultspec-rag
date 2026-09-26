"""What real uv does to a tool environment, hostile conditions and the cycle.

Two kinds of proof live here, and neither can touch a live installation:
every uv invocation runs in a sandbox whose tool, bin and cache directories
are inside ``tmp_path``, and the distributions are locally built stand-ins
served over a loopback index.

The first kind is why the product never replaces an environment: a forced
reinstall of a held one removes the installed distributions and then fails,
and so does an install whose interpreter request does not match the
environment it names. Both leave wreckage, and both are reproduced rather
than described.

The second is the install and upgrade cycle itself, end to end against real
uv: an installation made with the CUDA index and the first-match strategy
records both in its receipt, the product's own repair applies to a held
environment in place, and a plain upgrade afterwards moves the release while
keeping the accelerated build.

The destruction proofs are Windows-only by nature rather than by choice: a
blocked removal is what turns a replacement destructive, and POSIX unlink
semantics do not produce one. They are skipped elsewhere rather than weakened
into something that passes everywhere and proves nothing.
"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

import pytest

from ..commands import _tool_torch
from ..operator_state import _provisioning
from ..operator_state._provisioning import (
    CU130_INDEX_STRATEGY,
    ToolReceiptVerdict,
    classify_tool_receipt,
    tool_repair_arguments,
)
from ._uv_env_harness import (
    UvSandbox,
    WheelContents,
    WheelTags,
    build_wheel,
    hold_environment,
    index_arguments,
    installed_distributions,
    publish_index,
    receipt_text,
    sandbox_from,
    serve_wheels,
)

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

pytestmark = [pytest.mark.unit]

#: The stand-in tool carries this product's own name, because the repair
#: builds its request from that name and reads the entry uv keeps under it.
_TOOL = "vaultspec-rag"
_TOOL_VERSION = "1.0.0"
_NEWER_TOOL_VERSION = "1.1.0"

#: The stand-in for torch. Both builds exist, so an upgrade that silently
#: resolves the plain one is visible as a version rather than inferred.
_TORCH = "torch"
_CPU_TORCH = "1.0.0"
_CUDA_TORCH = "1.0.0+cu130"


@pytest.fixture
def sandbox(tmp_path: Path) -> UvSandbox:
    """A uv installation redirected entirely inside this test's temp tree."""
    return sandbox_from(tmp_path)


@pytest.fixture
def wheel_index(tmp_path: Path) -> Iterator[str]:
    """Serve the stand-in distributions over loopback HTTP as a flat listing."""
    wheels = tmp_path / "wheels"
    build_wheel(
        wheels,
        name=_TOOL,
        version=_TOOL_VERSION,
        contents=WheelContents(requires=(_TORCH,)),
    )
    build_wheel(wheels, name=_TORCH, version=_CPU_TORCH)
    build_wheel(
        wheels,
        name="badtag",
        version="1.0.0",
        contents=WheelContents(
            tags=WheelTags(python="cp299", abi="cp299", platform="win_amd64")
        ),
    )
    with serve_wheels(wheels) as base_url:
        yield base_url


@pytest.fixture
def cuda_index(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    """A simple index standing in for the accelerated one, and its two builds.

    The product compares a receipt's recorded index against one constant, so
    that constant is pointed at this index for the duration: what is being
    proved is what uv records and re-applies, not which host the real index
    lives on.
    """
    packages = tmp_path / "cuda-index"
    wheels = tmp_path / "cuda-wheels"
    needs_torch = WheelContents(requires=(_TORCH,))
    build_wheel(wheels, name=_TOOL, version=_TOOL_VERSION, contents=needs_torch)
    build_wheel(wheels, name=_TOOL, version=_NEWER_TOOL_VERSION, contents=needs_torch)
    build_wheel(wheels, name=_TORCH, version=_CUDA_TORCH)
    publish_index(wheels, packages)
    with serve_wheels(packages) as base_url:
        monkeypatch.setattr(_provisioning, "CU130_INDEX_URL", base_url)
        yield base_url


def _cuda_options(base_url: str) -> tuple[str, ...]:
    """The two options the product records, as uv arguments."""
    return ("--index", base_url, "--index-strategy", CU130_INDEX_STRATEGY)


def _interpreter(sandbox: UvSandbox) -> str:
    """The stand-in tool environment's own interpreter."""
    root = sandbox.tool_root(_TOOL)
    windows = root / "Scripts" / "python.exe"
    return str(windows if windows.exists() else root / "bin" / "python")


def _installed_version(sandbox: UvSandbox, distribution: str) -> str:
    """The version of *distribution* installed in the tool environment."""
    site = sandbox.site_packages(_TOOL)
    prefix = f"{distribution.replace('-', '_')}-"
    for entry in site.glob("*.dist-info"):
        if entry.name.startswith(prefix):
            return entry.name.removeprefix(prefix).removesuffix(".dist-info")
    raise AssertionError(f"{distribution} is not installed: {sorted(site.iterdir())}")


def _install_without_the_cuda_source(sandbox: UvSandbox, base_url: str) -> None:
    """Stage the field shape: an installation recording no CUDA source."""
    completed = sandbox.run("tool", "install", _TOOL, *index_arguments(base_url))
    assert completed.returncode == 0, completed.stderr


def test_an_installation_made_with_the_options_is_durable(
    sandbox: UvSandbox, cuda_index: str
) -> None:
    """uv records the index and the strategy, and production reads them back.

    This is the whole basis of the cycle: the receipt is the only state uv
    consults on a later upgrade, so a CUDA source recorded there is the only
    one that survives an upgrade nobody supervises. The receipt is written by
    real uv rather than by this test, because what it serialises is the fact
    being relied on.
    """
    completed = sandbox.run("tool", "install", _TOOL, *_cuda_options(cuda_index))
    assert completed.returncode == 0, completed.stderr

    recorded = receipt_text(sandbox, _TOOL)
    assert f'index-strategy = "{CU130_INDEX_STRATEGY}"' in recorded
    assert cuda_index in recorded
    assert classify_tool_receipt(_interpreter(sandbox)) is ToolReceiptVerdict.DURABLE


@pytest.mark.usefixtures("cuda_index")
def test_an_installation_made_without_them_is_not(
    sandbox: UvSandbox, wheel_index: str
) -> None:
    """The field shape reads as what it is: one upgrade from a CPU build.

    Guard assertion: this installation's torch works, so a check that reads
    only the installed build calls it healthy and lets the next upgrade
    replace it.
    """
    _install_without_the_cuda_source(sandbox, wheel_index)

    assert (
        classify_tool_receipt(_interpreter(sandbox))
        is ToolReceiptVerdict.NO_CUDA_SOURCE
    )


@pytest.mark.usefixtures("cuda_index")
def test_the_repair_applies_in_place_to_a_held_environment(
    sandbox: UvSandbox, wheel_index: str
) -> None:
    """The product's own repair, run against an environment being used.

    Nothing is stopped for it: a process is running out of the environment
    throughout, and it is still running afterwards. This is what lets the
    product run the repair itself, and the command is the one the builder
    produces rather than one written here.
    """
    _install_without_the_cuda_source(sandbox, wheel_index)
    assert _installed_version(sandbox, _TORCH) == _CPU_TORCH
    interpreter = _interpreter(sandbox)

    with hold_environment(sandbox.tool_root(_TOOL), by_image=True) as holder:
        completed = sandbox.run(*tool_repair_arguments(interpreter)[1:])

        assert completed.returncode == 0, completed.stderr
        assert holder.poll() is None, "the repair must not end a running process"

    assert _installed_version(sandbox, _TORCH) == _CUDA_TORCH
    assert _installed_version(sandbox, _TOOL) == _TOOL_VERSION
    assert classify_tool_receipt(interpreter) is ToolReceiptVerdict.DURABLE


@pytest.mark.usefixtures("cuda_index")
def test_a_plain_upgrade_after_the_repair_keeps_the_cuda_build(
    sandbox: UvSandbox, wheel_index: str
) -> None:
    """The end of the cycle: uv's own verb, and the GPU build survives it.

    Guard assertion: this is what the previous mechanism could not do. It
    kept CUDA by pinning the release, so the same upgrade reported nothing to
    upgrade and the host never moved.
    """
    _install_without_the_cuda_source(sandbox, wheel_index)
    interpreter = _interpreter(sandbox)
    repaired = sandbox.run(*tool_repair_arguments(interpreter)[1:])
    assert repaired.returncode == 0, repaired.stderr

    upgraded = sandbox.run("tool", "upgrade", _TOOL)

    assert upgraded.returncode == 0, upgraded.stderr
    assert "Nothing to upgrade" not in upgraded.stdout + upgraded.stderr
    assert _installed_version(sandbox, _TOOL) == _NEWER_TOOL_VERSION
    assert _installed_version(sandbox, _TORCH) == _CUDA_TORCH


@pytest.mark.usefixtures("cuda_index")
def test_the_builder_asks_for_the_environments_own_interpreter(
    sandbox: UvSandbox, wheel_index: str
) -> None:
    """The request the product issues is the one uv applies in place.

    Guard assertion: a request uv reads as another interpreter is not applied
    in place at all, and the destruction that follows is proved below. The
    version is read from the environment uv built, not from this process.
    """
    _install_without_the_cuda_source(sandbox, wheel_index)
    interpreter = _interpreter(sandbox)

    arguments = tool_repair_arguments(interpreter)

    request = _provisioning.environment_python_request(interpreter)
    assert request is not None
    assert "--python" in arguments
    assert arguments[arguments.index("--python") + 1] == request
    assert "--force" not in arguments


@pytest.mark.skipif(
    sys.platform != "win32",
    reason="a blocked removal is what makes a replacement destructive, and "
    "POSIX unlink semantics do not produce one",
)
def test_an_interpreter_request_that_does_not_match_destroys_the_environment(
    sandbox: UvSandbox, cuda_index: str, wheel_index: str
) -> None:
    """The incident, reproduced: a mismatched request is a replacement.

    uv treats an install whose ``--python`` names a different interpreter as
    a request for a different environment and rebuilds wholesale, which
    removes the installed distributions before it fails on the held files.
    This is why the request is read from the target environment and why the
    runner refuses when uv's entry is not the environment in hand.
    """
    _install_without_the_cuda_source(sandbox, wheel_index)
    interpreter = _interpreter(sandbox)
    own = _provisioning.environment_python_request(interpreter)
    assert own is not None
    other = f"{sys.version_info[0]}.{sys.version_info[1] - 1}"
    assert other != own

    with hold_environment(sandbox.tool_root(_TOOL), by_image=True):
        completed = sandbox.run(
            "tool", "install", "--python", other, _TOOL, *_cuda_options(cuda_index)
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
    ``Scripts``. uv has already removed the installed distributions by then,
    so what survives is an environment that cannot run and a receipt
    describing one that no longer exists. The ban on ``--force`` exists
    because of it.
    """
    _install_without_the_cuda_source(sandbox, wheel_index)
    assert installed_distributions(sandbox, _TOOL)

    with hold_environment(sandbox.tool_root(_TOOL), by_image=True):
        completed = sandbox.run(
            "tool", "install", "--force", _TOOL, *index_arguments(wheel_index)
        )

        assert completed.returncode != 0
        assert "failed to remove" in completed.stderr
        assert installed_distributions(sandbox, _TOOL) == set()
        assert sandbox.receipt(_TOOL).exists()


def test_an_unreachable_wheel_leaves_the_environment_intact(
    sandbox: UvSandbox, wheel_index: str
) -> None:
    """A resolve-stage failure is not a destructive one.

    uv resolves and fetches before it replaces, so a bad request costs the
    operator an error rather than an environment. This is what separates the
    conditions the product must guard from the ones uv already handles safely.
    """
    _install_without_the_cuda_source(sandbox, wheel_index)
    before = installed_distributions(sandbox, _TOOL)
    receipt_before = receipt_text(sandbox, _TOOL)

    completed = sandbox.run(
        "tool",
        "install",
        "--force",
        _TOOL,
        "--with",
        f"{_TORCH} @ {wheel_index}/{_TORCH}-9.9.9-py3-none-any.whl",
        *index_arguments(wheel_index),
    )

    assert completed.returncode != 0
    assert installed_distributions(sandbox, _TOOL) == before
    assert receipt_text(sandbox, _TOOL) == receipt_before


def test_a_wheel_tagged_for_another_interpreter_is_refused(
    sandbox: UvSandbox, wheel_index: str
) -> None:
    """An ABI mismatch is refused, and refused without touching the install."""
    _install_without_the_cuda_source(sandbox, wheel_index)
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


@pytest.mark.usefixtures("cuda_index")
def test_the_runner_refuses_an_entry_that_is_another_environment(
    sandbox: UvSandbox, wheel_index: str
) -> None:
    """The product's launcher asks uv where it would install, and compares.

    Guard assertion: uv acts on its own entry for the package. The incident
    that destroyed a live installation was exactly this - the interpreter in
    hand belonged to one environment and uv's entry was another - so the
    comparison happens before anything that mutates is launched.
    """
    _install_without_the_cuda_source(sandbox, wheel_index)
    elsewhere = sandbox.tool_root("another-tool")
    (elsewhere / "Scripts").mkdir(parents=True)

    ran, detail = _tool_torch._run_repair(
        str(elsewhere / "Scripts" / "python.exe"), stream=False
    )

    assert not ran
    assert "which is not the environment being repaired" in detail

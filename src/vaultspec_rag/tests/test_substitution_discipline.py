"""Guard: the runtime-substitution surface may not grow unnoticed.

A substitute that replaces production behaviour makes an assertion true by its
own programming rather than by the code under test, so it can pass over a
regressed path. The surface was driven down to the sites below, each of which
was examined individually and kept for a reason recorded in its own docstring
at the call site.

This does not forbid substitution. It forbids adding one silently: a new site
fails here, and clearing the failure means either removing it or adding it to
the table with the reason it could not be driven for real. That is the review
step the count exists to force.

The scan is deliberately textual and counts per file rather than per line, so
it survives edits that move code around and only reacts to a site appearing or
disappearing.
"""

from __future__ import annotations

import pathlib

import pytest

pytestmark = [pytest.mark.unit]

# Assembled rather than written literally, so this guard does not match itself.
_NEEDLES = ("monkeypatch." + "setattr", "monkeypatch." + "delattr")

# Path relative to the tests package -> (count, why it could not be driven for
# real). The reason belongs at the call site too; it is repeated here so a
# reader hitting a failure learns what bar a new entry has to clear.
_ALLOWED: dict[str, tuple[int, str]] = {
    "test_cli_index.py": (
        1,
        "the disk floor is a per-profile compile-time constant with no config "
        "override, so a real run cannot be driven under it; production's own "
        "ensure_disk_headroom raises, classifies and words the refusal",
    ),
    "test_cli_server.py": (
        1,
        "asserts which watch mode 'server --watch' dispatches, which is only "
        "observable at the run_service_jobs boundary - driving it for real "
        "opens the full-screen interactive app and never returns; the "
        'source-scan this replaced matched the literal watch_mode="server" '
        "and so passed while the verb really dispatched jobs mode",
    ),
    "test_cli_progress_surfaces.py": (
        1,
        "no substitute source can be staged - the provisioner requires https "
        "on a pinned host and an archive matching a committed digest - and "
        "the only real alternative is re-downloading the pinned release on "
        "every run, which the suite's mirror-the-installed-binary design "
        "exists to avoid",
    ),
    "test_embeddings_dependencies.py": (
        3,
        "the two package-absence paths must be exercised without uninstalling "
        "the GPU development runtime from the shared test interpreter; the "
        "central torch gate and importlib lookup are substituted only to "
        "produce those otherwise destructive dependency states",
    ),
    "gpu_admission/test_floor_and_window.py": (
        1,
        "forces a present-but-unreadable memory reading, because the streak "
        "ledger the diagnostic and load paths share is only observable across "
        "a run of them and no real device yields one on demand",
    ),
    "gpu_admission/test_latch_and_wire.py": (
        2,
        "asserts the shared device-load reading's raise-swallowing behaviour "
        "and its composition with the live evaluator, which requires forcing "
        "a specific reading and a raised exception from it - neither "
        "reachable through a real device on a CPU-only runner; and forces a "
        "present-but-unreadable memory reading, because the streak ledger the "
        "diagnostic and load paths share is only observable across a run of "
        "them and no real device yields one on demand",
    ),
    "test_env_holders.py": (
        2,
        "drives the two fail-closed branches of the holder query - a process "
        "whose image and directory both read as unknown, and a process table "
        "that cannot be enumerated at all. Neither can be provoked on demand "
        "from a live table: the first needs a process this user may not "
        "inspect, the second needs the operating system to refuse the walk. "
        "Every relation the query actually reports is driven for real, "
        "against real environments held by real child processes",
    ),
    "test_readiness_holders.py": (
        2,
        "points the readiness scan at a purpose-built environment by "
        "substituting the running interpreter's own prefix, which the "
        "reporter reads to decide what to scan. A test cannot relaunch itself "
        "from inside a temporary virtual environment, and asserting on "
        "whatever happens to hold the developer's own prefix would assert "
        "nothing. The second widens the scan budget, which production sizes "
        "for an HTTP route: a walk of every process on a runner hosting a "
        "dozen parallel workers does not finish inside it, and the snapshot "
        "then honestly reports that it could not tell - indistinguishable, to "
        "an assertion about content, from finding no holder",
    ),
    "test_install_torch_config.py": (
        1,
        "drives a real install under a symlinked system temp root - the shape "
        "macOS has by default, where TMPDIR lives under a symlink - and the "
        "temp module caches its answer in a module attribute that pytest's own "
        "tmp_path populates before the test runs, so the documented "
        "environment override cannot take effect until that cache is cleared; "
        "the install itself runs for real and nothing about its behaviour is "
        "replaced",
    ),
    "test_jobs_device_load.py": (
        5,
        "asserts the jobs-listing cache's call count and its handling of a "
        "cached-absent reading against the shared device-load reading, which "
        "requires forcing a controlled reading (and counting how often it is "
        "taken) - neither reachable through a real device on a CPU-only "
        "runner",
    ),
    "test_server.py": (
        3,
        "asserts the stdio runner wires watcher cleanup and loads no model - "
        "both observable only at the instant the MCP transport is entered, "
        "and mcp.run(transport='stdio') blocks on real stdin forever, so the "
        "transport, the lifetime watchdog it arms, and the model load it must "
        "not perform are the three boundaries substituted; the source scans "
        "these replaced read main(), a two-line dispatcher containing neither "
        "contract, and passed against a real load added one frame down",
    ),
    "test_tool_torch_repair.py": (
        8,
        "the persistent uv tool interpreter and machine singleton cannot be "
        "safely forced through a defective-CUDA reinstall during a test: that "
        "would replace the developer's installed tool and can disrupt a live "
        "machine service. The tests retain the real repair transaction and "
        "substitute only its externally-owned observations, with sentinels "
        "that fail if a holder, no-device diagnosis, CUDA re-probe, or receipt "
        "postcondition is bypassed",
    ),
}


def _substitution_counts() -> dict[str, int]:
    """Count substitution call sites per file across the test package."""
    tests_root = pathlib.Path(__file__).parent
    counts: dict[str, int] = {}
    for path in sorted(tests_root.rglob("*.py")):
        if path == pathlib.Path(__file__):
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        hits = sum(
            1
            for line in text.splitlines()
            if any(needle in line for needle in _NEEDLES)
        )
        if hits:
            counts[path.relative_to(tests_root).as_posix()] = hits
    return counts


def test_no_test_substitutes_production_behaviour_undeclared() -> None:
    """Every substitution site is one of the examined, documented keeps.

    Proven able to fail: adding a ``monkeypatch.setattr`` anywhere under the
    tests package fails on the unexpected-site assertion naming that file;
    removing it restores the pass. Raising a declared count has the same
    effect through the count comparison.
    """
    found = _substitution_counts()
    expected = {name: count for name, (count, _reason) in _ALLOWED.items()}

    unexpected = {name: n for name, n in found.items() if name not in expected}
    assert not unexpected, (
        "new runtime substitution(s) added without a recorded justification: "
        f"{unexpected}. Drive the behaviour for real, or add the file here "
        "with the reason it cannot be."
    )

    grown = {
        name: (found[name], expected[name])
        for name in expected
        if name in found and found[name] > expected[name]
    }
    assert not grown, (
        f"substitution count grew in {grown} (found, allowed). Each new site "
        "needs its own recorded reason."
    )


def test_the_declared_sites_all_still_exist() -> None:
    """A keep that disappeared must be removed from the table, not left.

    Without this the allowance outlives the site it was written for, and the
    next substitution added to that file inherits a justification nobody wrote
    for it.
    """
    found = _substitution_counts()
    stale = {
        name: count
        for name, (count, _reason) in _ALLOWED.items()
        if found.get(name, 0) < count
    }
    assert not stale, (
        f"declared substitution sites no longer present: {stale}. Lower or "
        "delete the entry so the allowance cannot be inherited."
    )

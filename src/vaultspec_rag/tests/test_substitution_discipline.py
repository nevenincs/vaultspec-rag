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
    "test_cli_styled_output.py": (
        1,
        "styling reaches only a colour terminal, and the CLI builds its one "
        "console at import from the real stdout, so the styled bytes can only "
        "be read by handing the unchanged production renderers a real recording "
        "console; the substitute is the output sink, not any behaviour. "
        "Mutation proof: setting this allowance to zero failed the count-growth "
        "assertion; restoring one passed",
    ),
    "test_typesafe_search.py": (
        26,
        "search routing needs fixed candidate windows and forced provider failures "
        "to prove exact keyless fallback, ranking order, and timing boundaries. "
        "A live GPU index cannot reproduce those branch states on demand; the "
        "separate live spike exercises real provider answers",
    ),
    "test_typesafe_transport.py": (
        23,
        "the transport tests drive real loopback HTTP and force malformed frames, "
        "timeouts, credential rotation, and thread admission failures. The live "
        "provider cannot be made to emit those failures safely or repeatably; "
        "the separate live spike checks the hosted path",
    ),
    "test_cli_index_disk_preflight.py": (
        1,
        "the disk floor is a per-profile compile-time constant with no config "
        "override, so a real run cannot be driven under it; production's own "
        "ensure_disk_headroom raises, classifies and words the refusal",
    ),
    "test_cli_index.py": (
        8,
        "audit substitutions are one of three kinds. Most are "
        "tripwires that only ever raise - the audit must not reach the "
        "publication transport, and must reject a bad scope before reaching "
        "any transport at all - so none of them can make a regressed verb "
        "pass. Two stand in for the audit response so the verb's rendering of "
        "a clean and a drifted verdict is asserted without a populated "
        "backend to produce each one. One captures the outgoing call to prove "
        "the audit builds the request the route expects, which is a fact "
        "about the wire and is not observable from the verb's output",
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
    "test_publication_scaling.py": (
        1,
        "observation, not substitution: the replacement opens the real ledger "
        "connection and only attaches a trace callback and a progress handler "
        "to it, so every statement counted is one production actually issued "
        "and every instruction counted is one it actually retired. Those "
        "counts are the assertions - they are what prove a scoped publication "
        "examines the same number of rows whatever the parent's size - and "
        "SQLite reports both to connection-level callbacks or not at all. One "
        "site, not two: both seams are patched from a single helper, because "
        "patching either alone leaves the other untraced",
    ),
    "test_server_routes.py": (
        2,
        "one is a tripwire that only ever raises, so it cannot make a "
        "regressed route pass; the other stands in for the audit owner so the "
        "route is proven to delegate to it and return its verdict verbatim, "
        "which is the whole behaviour under test. Driving a real audit here "
        "would need a populated backend and would assert the auditor's "
        "correctness a second time rather than the route's delegation",
    ),
    "test_store.py": (
        1,
        "a tripwire: the replacement only ever fails the test, proving the "
        "audit read never reconciles the backend. A call that must not happen "
        "is not observable from outside the store, and asserting on state "
        "instead would pass whenever a reconcile happened to change nothing",
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
    "test_hardware_anchor.py": (
        1,
        "forces the machine anchor directory to be unresolvable, to prove the "
        "load window then degrades rather than refusing every load. A host "
        "with no directory every account shares does exist, but it cannot be "
        "staged on a runner: the suite cannot remove /dev/shm, /Users/Shared "
        "and the shared temporary directory, nor make the Windows known-folder "
        "API fail",
    ),
    "test_env_holders.py": (
        6,
        "drives the fail-closed branches of the holder query and the shapes a "
        "live table cannot be made to contain: a process whose image and "
        "directory both read as unknown, a table that cannot be enumerated at "
        "all, a launcher paired with the interpreter it re-executed, a shell "
        "that must not be paired with its child, and this process itself "
        "holding the tree so the launch-chain exclusion can be asked about. "
        "None can be provoked on demand - the first needs a process this user "
        "may not inspect, the second needs the operating system to refuse the "
        "walk, and the rest need a parentage the test cannot arrange around "
        "its own pid. Every relation the query reports is still driven for "
        "real elsewhere in the file, against real environments held by real "
        "child processes",
    ),
    "test_job_progress_durability.py": (
        1,
        "pins the progress flush budget so the publish under test lands inside "
        "it by construction. The budget is two tenths of a second and the test "
        "asserts the durable write is DEFERRED; establishing that from the "
        "adjacency of two calls is not sound on a machine that can deschedule "
        "a process for longer than the budget, where the write legitimately "
        "happens and the assertion reads as a regression. The paired test "
        "drives expiry for real against the production value",
    ),
    "test_model_setup.py": (
        1,
        "makes the load probe unavailable so the documented fallback runs. "
        "Windows raises this from PDH performance counters being disabled or "
        "unreadable by the agent's account, which cannot be provoked on a host "
        "whose counters work, and the alternative is a contract asserted only "
        "on the machines that never exercise it",
    ),
    "test_cli_storage_migrate.py": (
        6,
        "scripts the stores a migrate command opens so its EXIT STATUS can be "
        "asserted. Reaching that code for real needs a live Qdrant server and "
        "populated collections on both backends, which the unit tier has not "
        "got. The reported envelope is not covered by these: it is a pure "
        "function of the results, and is driven through the renderer itself "
        "with nothing substituted",
    ),
    "test_tool_env_provisioning_hostile.py": (
        1,
        "points the production CUDA-index constant at the loopback index the "
        "proofs serve. What is being proved is what uv records in a receipt "
        "and re-applies on a later upgrade, not which host the accelerated "
        "index lives on; resolving against the real one would put a network "
        "dependency and a multi-gigabyte download in a commit-gating test",
    ),
    "test_cli_status.py": (
        3,
        "redirects the daemon interpreter at a purpose-built tool "
        "environment. The receipt verdict is a fact about the environment "
        "that would serve, and a test cannot make the interpreter running it "
        "into a uv tool installation; asserting against whatever this "
        "developer's own daemon interpreter happens to be would assert "
        "nothing",
    ),
    "test_readiness_holders.py": (
        1,
        "widens the scan budget, which production sizes for an HTTP route: a "
        "walk of every process on a runner hosting a dozen parallel workers "
        "does not finish inside it, and the snapshot then honestly reports "
        "that it could not tell - indistinguishable, to an assertion about "
        "content, from finding no holder",
    ),
    "test_doctor_repair_and_holders.py": (
        16,
        "substitutes the interpreter probe, the daemon interpreter and the "
        "holder scan across three cases. The probe starts a child "
        "interpreter and imports torch in it, so a CPU-only build cannot be "
        "provoked on a GPU host and the defect branch would never run. The "
        "daemon interpreter is redirected at a purpose-built environment "
        "because the point of the assertion is that the verb asks about that "
        "environment rather than its own, which is untestable while the two "
        "are the same directory. The holder scan is substituted so the roots "
        "it is asked about can be observed and so a service-shaped holder "
        "exists at all; spawning one would mean starting a real daemon in a "
        "unit test. The later cases add the receipt verdict, the bounded "
        "holder list and a role from another release, each of which needs the "
        "same three boundaries staged again. Everything else is the real "
        "verb, including the whole render and envelope path the assertions "
        "read",
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
    "test_uv_sync.py": (
        2,
        "stands in for the uv the project sync launches: a uv that never "
        "returns cannot be staged with a real one, and the "
        "workspace-containment refusal must be observed without any uv "
        "running at all",
    ),
    "test_jobs_device_load.py": (
        5,
        "asserts the jobs-listing cache's call count and its handling of a "
        "cached-absent reading against the shared device-load reading, which "
        "requires forcing a controlled reading (and counting how often it is "
        "taken) - neither reachable through a real device on a CPU-only "
        "runner",
    ),
    "test_cli_install.py": (
        10,
        "the post-install warning classifies the running interpreter in a child "
        "process, and a client or an MPS-refused environment cannot be made on "
        "the test host without replacing its installed torch; only the child "
        "probe's verdict is substituted, and the real warning renderer, its "
        "defect gate and its topology remediation run unchanged. The refusal "
        "cases substitute the tool repair itself for the same reason the "
        "repair's own tests do - running it would reinstall packages in a real "
        "tool environment - and the consent cases observe what the install "
        "hands it, because the flag's whole effect is which authorisation "
        "arrives there. The run that counts interpreter probes also pins the "
        "environment's classification and its receipt verdict, so the count "
        "is of one known state rather than of whatever this host happens to "
        "be",
    ),
    "conftest.py": (
        3,
        "install's torch and provisioning steps and the release-mismatch advice "
        "all branch on whether this is a host or a client installation, and the "
        "role is read from the distributions the running interpreter holds. The "
        "accelerator-free lane never installs the gpu extra and the gpu lane "
        "always does, and the suite can neither add nor remove the inference "
        "stack in the shared interpreter, so each lane would otherwise reach "
        "only one side of every branch. Only the role reading is substituted; "
        "every consumer of it runs unchanged. Separately, both machine "
        "hardware anchors are pointed at private files for every test, "
        "because the machine's own anchors may be held by a live service, a "
        "test must never contend for them, and an ownership claim outlives "
        "the test that took it; only their location is substituted, and "
        "claiming, lending and refusing run unchanged",
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
        29,
        "the persistent uv tool interpreter and machine singleton cannot be "
        "safely forced through a CUDA repair during a test: that would install "
        "packages into the developer's own tool environment, which is how a "
        "live installation was once emptied. The tests retain the real repair "
        "transaction and substitute only its externally-owned observations - "
        "the child interpreter probe, the environment classification, the "
        "receipt verdict, the process table and the uv launch itself - with "
        "sentinels that fail if consent, a foreign target, an unreadable "
        "release, a holder, a no-device diagnosis, the CUDA re-probe or the "
        "receipt postcondition is bypassed. The count is high because each "
        "guard stages the same boundaries again for the one branch it proves",
    ),
    "test_watcher_controller_intake.py": (
        11,
        "the intake durability tests intercept the persistence boundary to prove "
        "commit-before-ack and cancellation ordering; the scheduler wiring test "
        "captures registration and supplies an otherwise host-dependent storage "
        "measurement; and the pre-creation recovery test forces failures at the "
        "preflight and manager boundaries. Real equivalents require crashing or "
        "changing the service's live storage state at an exact instruction "
        "boundary. The post-creation admission tests use the real process job "
        "manager but skip scoped preflight, which needs the root's GPU compute "
        "lease; they wrap the real create to land an intake observation at the "
        "instant the job exists, which no real event can be timed to hit; and "
        "they replace dispatch, which would run a real GPU index attempt, with "
        "one that records, fails, or really binds and dispatches before failing",
    ),
    "test_watcher_recovery.py": (
        1,
        "restart reconciliation requires a durable attempt whose recorded owner is "
        "provably dead; substituting the process-liveness observation avoids killing "
        "a real owner while every durable scope and job-history transition remains "
        "real",
    ),
    "_run_ledger_test_support.py": (
        1,
        "a peer's schema commit must land between two particular reads of one "
        "opener to prove those reads share a snapshot; the read helper is wrapped "
        "only to run the real peer commit at that point, and it still returns the "
        "real row, so every read, lock and refusal stays real",
    ),
    "test_vault_checkpoint.py": (
        1,
        "a proof written under an older vault point schema can only come from an "
        "older build; lowering the schema constant for the one rebuild that writes "
        "it lets the real ledger record and then refuse that proof, with every "
        "ledger, signature and publication step left real",
    ),
    "test_process_termination.py": (
        19,
        "the states under test - a child whose exit waitpid acknowledges, a "
        "zombie that is not this process's child, a PID reused after exit - "
        "are kernel states that cannot be produced on demand, and a zombie "
        "cannot exist on Windows at all. Most substitutes are tripwires that "
        "only fail the test when a forbidden probe or sleep is reached, so "
        "none can make a regressed path pass",
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

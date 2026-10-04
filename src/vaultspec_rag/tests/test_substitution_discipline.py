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
    # Reducing this bound to zero failed count growth; exact restoration passed.
    "integration/_shutdown_storage_control.py": (
        1,
        "root-scoped scheduling instrumentation in the canonical server child: "
        "the wrapper delegates real confirmed storage accounting before "
        "publishing a witness and waiting at the normal cooperative checkpoint. "
        "Live inference cannot reliably schedule shutdown after storage but "
        "before publication. Models, storage, checkpoint interruption, release "
        "ordering and HTTP diagnostics remain real. The parent releases the "
        "barrier on failure and the wrapper restores itself on every exit",
    ),
    "test_attempt_memory_telemetry.py": (
        2,
        "the embedding model is deliberately constructed unloaded, so its "
        "forward call is replaced to record a chosen, exact CUDA peak across "
        "two attempts and prove a new checkpoint never inherits the prior "
        "one's memory facts; a real forward on this CPU-only runner cannot "
        "report a chosen exact peak at all, let alone two distinct ones on "
        "demand. The manager's resilience publication is wrapped to call "
        "through to the real update and only record the accepted snapshots, "
        "because the manager keeps the latest publication only and an "
        "attempt's opening fact is otherwise overwritten before a test can "
        "read it",
    ),
    "test_route_scan_classification_cache.py": (
        2,
        "wraps ResolvedIndexPolicy.classify and RunPolicy.checkpoint to record "
        "each call before delegating to the real implementation, because the "
        "route scan wraps the production classify method directly in an "
        "lru_cache and its deduplication is observable only by counting how "
        "many times the underlying method actually runs; the real "
        "classification and checkpoint logic execute unchanged on every call",
    ),
    "test_search_conformance_refusal.py": (
        1,
        "the model-free count path a registry exposes never checks storage "
        "identity, by design - counting must not require a GPU - so a real "
        "mismatched collection cannot make it raise the typed conformance "
        "error the combined count's exception handling must classify. The "
        "substitute routes the count through the same real, already-mismatched "
        "store's real search instead, which does carry the conformance check; "
        "every store, identity and search call involved is real",
    ),
    "test_search_readiness_responsiveness.py": (
        2,
        "wraps the real publication-snapshot read to hold it open until the "
        "event loop's own heartbeat is observed running, because a live disk "
        "read cannot be made to take long enough to prove responsiveness on "
        "demand, and it still returns the real snapshot. The job snapshot is "
        "redirected to a fixed empty list because it is read from a live "
        "process-wide job-manager singleton shared by the whole test session "
        "and never reset between tests; a leftover job from an unrelated test "
        "would make this responsiveness assertion flake on content it did not "
        "create",
    ),
    "test_search_readiness_restore.py": (
        6,
        "three sites redirect the canonical job snapshot away from that same "
        "live, session-wide job-manager singleton to a deterministic empty or "
        "fixed input, for the reason above. The other three wrap the real "
        "publication-snapshot read, or the real proof-token validate, to run a "
        "genuine concurrent mutation - a real ledger reservation, or a real "
        "publish on a separate thread - at the one instant between a read and "
        "its later validation; a live race cannot be scheduled to land there, "
        "and every object returned and every ledger operation run is real",
    ),
    "test_service_cleanup_callers.py": (
        1,
        "stages an already-read, stale service-status snapshot ahead of a real "
        "successor already published to disk, because the only way a caller "
        "legitimately holds a stale snapshot is a prior read racing a "
        "concurrent republish, which cannot be scheduled to land on demand; "
        "every subsequent process probe and the locked deletion use the actual "
        "dead child and the real on-disk record",
    ),
    "test_service_launcher_lifetime.py": (
        1,
        "fresh CPU child refuses only the named launcher-waiter thread start; "
        "exhausting host threads cannot safely or repeatably cause this branch. "
        "Canonical process creation, detached flags, argv witness discovery, "
        "termination and launcher reaping remain real. The patch restores in "
        "its context, and both successful and failed handoffs retain strict "
        "ResourceWarning checks. Missing declaration fails; a second site "
        "exceeds this exact bound",
    ),
    "test_service_stop_cleanup.py": (
        2,
        "one wraps the real termination-and-confirm call to publish a real "
        "successor status immediately after it returns, modelling a successor "
        "process winning the race to publish between an old stop's termination "
        "and its cleanup write - a window a live schedule cannot be timed to "
        "hit. The other sets a signal the instant a real deletion reaches the "
        "real shared write lock, which a separate real process is holding, so "
        "the test can prove the deletion blocks on that lock rather than on a "
        "fixed sleep; both wrappers delegate every lock and write to the real "
        "implementation",
    ),
    "test_service_stop_port.py": (
        5,
        "forces four OS-query failures that a real, currently-running child "
        "process this test owns cannot be made to produce on demand: an "
        "unreadable process-start time, the same call reporting a different "
        "birth on a second read to model a PID reused by another image mid- "
        "inspection (patched at both of its two import sites), a held machine "
        "lock reported with an unidentifiable holder pid, and an unreadable "
        "process argv. Every surrounding identity check, termination and "
        "discovery read or write stays real; only the fact the OS reports back "
        "is substituted, because reproducing any of these four states for real "
        "means racing or defeating the kernel's own process table",
    ),
    "integration/_served_drift_control.py": (
        2,
        "root-scoped fault and scheduling instrumentation in the canonical "
        "server child: one wrapper delegates the actual durable source commit "
        "before failing once; one delegates the actual indexing pipeline after "
        "a parent-controlled source edit following admission. A natural disk "
        "failure risks unrelated storage and live inference cannot schedule "
        "the edit repeatably. Models, storage, retry, drift classification and "
        "HTTP health remain real. Both wrappers restore themselves on exit. "
        "Mutation proof: reducing two to one fails the count-growth assertion; "
        "restoring two passes",
    ),
    "test_cli_styled_output.py": (
        1,
        "styling reaches only a colour terminal, and the CLI builds its one "
        "console at import from the real stdout, so the styled bytes can only "
        "be read by handing the unchanged production renderers a real recording "
        "console; the substitute is the output sink, not any behaviour. "
        "Mutation proof: setting this allowance to zero failed the count-growth "
        "assertion; restoring one passed",
    ),
    "test_code_consumer_progress.py": (
        3,
        "a replayed zero-chunk ledger write is replaced with one that raises "
        "after its real validation so the policy-rejection failure branch is "
        "reached without actually corrupting the on-disk ledger, which would "
        "need a real disk or permission fault of the exact kind no runner can "
        "stage on demand. The producer/consumer publication-order test wraps "
        "the reporter's publish and the checkpoint's zero-chunk record with "
        "call-through instrumentation that holds one real thread at the exact "
        "instant the other's durable outcome resolves, which a live schedule "
        "cannot be timed to hit; both wrappers run the real body before or "
        "after the held point and change nothing it computes",
    ),
    "test_code_pipeline_retained_ids.py": (
        1,
        "the cheap in-memory drift observation can miss a race by design; "
        "forcing that miss is the only way to reach the real ledger's own "
        "indexed-path collision detection, which a live race cannot be "
        "scheduled to trigger on demand. Storage, chunking and retirement "
        "stay real throughout",
    ),
    "test_confirmed_chunk_progress.py": (
        1,
        "the chunk and file progress classification is pure arithmetic over "
        "timestamps replayed across hundreds of simulated seconds; a "
        "controllable clock is substituted for the module's time source so "
        "the cadence is deterministic, because driving the same assertions "
        "with real sleeps would make the suite minutes slower and flaky "
        "against scheduling jitter. Nothing else about progress, rate or "
        "degradation computation is replaced",
    ),
    "test_content_route_migration.py": (
        1,
        "wraps the real local-store scroll with a recording proxy that still "
        "executes it, because the arguments a migration scan passes at that "
        "boundary - with_vectors false, with_payload true - are not otherwise "
        "observable from any value the scan returns",
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
    "test_quiesce_abort_recovery.py": (
        4,
        "wraps the quiesce controller's abort_pause, and the atomic-write "
        "durability call, to land an injected fault or assertion at one exact "
        "point in the resume/recovery sequence - mid-abort, between a "
        "protected acknowledgement and reopening admissions, or between a "
        "durable rename and its following sync fault. A live resume races "
        "background job threads and the operating system, so none of these "
        "points can be scheduled against real timing; every wrapper calls "
        "through to the real implementation for the rest of its work, and the "
        "quiesce state machine, job manager and persisted state stay real "
        "throughout",
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
    "test_encode_bucket_planner.py": (
        1,
        "proves the lockless sparse forward now enters the peak-capture "
        "bracket the locked branch already used, but a real capture is "
        "indistinguishable from a no-op without a CUDA device; the bracket is "
        "substituted only to count entries, and the forward itself stays real",
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
    "test_incremental_failure_classification.py": (
        2,
        "the embedding model is deliberately constructed unloaded, so its "
        "forward call is replaced with a fixed-vector stand-in; a real forward "
        "on this CPU-only runner is not available. The store's model-free "
        "count is wrapped to call through to the real count and raise only "
        "once a specific generation has actually transitioned to SUCCEEDED in "
        "the real ledger, modelling an exception raised by the caller after a "
        "real durable publication commits but before the call returns - a "
        "window a live schedule cannot be timed to hit",
    ),
    "test_index_cuda_reservation_credit.py": (
        1,
        "forces an exact CUDA device memory reading so the reservation-credit "
        "ceiling math can be checked against known allocated and reserved "
        "figures; no real device reports a chosen exact pair of megabyte "
        "readings on demand, and this runner has none besides. Torch itself "
        "is never imported and the ceiling and credit computation under test "
        "run unchanged",
    ),
    "test_env_holders.py": (
        7,
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
        "child processes. The additional lazy-row witness records which rows "
        "request a parent pid: the OS returns the value but cannot expose "
        "whether this query requested an unused one, and elapsed time cannot "
        "establish that on a variably loaded runner. Holder classification, "
        "exclusions and parent pairing remain production behaviour",
    ),
    "test_generation_survey.py": (
        1,
        "root-scoped scheduling instrumentation: the wrapper calls through to "
        "the real publication-snapshot acquisition and then, only on its "
        "first hit for the root under test, reserves a real conflicting "
        "receipt - and for one phase rolls it back - in the gap between "
        "acquisition and validation. Live survey and publication traffic "
        "cannot be scheduled to land a conflicting write in that exact gap on "
        "demand; every proof, ledger and survey operation involved is real",
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
    "test_cli_storage_generation_diagnostics.py": (
        3,
        "a unit-level CLI JSON round-trip needs specific generation facts - "
        "unattributed, unreadable, empty and debt namespaces, and malformed "
        "model maps - behind the service transport, so the admin fetch is "
        "replaced with a canned survey payload; reaching the same conditions "
        "through a live server needs a populated GPU-backed backend the unit "
        "tier does not have, and the separate subprocess survey test drives "
        "the real route. Pytest's own tmp_path lives under the real OS temp "
        "directory, so the uncached tempfile answer would make every root "
        "temp-rooted regardless of the published fact; tempfile.tempdir is "
        "substituted only so the server and client temp roots can be varied "
        "independently of that shared ancestor, and is_temp_rooted's own "
        "environment-variable reading runs unchanged",
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
    "test_donor_admission.py": (
        12,
        "isolates the real admission ranking and gate logic from the "
        "manifest, git, store-transport and settings boundaries it reads, "
        "because the bounded-inspection-window and family/newest/prefix "
        "ordering are proved against a hundred synthetic donor candidates "
        "with controlled per-candidate failures - an absent or unreadable "
        "pointer, an absent or unreadable proof, a capability refusal, an "
        "unsupported collection. Building a hundred real donor projects and "
        "git repositories, and forcing each one's publication reads to fail "
        "on demand, is not something a unit test can construct. Only the "
        "manifest load, prefix derivation, pointer and proof readers, git "
        "lookup, model identity, vector schema and config accessors are "
        "replaced; the ranking, gating, inspection-bounding and vector "
        "adoption logic under test run unchanged",
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
        1,
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
    "test_lifespan_storage_tasks.py": (
        1,
        "component startup must not perform a real GPU model load in a "
        "CPU-only unit test; only ServiceRegistry.load_model is replaced "
        "with a no-op, and the real discovery publisher, maintenance "
        "scheduler, heartbeat, borrower lease recovery and survey warmup "
        "tasks it starts all run unchanged on top of it",
    ),
    "test_machine_lock_presence.py": (
        2,
        "wraps the real Path.stat and the real anchor-open call so that, only "
        "for the exact machine-lock anchor path under test, they raise a "
        "permission, I/O or not-a-directory fault instead of running; every "
        "other path still goes through the genuine call. The resolver must "
        "treat that fault as degraded rather than absent, and neither fault "
        "can be staged by changing real filesystem permissions across the "
        "platforms this suite also runs on. The holder process, the real "
        "anchor file and the lock-claim machinery stay real",
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
        5,
        "asserts the stdio runner wires watcher cleanup and loads no model - "
        "both observable only at the instant the MCP transport is entered, "
        "and mcp.run(transport='stdio') blocks on real stdin forever, so the "
        "transport, the lifetime watchdog it arms, and the model load it must "
        "not perform are the three boundaries substituted; the source scans "
        "these replaced read main(), a two-line dispatcher containing neither "
        "contract, and passed against a real load added one frame down. The "
        "health lock-wait test calls the real handler over a real registry, "
        "store and held lock, and substitutes two facts the handler reads "
        "from outside that path: the device load reading, which needs an "
        "accelerator a unit run does not have, and the process start stamp, "
        "which only the server entry point sets and this handler-level test "
        "never runs",
    ),
    "test_tool_torch_repair.py": (
        28,
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
        14,
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
        "one that records, fails, or really binds and dispatches before failing. "
        "The typed-refusal test raises the full-reindex refusal from that same "
        "preflight boundary, since a real one needs a publication made "
        "incompatible under a held compute lease; and the two terminal-outcome "
        "tests hold dispatch so the created job stays put while the real "
        "manager and the real durable policy settle it",
    ),
    "test_watcher_filter_offload.py": (
        10,
        "the intake loop is driven by the operating system's change "
        "notifications, which cannot be made to deliver an exact batch - a "
        "control file together with an ignored path, a deletion and a path "
        "outside the root - in a chosen order and then stop, so the native "
        "notifier is replaced with a queue that hands over those batches and "
        "ends the watch. Three further sites keep the loop standalone: the "
        "bindings are built from real retry policies, slots and controllers "
        "but supplied directly, because the real initialiser needs a served "
        "root, and controller unregistration and the scheduler wake-up are "
        "silenced because no scheduler runs here. Four sites wrap the real "
        "filter, the real classifier, the real policy-file read and the real "
        "persist step and call straight through: three hold a worker at a "
        "barrier so the test can observe the event loop still turning, which "
        "a real disk read is too fast to show, and one records which paths "
        "were accepted. The remaining two replace the stored-ownership read "
        "with a recorder, because real stored owners need an index "
        "publication this intake-only test never makes; what is asserted is "
        "that the read is not reached for a rejected path",
    ),
    "test_watcher_index_resilience.py": (
        2,
        "substitutes the external encoder forward with a fixed-vector stand-in so "
        "model loading, lifecycle and watcher wiring stay real without a GPU; and "
        "forces the resilience-snapshot projector to raise, because the only real "
        "route to that exception is a corrupted checkpoint state the test cannot "
        "assemble without first causing the very failure it exists to test around",
    ),
    "test_watcher_publication_certification.py": (
        5,
        "two source-entry replacements return contradictory or missing current "
        "checkpoint outcomes that corrected pipelines cannot produce on demand, "
        "so the real dispatcher must reject them. Two admission replacements "
        "retain actual policy validation while avoiding hardware admission for "
        "deliberately unloaded CPU indexers. One supplies their CPU compute "
        "lease instead of loading a model. Actual checkpoint observation, "
        "SQLite ledger, proof publication, JobManager dispatch, typed failure "
        "and completion remain real. Mutation proof: reducing five to four "
        "fails the exact count-growth assertion; restoring five passes",
    ),
    "test_watcher_rebuild_reconciliation.py": (
        5,
        "three sites wrap the real publication-snapshot read to observe which "
        "source it was asked for, or to hold it open across a real second thread "
        "so a concurrent retry-state refresh is proven not to block on it; a live "
        "schedule cannot be timed to land in that exact window, and every wrapper "
        "still returns the real snapshot it reads. Two force the recorded attempt "
        "owner to read as dead, because the owner recorded by a real admission is "
        "this test process itself, which is genuinely alive, and killing this "
        "process to produce a dead owner is not an option; every durable scope, "
        "ledger and job-history transition the reconciliation reads stays real",
    ),
    "test_watcher_recovery.py": (
        1,
        "restart reconciliation requires a durable attempt whose recorded owner is "
        "provably dead; substituting the process-liveness observation avoids killing "
        "a real owner while every durable scope and job-history transition remains "
        "real",
    ),
    "test_watcher_root_identity.py": (
        2,
        "points the module-level watcher scheduler and the resident-task registry "
        "at test-scoped values, because production reads both from process "
        "globals with no constructor override; only their location is "
        "substituted, since the scheduler instance registered in their place and "
        "the task it maps are themselves real, driving real controllers through "
        "the real HTTP route",
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
    "test_vault_payload_batching.py": (
        7,
        "wraps the real local QdrantLocal batch_update_points with a recording "
        "proxy that delegates every call to the captured original, because the "
        "RPC-level request shape under test - the exact chunk bound per batch, "
        "which requests wait for applied changes, and the timeout each one "
        "carries - is only observable at that boundary, not from any return "
        "value the store exposes. Several sites also inject a config flip, a "
        "short result or a transport failure from inside that same proxy at a "
        "precise point between two particular batches, which a live retry or a "
        "live config change cannot be scheduled to land on demand; every write "
        "that is not the injected failure still reaches the real local store",
    ),
    "test_vault_progress_phases.py": (
        5,
        "replaces the prior-generation publication read, the parent-checkpoint "
        "construction and its recovery check, the donor-reuse resolution, and "
        "the encode-and-upsert worker, so this test exercises only the public "
        "scoped entry, hashing, classification and the phase-reporting machinery "
        "under test. Standing up a full embedding model and a prior real Qdrant "
        "generation to produce the same fixed evidence would trade a GPU-bound "
        "production path for a GPU-free workaround without changing what the "
        "test proves; hashing, classification, scoped payload preparation and "
        "the phase machinery stay production",
    ),
    "test_vault_readiness_publication.py": (
        6,
        "two sites disable the donor-reuse optimisation and two replace the "
        "encode-and-upsert worker, because this test is about durable "
        "publication and readiness notification, not reuse or GPU encoding, and "
        "both require a populated backend or a loaded model the unit tier does "
        "not have. One substitutes GPU model loading with a fixed object for "
        "the same reason. One forces a disk or ledger failure at the exact "
        "durable-publish boundary, which cannot be induced on a real filesystem "
        "on demand; the actual publication, checkpoint and readiness-wake code "
        "under test runs unchanged in every case",
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

"""Decide how much of the merge gate a commit still has to measure.

Run by the merge gate's scope job and the release workflow's parent proof, on a
hosted runner that has only the standard library and ``gh``. The script is
invoked with ``python3 -I``, so it imports nothing from this repository.

Three answers, written to the job's ``suites`` output:

- ``full``: run everything. The answer whenever anything is unclear, because a
  wrong ``full`` costs an hour and a wrong skip lands unmeasured code.
- ``reused``: this commit's tree is the tree a merged pull request already
  passed every suite on. Only what can change without the tree changing runs
  again: the advisory audit and code scanning.
- ``proof``: this commit changes nothing but release version files over a parent
  the gate already passed. Nothing runs; the release cut audits the lock and runs
  the accelerator tiers before any tag exists.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

    Api = Callable[[str], Any]

FULL = "full"
REUSED = "reused"
PROOF = "proof"

GATE_WORKFLOW = "merge-gate.yml"
RELEASE_BOT = "nevenincs-release[bot]"
FULL_RUN_LABEL = "ci:full"
SCOPE_JOB = "Check: Proof scope (Linux)"

#: Every measuring job of one gate run. All of them passing is complete proof.
MEASURING_JOBS = frozenset(
    {
        "Check: Full lint (Linux)",
        "Test: Correctness suite (Linux, 3.13)",
        "Test: Correctness suite (Linux, 3.14)",
        "Test: Full suite (Windows)",
        "Check: Dependency advisories (Linux)",
        "Check: Code scanning (Linux, actions)",
        "Check: Code scanning (Linux, javascript-typescript)",
        "Check: Code scanning (Linux, python)",
    }
)

#: What Release Please writes when it proposes a version.
VERSION_FILES = frozenset(
    {
        ".release-please-manifest.json",
        "CHANGELOG.md",
        "pyproject.toml",
        "uv.lock",
        "docs/installation.md",
    }
)

#: Files in :data:`VERSION_FILES` that also configure what the suites run, so
#: only their version lines may change.
VERSION_LINE_ONLY = frozenset({"pyproject.toml", "uv.lock"})

#: Attempts and seconds between them while a parent's gate is still running:
#: two hours, under the jobs' own ceilings.
POLL_ATTEMPTS = 120
POLL_SECONDS = 60

#: The compare endpoint lists at most this many files, so a response this long
#: may be hiding the file that disqualifies it.
COMPARE_FILE_CAP = 300


class GitHubError(Exception):
    """A GitHub API read failed."""


def _gh_api(path: str) -> Any:
    """Return one parsed GitHub API response for this repository."""
    repository = os.environ["GITHUB_REPOSITORY"]
    result = subprocess.run(
        ["gh", "api", f"repos/{repository}/{path}"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise GitHubError(f"gh api {path}: {result.stderr.strip()}")
    return json.loads(result.stdout)


def _version_line_change(patch: str) -> bool:
    """Whether every changed line in a unified *patch* is a ``version =`` line."""
    changed = (
        line
        for line in patch.splitlines()
        if line[:1] in {"+", "-"} and not line.startswith(("+++ ", "--- "))
    )
    return all(line[1:].startswith('version = "') for line in changed)


def non_version_change(files: list[dict[str, Any]]) -> str | None:
    """Return why a compare's *files* are more than a version bump, or ``None``.

    A version-line file with no patch fails: GitHub omits the patch on a large
    diff, and an unreadable diff is not a version bump.
    """
    if len(files) >= COMPARE_FILE_CAP:
        return f"the comparison reached the {COMPARE_FILE_CAP}-file listing cap"
    for entry in files:
        name = str(entry.get("filename"))
        if name not in VERSION_FILES:
            return f"{name} is not a release version file"
        if entry.get("previous_filename"):
            return f"{name} was renamed"
        if name in VERSION_LINE_ONLY:
            patch = entry.get("patch")
            if not isinstance(patch, str):
                return f"{name} has no readable diff"
            if not _version_line_change(patch):
                return f"{name} changes more than its version line"
    return None


def push_gate_state(api: Api, sha: str) -> str:
    """Return the state of the newest push gate on *sha*.

    One of ``success``, ``running`` or the conclusion it ended with. Only a
    push run proves a commit that landed, and the newest one decides.
    """
    runs = api(
        f"actions/workflows/{GATE_WORKFLOW}/runs?head_sha={sha}&event=push&per_page=10"
    )["workflow_runs"]
    if not runs:
        return "running"
    newest = max(runs, key=lambda run: (run["created_at"], run["id"]))
    if newest["status"] != "completed":
        return "running"
    return str(newest["conclusion"])


def wait_for_push_gate(
    api: Api, sha: str, sleep: Callable[[float], None] = time.sleep
) -> str:
    """Return the settled state of *sha*'s push gate, or ``running`` on timeout."""
    state = "running"
    for attempt in range(POLL_ATTEMPTS):
        state = push_gate_state(api, sha)
        if state != "running":
            return state
        if attempt < POLL_ATTEMPTS - 1:
            sleep(POLL_SECONDS)
    return state


def _newest_attempts(jobs: list[dict[str, Any]]) -> dict[str, str | None]:
    """Return each job name's conclusion in its newest attempt."""
    newest: dict[str, tuple[int, int, str | None]] = {}
    for job in jobs:
        rank = (int(job["run_attempt"]), int(job["id"]), job["conclusion"])
        name = str(job["name"])
        if name not in newest or rank[:2] > newest[name][:2]:
            newest[name] = rank
    return {name: rank[2] for name, rank in newest.items()}


def pull_request_passed_every_suite(api: Api, head: str) -> bool:
    """Whether the newest proof on pull-request *head* measured every suite.

    Walks completed runs newest first. A run an unrelated label started measures
    nothing and only carries earlier proof forward, so it is passed over; any
    other result ends the walk, so an older green cannot outlive a newer red.
    """
    runs = api(
        f"actions/workflows/{GATE_WORKFLOW}/runs"
        f"?head_sha={head}&event=pull_request&status=completed&per_page=100"
    )["workflow_runs"]
    for run in sorted(runs, key=lambda item: int(item["id"]), reverse=True):
        if run["conclusion"] != "success":
            return False
        jobs = _newest_attempts(
            api(f"actions/runs/{run['id']}/jobs?filter=all&per_page=100")["jobs"]
        )
        measured = [jobs.get(name) for name in sorted(MEASURING_JOBS)]
        if all(conclusion == "success" for conclusion in measured):
            return True
        preservation = (
            all(conclusion == "skipped" for conclusion in measured)
            and jobs.get(SCOPE_JOB) == "skipped"
        )
        if not preservation:
            return False
    return False


def _tree(api: Api, sha: str) -> str:
    """Return the tree of commit *sha*."""
    return str(api(f"commits/{sha}")["commit"]["tree"]["sha"])


def _merged_with_identical_tree(api: Api, sha: str) -> str | None:
    """Return the head of the pull request that landed *sha* with its exact tree."""
    tree = _tree(api, sha)
    for pull in api(f"commits/{sha}/pulls"):
        if pull.get("merge_commit_sha") != sha or not pull.get("merged_at"):
            continue
        head = str(pull["head"]["sha"])
        if _tree(api, head) == tree:
            return head
    return None


def decide_push(api: Api, sha: str, sleep: Callable[[float], None]) -> tuple[str, str]:
    """Return ``(suites, reason)`` for a commit that landed on the default branch."""
    commit = api(f"commits/{sha}")
    parents = commit["parents"]
    if not parents:
        return FULL, "a root commit has no parent proof"
    parent = str(parents[0]["sha"])
    change = non_version_change(api(f"compare/{parent}...{sha}")["files"])
    if change is None:
        state = wait_for_push_gate(api, parent, sleep)
        if state == "success":
            return PROOF, f"a version bump over {parent}, whose push gate passed"
        change = f"parent {parent}'s push gate is {state}"
    head = _merged_with_identical_tree(api, sha)
    if head is None:
        return FULL, f"{change}, and no merged pull request carries this exact tree"
    if not pull_request_passed_every_suite(api, head):
        return FULL, f"{change}, and pull-request head {head} lacks complete proof"
    return REUSED, f"the tree pull-request head {head} passed every suite on"


def decide_pull_request(
    api: Api,
    *,
    author: str,
    head: str,
    base_ref: str,
    sleep: Callable[[float], None],
) -> tuple[str, str]:
    """Return ``(suites, reason)`` for a ready pull-request head.

    Only the release App's proposal may skip: every other pull request is the
    measurement its later landing reuses.
    """
    if author != RELEASE_BOT:
        return FULL, f"{author} is not the release App"
    comparison = api(f"compare/{base_ref}...{head}")
    if comparison["behind_by"] != 0:
        return FULL, f"{comparison['behind_by']} commit(s) behind {base_ref}"
    change = non_version_change(comparison["files"])
    if change is not None:
        return FULL, change
    base = str(comparison["merge_base_commit"]["sha"])
    state = wait_for_push_gate(api, base, sleep)
    if state != "success":
        return FULL, f"base {base}'s push gate is {state}"
    return PROOF, f"a version bump over {base}, whose push gate passed"


def decide(
    api: Api, env: dict[str, str], sleep: Callable[[float], None]
) -> tuple[str, str]:
    """Return ``(suites, reason)`` for the event described by *env*."""
    event = env.get("EVENT", "")
    if event == "push":
        return decide_push(api, env["SHA"], sleep)
    if event != "pull_request":
        return FULL, f"{event or 'an unknown event'} always measures"
    if env.get("ACTION") == "labeled" and env.get("LABEL") == FULL_RUN_LABEL:
        return FULL, f"{FULL_RUN_LABEL} was pressed"
    return decide_pull_request(
        api,
        author=env.get("AUTHOR", ""),
        head=env["HEAD_SHA"],
        base_ref=env["BASE_REF"],
        sleep=sleep,
    )


def prove_release_head(
    api: Api, sha: str, sleep: Callable[[float], None]
) -> str | None:
    """Return why the release head *sha* may not be cut, or ``None``."""
    parents = api(f"commits/{sha}")["parents"]
    if not parents:
        return f"release head {sha} has no parent"
    parent = str(parents[0]["sha"])
    change = non_version_change(api(f"compare/{parent}...{sha}")["files"])
    if change is not None:
        return f"the release head changes more than its version files: {change}"
    state = wait_for_push_gate(api, parent, sleep)
    if state != "success":
        return f"parent {parent}'s {GATE_WORKFLOW} push run is {state}"
    return None


def main(argv: list[str]) -> int:
    """Run ``decide``, or ``prove <sha>``, and return the exit code."""
    if argv[:1] == ["prove"] and len(argv) == 2:
        failure = prove_release_head(_gh_api, argv[1], time.sleep)
        if failure is not None:
            print(f"::error::{failure}")
            return 1
        print(f"{argv[1]} changes only version files over a proven parent")
        return 0
    if argv != ["decide"]:
        print("usage: gate_scope.py decide | prove <sha>", file=sys.stderr)
        return 2
    try:
        suites, reason = decide(_gh_api, dict(os.environ), time.sleep)
    except GitHubError as error:
        suites, reason = FULL, f"GitHub could not answer: {error}"
    print(f"{suites}: {reason}")
    with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as output:
        output.write(f"suites={suites}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

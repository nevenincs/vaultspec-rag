---
tags:
  - '#research'
  - '#ci-self-hosted-gpu-runner'
date: '2026-07-23'
modified: '2026-07-23'
related: []
---

# `ci-self-hosted-gpu-runner` research: `Self-hosted GPU CI runner and CI tier split`

This project is GPU-only, yet its CI executes entirely on GitHub-hosted Linux
with no GPU. Every test carrying a GPU-bearing marker is deselected with
`-m "not (integration or quality or performance or robustness or subprocess_gpu or cuda)"`, so the CI green light only ever means the tokenless unit subset
passed; the 694 integration, 24 quality, 14 performance, 3 robustness, 66
subprocess-GPU, and 3 CUDA tests never run in CI. The question is how to make
the GPU tier actually execute in CI without either paying for GPU cloud minutes
or exposing the developer's workstation to arbitrary fork code. The evidence
below favours a self-hosted GPU runner for the heavy tier, a hosted runner for
the cheap tier, and a trusted-event gate as the security boundary.

## Findings

### The GPU tier is real work that a hosted runner cannot do

The suite splits cleanly by cost. The tokenless unit population runs anywhere;
the rest needs a real CUDA device. `pyproject.toml` registers the markers and
the root `conftest.py` gate (`pytest_runtestloop`) hard-fails the run if a
GPU-marked test is collected without `HF_TOKEN`, because the gated model
`naver/splade-v3` must be pullable. Marker census on 2026-07-23:
`cuda` 3, `integration` 694, `quality` 24, `performance` 14, `robustness` 3,
`subprocess_gpu` 66. The device is an RTX 4080 SUPER, 16 GB VRAM; the in-process
`gpu_lock` serialises compute, but `subprocess_gpu` tests spawn a second
model-loading process whose VRAM sits outside that lock, so they must not
co-schedule with the serialized markers on a 16 GB card.

### Self-hosted runners on a public repo are a remote-code-execution surface

The repository `nevenincs/vaultspec-rag` is public. GitHub's own guidance is
blunt: only use self-hosted runners with private repos, because a fork pull
request can run arbitrary code on the runner host and reach the job's secrets
and `GITHUB_TOKEN`. Anyone who can fork and open a PR (i.e. anyone with read
access) can compromise a persistent runner. The documented mitigations are:
never run fork PR code in a privileged/secret-bearing job; require approval for
outside collaborators; avoid `pull_request_target` with a PR-head checkout; and
prefer ephemeral runners so a compromised job leaves no residue for the next.
Sources: GitHub Docs "Secure use reference"; the community discussion on
self-hosted runners with public repos (#26722); Wiz and GitGuardian hardening
guides.

### The trusted-event gate is the load-bearing control

A same-repo branch requires write access to create, so `push`,
`workflow_dispatch`, and a `pull_request` whose head repository equals the base
repository are all trusted; only a fork PR carries a different head repo. The
idiomatic guard is
`github.event_name != 'pull_request' || github.event.pull_request.head.repo.full_name == github.repository`,
which admits the three trusted paths and refuses fork PRs from the GPU job
entirely, so fork code never reaches the runner and never sees a secret. This is
belt-and-braces with the repo Actions setting that requires approval before a
fork PR can start any run.

### The machine already runs a sibling runner; instances are per-directory

The host already has a configured runner at `C:\actions-runner` bound to a
different repository (`nevenincs/cadrumo`). GitHub's runner supports multiple
independent instances on one machine, each in its own directory with its own
`_work` tree and its own Windows service
(`actions.runner.<owner>-<repo>.<name>`). A second instance in a separate
directory registers and runs without disturbing the first. The runner installs
as a delayed-auto-start Windows service; the default service account is
`NT AUTHORITY\NETWORK SERVICE`, which can reach the system-wide CUDA driver and,
because it has a distinct profile, is naturally isolated from the developer's
per-user resident service (different storage dir, different machine-singleton
lock path). Runner package `actions/runner@v2.336.0`, win-x64, is
SHA256-pinned in the release notes
(`d59123a43003e357b0805b5d0f611d0bd2f65ab67d51bd070dd4e7a0f685c162`).

### Machine-identity leakage is a live incident theme

Real paths (`Y:\code\...`), the username, the hostname, and any runner
registration token must never land in tracked files. Registration tokens are
short-lived secrets minted on demand
(`POST /repos/{owner}/{repo}/actions/runners/registration-token`, ~1 h TTL);
the local `gh` token (scopes `repo`, `workflow`) can mint them. The runner
install lives outside the repo tree; workflow files name only generic labels
(`self-hosted`, `windows`, `gpu`, `cuda`). `.github/actionlint.yaml` must list
any custom label or `actionlint` rejects the `runs-on` array.

### What was not investigated

Ephemeral (single-job, auto-deregistering) runners were considered but not
adopted: they need an orchestrator (Actions Runner Controller / autoscaler) that
is disproportionate for a single developer workstation, and the trusted-event
gate already removes the untrusted-code vector that ephemerality primarily
defends against. The current integration suite's own green/red state on `main`
was not exhaustively established here; that is a codebase-health question the
newly-executing gate will now surface honestly rather than a blocker for the
runner design.

## Sources

- https://docs.github.com/en/actions/reference/security/secure-use
- https://github.com/orgs/community/discussions/26722
- https://www.wiz.io/blog/github-actions-security-guide
- https://blog.gitguardian.com/github-actions-security-cheat-sheet/
- https://latchkey.dev/learn/ci-how-to/secure-self-hosted-runner-public-repo-github-actions
- Runner package and pinned digest: https://github.com/actions/runner/releases/tag/v2.336.0
- `pyproject.toml` marker registry and `conftest.py` `pytest_runtestloop` HF gate
- `justfile` `_dev-test` recipe; `.github/workflows/ci.yml`; `.github/actionlint.yaml`

---
tags:
  - '#research'
  - '#tool-upgrade-cycle'
date: '2026-09-26'
modified: '2026-09-26'
body_schema: 'body-v2'
body_hash: 'sha256:197cea3f6ca46e04011b94e27208d0724d5177b79f619b3858eee1ff5c2d707b'
related: []
---

# `tool-upgrade-cycle` research: `a durable CUDA tool install and upgrade cycle with uv`

A `uv tool` installation of the GPU host resolves torch from PyPI, which on
Windows is a CPU-only build, and every upgrade re-resolves it. The shipped
remedy pins a direct CUDA wheel URL in the receipt and pins the installed
package version (`2026-07-14-tool-env-gpu-continuity-adr`, O-A1;
`2026-09-04-cuda-provisioning-adr`, D3), which keeps CUDA across a bare
`uv tool upgrade` only by freezing both the release and torch. This research
asks whether uv can carry a CUDA source that resolves dynamically, survives
every upgrade, and tolerates a running service, so that installing and
upgrading become one dependable cycle. It concludes that uv does: an index and
an index strategy passed at install time are persisted in the receipt, resolve
the real package correctly, keep CUDA across release upgrades, and apply in
place while the environment is held. Every observation below was made with
`uv 0.12.12` on Windows 11 against real PyPI and `download.pytorch.org`, in
tool directories redirected under a scratch directory; version-sensitive
claims name the uv release tested.

## Findings

### F1 - the wheel-URL pin freezes the tool and its torch

The repair pins the installed version (`vaultspec-rag[gpu,mcp]==0.4.35`), and
uv records an exact pin in the receipt. A later `uv tool upgrade` then reports
"Nothing to upgrade", naming the pin (reproduced with `cowsay==5.0`, and again
with `vaultspec-rag[gpu,mcp]==0.4.34`). The direct wheel requirement pins torch
to one build in the same way, so a release requiring a newer torch fails to
resolve until the command is rebuilt by hand.

### F2 - uv persists the index and the index strategy in the receipt

`uv tool install ... --index https://download.pytorch.org/whl/cu130 --index-strategy unsafe-first-match` writes both under `[tool.options]` in
`uv-receipt.toml`. The same two lines were written by uv 0.9.0, 0.10.0, 0.11.0
and 0.12.0 (each run through `uvx uv@<version>`), so the premise behind O-A1 -
that the receipt carries no index options - does not hold for any uv release in
use. `--torch-backend cu130` is accepted by `uv tool install` in 0.12.12 but is
not written to the receipt, and `uv tool upgrade` has no such option, so it
cannot carry CUDA across an upgrade.

### F3 - only the first-match strategy resolves the real package

With the CUDA index and uv's default first-index strategy, `uv pip compile` of
`vaultspec-rag[gpu,mcp]` for CPython 3.14 on Windows is unsatisfiable: the
PyTorch index mirrors `urllib3` without a version `qdrant-client` accepts, and
first-index forbids falling through to PyPI. `unsafe-first-match` exhausts the
CUDA index before PyPI for each package, and resolves `torch==2.14.0+cu130`
with `urllib3==2.8.0` from PyPI on Windows x86_64, Linux x86_64 and Linux
aarch64. `unsafe-best-match` was not adopted: it takes the highest version from
any index, so a torch release that reaches PyPI before the CUDA index - or a
CUDA index PyTorch has stopped publishing to - silently selects the CPU build.
Under first-match the same situation also falls through to PyPI, but only when
no CUDA build satisfies the requirement at all; the start preflight's refusal
of a CPU-only build (`src/vaultspec_rag/cli/_service_start.py`) still catches
it.

### F4 - a bare upgrade keeps CUDA and moves the release

An installation made with the two options, whose receipt carries no version
pin, was upgraded with plain `uv tool upgrade vaultspec-rag`: it moved
0.4.34 to 0.4.35 and kept `torch 2.14.0+cu130`, CUDA 13.0. A re-resolving
`uv tool upgrade --reinstall` of a small tool with the same options kept the
CUDA build under uv 0.9.0 as well. Without the options, the same install
resolves `torch 2.14.0`, the CPU build.

### F5 - in-place installs and upgrades tolerate a live holder

With a process running from the environment holding `torch` and
`pydantic_core` loaded, in-place reinstalls of `vaultspec-rag`,
`pydantic-core` and `torch` each succeeded, the holder kept running, and the
environment imported cleanly afterwards with no leftover files. The
destructive case `2026-09-04-cuda-provisioning-research` reproduced is
`uv tool install --force`, which replaces the environment wholesale; nothing in
this cycle needs it.

In place holds only while the requested interpreter matches the environment's
own. Against a field-shaped environment (receipt with no `python` key, CPython
3.14.6, a live holder), `--python 3.14` and an absent `--python` both applied in
place, but `--python 3.13` printed "Ignoring existing environment ... the
requested Python interpreter does not match the environment interpreter" and
rebuilt wholesale: it deleted `Lib` and then failed on the held `Scripts`,
leaving the environment unrunnable. A plain `uv tool install` is therefore a
wholesale replacement whenever its interpreter request differs, `--force` or not.
The holders in this finding ran the environment's interpreter; a holder started
through one of the tool's launchers is F8.
The same failure occurred on 2026-09-26 against the machine's real tool
installation, recorded in `2026-09-26-gpu-single-owner-audit`.

### F6 - one in-place command repairs an existing installation

From the field state - an unpinned receipt with no options and CPU torch -
`uv tool install --python <X> "vaultspec-rag[gpu,mcp]" --index <cu130> --index-strategy unsafe-first-match --upgrade-package torch` replaced only
torch (CPU to `+cu130`), kept the installed release, and left a receipt with no
pin and both options; a later bare `uv tool upgrade` then moved the release and
kept CUDA. Without `--upgrade-package torch` uv rewrites the receipt but keeps
the installed CPU torch, because it still satisfies `torch>=2.4`. With
`--upgrade` instead, the same command repairs and upgrades in one step, also
while held.

### F7 - an MCP adapter launched through uvx no longer shares the host environment

With a host installed with the options, `uvx --from vaultspec-rag[gpu,mcp]`,
`--from vaultspec-rag[mcp]` and `--from vaultspec-rag` all ran from ephemeral
`archive-v0` cache environments, including with a matching interpreter. In the
audited field state the adapter did run from the installed tool, whose receipt
carried no options, so the options are the likely difference; this was
inferred, not isolated. The adapter then no longer holds the host environment,
but its cached environment is resolved independently of the host's release and
can drift from it, which the release-compatibility guard reports as a
mismatch. Not investigated further here.

### F8 - a running launcher turns `uv tool install` into an environment removal

F5 held a process running the environment's own `Scripts\python.exe`. A
process started through one of the tool's entry-point launchers in uv's
executable directory (`bin`) is a different case. Observed with `uv 0.12.12`
on Windows 11, with a two-launcher test package and again with the real
package from a wheel built at `9d067c0f`:

- `uv tool install` that changes any package, in place and with the
  environment's own interpreter, applies the packages, fails to replace the
  running launcher, and then removes the tool environment: `Lib` is deleted
  and the removal stops at the held `Scripts` with "failed to remove directory
  ... Access is denied". The same happened with `--upgrade`. The product's
  consented repair, run as `vaultspec-rag install --upgrade --yes` through its
  own launcher, did exactly this.
- `uv tool install` that changes no package, only the index options, prints
  "is already installed", writes both options into the receipt, and touches
  neither the environment nor the launchers, with a launcher running.
- `uv tool upgrade` across a release applies the packages and then fails with
  "Failed to install entrypoint ... being used by another process (os error
  32)"; the environment stays whole at the new release and the running
  launcher, left in place, runs the new release. A later upgrade with nothing
  running reports nothing to upgrade and does not refresh the launcher.
- `uv tool upgrade` does not persist `--index` or `--index-strategy` into the
  receipt, with or without a running launcher.
- A running `Scripts\<entry point>.exe` of the environment makes an upgrade or
  reinstall of that package fail at uninstall, before anything is installed;
  the old release stays importable, a sibling script executable may be
  removed, and the same upgrade after the process exits completes.
- Renaming a running launcher aside before the install worked for the test
  package and was refused for the real package's launchers with os error 32:
  the MCP launcher at 2, 8, 20 and 40 seconds after it started, and the CLI
  launcher during a short verb. It is not a precondition the product can
  establish.

### F9 - a torch swap through uv's pip interface plus an options-only install repair in place

Against the field shape (CPU torch, no receipt options) with the real
package's MCP launcher running and a second process holding `torch` and
`pydantic_core` loaded: `uv tool install --python 3.14 "vaultspec-rag[gpu,mcp]" --index <cu130> --index-strategy unsafe-first-match` wrote both options and
changed nothing else; `uv pip install --python <environment python> --index <cu130> --index-strategy unsafe-first-match --reinstall-package torch "torch==2.14.0"` replaced torch with `2.14.0+cu130` and left `Lib`, the
launchers and the receipt intact; a bare `uv tool upgrade vaultspec-rag` then
moved 0.5.2 to 0.5.3 with torch still `+cu130`, reporting only the running
launcher. Neither repair step re-installs a launcher, so neither can reach the
removal in F8.

### Not investigated

POSIX in-place replacement semantics, cross-account tool directories, and uv
releases older than 0.9.0. What holds the real MCP launcher open against a
rename (F8) was not isolated.

## Sources

- `uv 0.12.12` CLI help: `uv tool install --help`, `uv tool upgrade --help`.
- `uvx uv@0.9.0`, `uv@0.10.0`, `uv@0.11.0`, `uv@0.12.0` - receipt recording runs.
- https://download.pytorch.org/whl/cu130 - the CUDA 13.0 wheel index.
- https://pypi.org/project/vaultspec-rag/0.4.34/ and /0.4.35/ - the releases upgraded between.
- `src/vaultspec_rag/operator_state/_provisioning.py` - the current receipt-pin builder.
- `2026-07-14-tool-env-gpu-continuity-adr`, `2026-09-04-cuda-provisioning-adr`, `2026-09-04-cuda-provisioning-research`.

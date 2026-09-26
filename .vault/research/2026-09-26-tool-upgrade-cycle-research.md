---
tags:
  - '#research'
  - '#tool-upgrade-cycle'
date: '2026-09-26'
modified: '2026-09-26'
body_schema: 'body-v2'
body_hash: 'sha256:a59fb26d54f69b96e9b78a76eaea8f5c079db555da0dfb60cfa85b84b40731df'
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

`uv tool install ... --index https://download.pytorch.org/whl/cu130
--index-strategy unsafe-first-match` writes both under `[tool.options]` in
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

### F6 - one in-place command repairs an existing installation

From the field state - an unpinned receipt with no options and CPU torch -
`uv tool install --python <X> "vaultspec-rag[gpu,mcp]" --index <cu130>
--index-strategy unsafe-first-match --upgrade-package torch` replaced only
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

### Not investigated

POSIX in-place replacement semantics, cross-account tool directories, and uv
releases older than 0.9.0.

## Sources

- `uv 0.12.12` CLI help: `uv tool install --help`, `uv tool upgrade --help`.
- `uvx uv@0.9.0`, `uv@0.10.0`, `uv@0.11.0`, `uv@0.12.0` - receipt recording runs.
- https://download.pytorch.org/whl/cu130 - the CUDA 13.0 wheel index.
- https://pypi.org/project/vaultspec-rag/0.4.34/ and /0.4.35/ - the releases upgraded between.
- `src/vaultspec_rag/operator_state/_provisioning.py` - the current receipt-pin builder.
- `2026-07-14-tool-env-gpu-continuity-adr`, `2026-09-04-cuda-provisioning-adr`, `2026-09-04-cuda-provisioning-research`.

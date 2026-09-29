# The exit-code contract

A command's exit code is its contract with CI and with the developer. This
document is the canonical statement of that contract, and the numbers it
names live in `dev/exit_codes.py`, which is the machine-readable form of this
page. `dev/guards/test_exit_code_contract.py` enforces both.

## The governing distinction

A tool that RAN and found something is not the same event as a tool that FAILED
TO RUN. The first is a measurement; the second is the absence of one. Any
mechanism that maps both onto the same status is lying, and the shape it
usually takes is `some-scanner ; exit 0`: a literal `exit 0` maps *every*
non-zero status onto success, so a scanner that was never installed, whose
config no longer parses, or that segfaulted halfway through reports exactly
like a clean run — and keeps reporting it, silently, for as long as nobody
looks.

Advisory intent is legitimate. The mechanism must be structural: the target
declares `advisory=True`, and the runner suppresses only the statuses that mean
"findings" (`FINDINGS_CODES`, which is `{1}` for every scanner this
repository runs).
Anything else propagates as `TOOL_BROKEN` (7), which `ADVISORY_BROKEN` is the
advisory-facing name for. One code serves gates and advisories alike: "the
scanner did not run" means the same thing whichever kind of target hit it, and
whether that gates is already carried by the target's declaration.

## Verb classes, keyed to CONSEQUENCE

| Verb class | Gates? | 0 means | Non-zero means |
|---|---|---|---|
| `check-*` | yes | read-only inspection found nothing | a finding, or the checker could not run |
| `fix-*` | on failure only | the repair pass completed | the repair pass failed; `5` under `VAULTSPEC_FIX_STRICT` when it had to change something |
| `test-*` | yes | tests ran and passed | a failure, or `8` when nothing ran |
| `audit-*` | **no**, except dependency audit | the scan completed | `7` when the scanner could not run; for the dependency audit, `1` on a published advisory |
| `build-*` | yes | artefacts produced | the build failed |
| `health-*` | never | always; the output is the product | — |

`check` is read-only and `fix` mutates: that is the whole of the difference
between them, and it is why `fix` may not be used as a gate. A `fix` that
exited non-zero because it changed a file would make every clean local
development loop red.

### The `audit` rule

> **`audit` is advisory, except the DEPENDENCY audit, which gates.**

A published advisory against a version this repository has pinned is a verdict
about a specific artefact, and the remedy is mechanical: change the pin. A
duplication, dead-code, complexity or shadowing scan yields a lead to confirm
by hand, so it stays advisory.

The dependency audit gates with `FAILED` (1) and must fail CLOSED: `uv audit`
is a preview feature that has historically exited 0 while printing advisories,
so the verdict is derived from the printed summary AND the exit code, never
from the exit code alone.

## The numbers

| Code | Name | Meaning |
|---|---|---|
| 0 | `OK` | ran; nothing that gates |
| 1 | `FAILED` | ran; reported a gating result |
| 2 | `INIT_HOST_TOOL_MISSING` | `just init`: a required host tool is absent |
| 3 | `INIT_STALE` | `just init`: environment stale relative to its inputs |
| 4 | `INIT_STEP_FAILED` | `just init`: one bootstrap step failed |
| 5 | `DRIFT` | managed content differs from its generated form (also `fix` under `VAULTSPEC_FIX_STRICT`) |
| 6 | `INIT_LOCKED` | `just init`: the environment is held open by another process |
| 7 | `TOOL_BROKEN` (`ADVISORY_BROKEN`) | the tool failed to RUN: it started and could not do its job |
| 8 | `NOTHING_SELECTED` | nothing ran: empty selection, or every test skipped |
| 127 | `TOOL_MISSING` | required tool absent, no fallback |

2–6 are `just init`'s own codes. Outside `init`, an absent executable found at
dispatch time is `127` — the shell's own command-not-found status, legible
without a lookup table. `init` keeps `2` because its report distinguishes
*which* host tool, and callers of `init` already read that report.

## Aggregators: one rule

`check-all`, `fix-all`, `audit-all`, `test-all` and `build-all` **run every
step and report, and exit with the first non-zero status they saw.** They do
not stop at the first failure.

One `-all` recipe that runs everything, one that is fail-fast `just`
dependencies, one that always exits 0, and one that iterates its lanes
continue-on-failure would make "what does `-all` mean here" unanswerable
without reading the body of each recipe.

Run-all is the rule because an aggregate's purpose is a complete picture per
invocation. Fail-fast costs one CI round-trip per defect and hides the
correlation between them; the developer who ran `check-all` wanted the list.
Individual targets remain fail-fast: within one target the later steps usually
presuppose the earlier ones.

The consequence for construction: an `-all` aggregate is a target inside `dev/`
with `keep_going=True`, composing the others by reference. It is **not** a
`just` dependency chain, because `just` dependencies are unconditionally
fail-fast and cannot express this rule.

### What is an aggregate, and what is a pipeline

The rule above governs AGGREGATES, and the test for one is whether its steps
are independent measurements. `check-all`, `fix-all`, `test-all`, `audit-all`
and `build-all` all pass it: the type checker's verdict does not depend on the
linter's, and a reader who ran one of them wants every answer, not the first.

`ci` and `init` fail that test and are deliberately FAIL-FAST. Their first step
provisions the environment the rest run inside — `uv sync` for `ci`,
`init-python` for `init` — so a later step is not an independent measurement of
anything: it is a step whose result is unreadable once the step before it
failed. Running `init-node` after `init-python` failed does not add a second
data point, it adds a second error message about the same cause. Reporting
"nine steps failed" where one thing broke is the same loss of signal that
fail-fast aggregation causes, arrived at from the other direction.

So: run every step when each step ANSWERS SOMETHING; stop at the first failure
when each step DEPENDS ON the one before it. The test is the dependency, not
the verb.

### `audit-all` gates, and `advisory` is a property of a leaf

**`audit-all` fails only when a dimension that GATES found something, and the
only dimension that gates is the dependency audit.** That is the whole
guarantee.

Setting `advisory=True` on the aggregate itself instead of on its leaves would
make a published CVE against a pinned version pass `audit-all` whenever the
aggregate's own flag said so, regardless of what any individual dimension
found — same recipe, opposite consequence depending on where the flag landed.

The rule that settles it: `advisory` describes ONE TOOL and what its findings
are worth. It belongs on a leaf. Setting it on an aggregate overrides the
declarations of everything the aggregate composes, which is the same defect as
`; exit 0` moved up one level — a blanket claim standing in for a set of
specific ones. An aggregate's consequence is DERIVED from what it contains: the
advisory dimensions inside `audit-all` still exit 0 on their findings, so only
`deps` can fail it, and "one red dimension does not hide the rest" is delivered
by `keep_going`, not by silencing every dimension at once.

### Two advisory mechanisms; a conformance audit must look for both

Findings-suppression is declared in two places, and scanning for one of them
alone under-reports:

1. **`advisory=True` on a target**, with `findings_codes` defaulting to `{1}`.
   The dispatcher applies `advisory_result`.
2. **A per-invocation wrapper**, as in this repository's
   `_advisory(finding_exit, ...)`, which states the finding status at the call
   site and needs no flag on the target at all.

Both implement the same rule; neither is a shortcut past it. The second exists
because the default is not universal: **vulture reports dead code with 3**, and
reserves 1 for invalid input and 2 for invalid arguments. Read under `{1}`, a
vulture finding looks like a broken scanner and a broken vulture invocation
looks like a finding — both backwards, and both silent. So a tool that does not
use 1 must SAY which status it uses, whether by `findings_codes` on the target
or by the wrapper's argument. That requirement is what makes this different
from a blanket flag, and it is why the flag alone is not the thing to grep for.

## Partial and skipped work

A run that proved nothing must not read as a run that proved everything.

- A test lane that collected no tests exits `8` (`NOTHING_SELECTED`). The
  runner maps pytest's own status `5` onto it.
- A lane legitimately permitted to be empty sets
  `VAULTSPEC_ALLOW_EMPTY_SELECTION=1`, which is a declaration in the toolchain
  table, not a flag typed at a prompt.
- A hardware-gated lane whose tests all skip — this repository's GPU tiers on
  a host with no CUDA — is the case this rule exists for. pytest exits 0 for
  an all-skipped run, so `-ra` makes the skips visible in the log, and a lane
  that can skip *wholesale* is declared advisory rather than gating, so it
  cannot contribute a green verdict it did not earn.
- An optional tool that is simply absent is reported and skipped by
  `ToolOrSkip`, which only an advisory target may use. A gate that silently
  passes when its tool is missing is not a gate — it resolves to `127`.

## Where the contract lives

- `dev/exit_codes.py` — the constants and the two mapping functions.
- `dev/runner.py` / `dev/__main__.py` — the single place advisory suppression
  and selection mapping are applied.
- `dev/guards/test_exit_code_contract.py` — the guard. It asserts the mapping
  functions behave as written and that no justfile recipe re-implements a
  swallow (`; exit 0`, a trailing bare `exit 0`, `|| true`,
  `continue-on-error` inside a recipe body).

A guard that only asserts the mapping functions is not enough: without the
recipe-body scan, a justfile recipe could reintroduce a swallow the mapping
functions never see. The guard is the durable part of this contract; the
prose is only its explanation.

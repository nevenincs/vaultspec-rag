---
tags:
  - '#exec'
  - '#index-resume-drift-race'
date: '2026-07-25'
modified: '2026-07-25'
step_id: 'S12'
related:
  - "[[2026-07-25-index-resume-drift-race-plan]]"
---

# Turn the module-length gate from advisory to failing at a threshold the post-seam tree actually meets, and record the full offender census in the same change so the remaining ratchet is visible rather than implied

## Scope

- `tools/module_length.py`

## Description

- Invert the gate: fail by default, and make not failing the opt-in.
- Set the enforced ceiling to a length the tree genuinely holds today.
- Report the census at every rung between the ceiling and the target, and
  record that census in the tool.
- Prove the gate in both directions before trusting it.
- Correct the health report's description of a gate that is no longer
  advisory.

## Outcome

The gate was opt-in and always exited zero, so nothing stopped a module
growing. It now fails by default and the opt-out is explicit.

The enforced ceiling is 3400 lines, which the tree meets with zero modules
above it. The longest module is a test at 3398 lines; the longest module that
is not a test is 2990. The ceiling was chosen as the first rung above what
already exists rather than as a number the tree could be made to pass, because
any lower value fails today and would have had to be bought by excluding
offenders or counting differently.

That ceiling cannot make anything shorter. What it does is stop length growing
past where it already is, which is the property the campaign was missing, and
every extraction lowers the next rung.

A single passing number would hide how far there is to go, so the census is
recorded rather than implied. Over 434 modules:

```
over 3400:    0   the enforced ceiling
over 3000:    1
over 2000:    9
over 1200:   34
over 1000:   49
over  800:   63
over  500:  113   the ratchet target
```

The two extractions this Phase depends on are what made the step orderable at
all: the indexer was the fifth-longest module in the tree before them.

## Notes

The gate was proved in both directions rather than trusted for exiting zero.
At the ceiling the tree meets it exits zero; at one rung below, it exits
non-zero and names the module that put it over. With the opt-out passed at that
same lower ceiling it exits zero again. A gate only ever observed passing would
not have distinguished a working check from one that cannot fail.

The ceiling is honest but weak: at 3400 it constrains one module. Its value is
the ratchet, not the current bite, and the census is what keeps the remaining
distance visible instead of leaving one green tick to imply the work is done.

The health report computes module lengths a second time rather than importing
the tool that owns the count. That duplication was left in place - it is
outside this step's scope - but only its stale claim that the gate is
report-only was corrected. It is a real second implementation of the same
measurement and will drift.

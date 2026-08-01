---
tags:
  - '#audit'
  - '#module-split'
date: '2026-07-27'
modified: '2026-07-27'
body_hash: 'sha256:cad0cc0d037fc632a9f732abf631810ab5652c92deca162e1368ec40848527cb'
related:
  - "[[2026-06-01-module-split-plan]]"
---

# `module-split` audit: `install test split`

## Scope

Reviewed P08.S08's replacement of the indexed `test_install.py` integration
suite with `_install_helpers.py` and the nine directly collected installer
test modules. Compared test-method inventories, searched for replacement
scenarios and facade imports, reviewed fixture/plugin registration and direct
production imports, and collected and executed the split suite.

## Findings

### junction-coverage | high | Five Windows reparse-point scenarios were dropped

The indexed pre-split suite has 102 unique test methods; the nine replacement
modules have 97. No replacement exists for
`test_preview_does_not_follow_an_unrelated_windows_junction`,
`test_required_junction_fails_before_lifecycle_mutation`,
`test_required_junction_container_fails_before_lifecycle_mutation`,
`test_late_junction_blocker_preserves_reparse_topology`, or
`test_junction_snapshot_recreates_removed_reparse_node`. These cases prove
that preview, lifecycle rejection, rollback, and snapshot restore do not
traverse or corrupt Windows junction/reparse targets. The helper still carries
the junction construction and signature routines, but none of the directly
collected modules invokes them, so the security scenarios are not collected.

### plugin-registration | low | Repeated late plugin registration emits a collection warning

Each split module imports fixture and helper names from `_install_helpers.py`
before declaring that same module in `pytest_plugins`. Collection succeeds, but
pytest emits `PytestAssertRewriteWarning` that `_install_helpers` was imported
before it could be assertion-rewritten. The direct imports already make the
fixtures available, so the redundant late plugin registration is noisy and
obscures future collection diagnostics.

### junction-coverage | resolved | All Windows reparse-point scenarios are restored

The five missing tests now reside in the concrete preview, topology, and
rollback modules. The split inventory again matches the indexed source at 102
unique methods, with no duplicate method names. All 13 parametrized
junction/reparse cases were collected and passed on Windows.

### plugin-registration | resolved | Package registration makes fixtures available before imports

`integration.__init__` now registers `_install_helpers` for assertion rewriting
and as the package fixture plugin. The individual test modules no longer carry
plugin declarations. Collection of all nine modules reports 183 tests with no
warnings. The package initializer exports no test or helper symbols, so it is
fixture registration rather than a compatibility facade.

## Recommendations

- Restore the five junction/reparse scenarios in the concrete topology and
  rollback owners, retaining their Windows-only guards and direct production
  imports.
- Remove the redundant per-module `pytest_plugins` declarations after verifying
  the directly imported fixtures remain available, so collection is warning-free.

Verification: `uv run pytest --collect-only -q` over all nine modules collected
170 parametrized tests. The corresponding execution reported 170 passed in
59.37 seconds; the command wrapper timed out immediately after pytest printed
its completed summary. No test facades, re-exports, duplicate test names, or
non-production test targets were found.

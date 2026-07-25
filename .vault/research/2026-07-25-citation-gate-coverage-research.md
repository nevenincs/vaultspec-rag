---
tags:
  - '#research'
  - '#citation-gate-coverage'
date: '2026-07-25'
modified: '2026-07-25'
related: []
---

# `citation-gate-coverage` research: `where the citation gate was actually blind`

The citation gate reported clean while a dated vault stem sat in a module
docstring. The reported hypothesis was that the AST walk never visits a module's
first statement. That hypothesis is wrong, and acting on it would have shipped a
plausible-looking fix over an unchanged hole - so the actual escape had to be
located before anything was changed. Two independent holes were found, neither
of them in the walk.

## Findings

### The prose walk reaches every docstring, including the module docstring

Calling the gate's prose iterator directly against the reported file returns 221
prose entries whose first entry is line 1 - the opening line of the module
docstring. The iterator matches any bare string-constant expression statement
anywhere in the tree, which covers module, class, function and async-function
docstrings alike, and it walks comment tokens separately. Backtick style is
irrelevant: the patterns are substring regexes over the docstring text, so RST
double-backtick and markdown single-backtick literals are indistinguishable to
them. No surface was missing.

### The dated-stem pattern required a document-type suffix

The pattern demanded a trailing `-adr`, `-plan`, `-audit`, `-research`,
`-reference` or `-exec` segment. Fed the exact sentence from the issue, it
returns no match; append `-adr` to the same stem and it matches immediately.
This is the escape. Prose cites a document far more often by its bare dated stem
than by its full filename - that bare form is also the exec-folder name - so the
suffix requirement excluded the commonest shape of the thing being forbidden
while leaving the gate reporting clean.

### The tooling surface was never citation-scanned

The walk covered the package for citations and paths, but reached the tooling
directory only for workstation-path leaks. Running the citation patterns over
that directory by hand returns one live audit-finding pointer in the vault-index
profiler, alongside the gate's own file, which necessarily reports its own
pattern definitions and is the one legitimate exemption. A citation in a tool
was structurally unreachable by the gate that exists to find it.

### The instance the issue named was already gone

The worker docstring no longer carries the stem; two earlier commits removed it.
Only the specific text was addressed at the time, not the gate hole that let it
pass, which is why the gate still reported clean on the same class of violation.

### Not investigated

Whether non-Python tracked surfaces - user-facing documentation, markdown, YAML
workflow files - carry citations. The gate scans Python prose and one config
file for paths, and widening it to prose in markdown is a materially different
problem with a much higher false-positive surface. It is left open.

## Sources

- `tools/citation_gate.py`
- `tools/profile_vault_index.py:114`
- `src/vaultspec_rag/indexer/_chunk_worker.py`

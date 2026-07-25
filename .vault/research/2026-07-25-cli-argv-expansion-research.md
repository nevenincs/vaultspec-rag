---
tags:
  - '#research'
  - '#cli-argv-expansion'
date: '2026-07-25'
modified: '2026-07-25'
related: []
---

# `cli-argv-expansion` research: `argv rewriting under the CLI`

`vaultspec-rag search --include-path "src/**"` cannot receive a glob on
Windows. The pattern arrives at the parser already replaced by the files it
matched, and the surplus files land as stray positionals that
`src/vaultspec_rag/cli/_search.py:1138` reports as unexpected options. Path
narrowing is the documented remedy for noisy code search, so an agent following
the shipped guidance concludes the filter is unsupported and searches
unfiltered instead. The question was where the replacement happens, because the
answer decides whether this is fixable in this repository at all.

## Findings

### The replacement is inside the process, not in any shell or launcher

Measured on Windows 11, Python 3.13, `click@8.4.2`, `typer@0.27.0`. The same
interpreter, same working directory, same quoted argument:

- a plain script printing `sys.argv` receives `src/vaultspec_rag/indexer/**`
  intact - from PowerShell 7 and from Git Bash alike;
- `python -m vaultspec_rag search ... --include-path "src/vaultspec_rag/indexer/**"`
  reports the expanded file list.

Both shells behave identically and neither expands. The console script is a
`uv` trampoline, and bypassing it entirely by invoking the module still
reproduces, so the launcher is not involved either. The original report
attributed this to the packaged wrapper or the C runtime; the measurement rules
both out.

### The replacement is a click feature, applied to every argument

`click/core.py:1473-1480` reads the command line only when the caller passes no
argument list, and in that branch calls `_expand_args` under
`os.name == "nt"`. `click/utils.py:604-653` applies `os.path.expanduser`, then
`os.path.expandvars`, then `glob(arg, recursive=True)`, and extends the output
with every match. It is deliberate: click emulates a POSIX shell for `cmd.exe`,
where nothing else would.

Three outcomes follow, and only one is loud. No glob match leaves the argument
alone. One match silently replaces a pattern with a single concrete file.
Several turn the remainder into positionals. The two substitutions that precede
the glob apply unconditionally, so they reach arguments that are not paths at
all - measured, a query of `cost of %USERPROFILE% expansion` reaches the ranker
as `cost of C:\Users\hello expansion`, and `~approximately equal` becomes
`C:\Users\approximately equal`.

The mixed separator in the reported output - `src/vaultspec_rag/indexer\_ast_chunker.py`,
forward slashes from the pattern and a backslash at the join - is `glob`
returning `os.path.join(dirname, name)`, and was the evidence that pointed at a
Python-level globber rather than a shell.

### Nothing in this project relies on the behaviour

The application expands `~` itself wherever it accepts a path:
`config.py:368` covers the status-directory chain fed by the global options,
reinforced at `logging_config.py:184`, `store.py:284`,
`cli/_service_watcher.py:57` and `cli/_service_storage.py:744`. The exception
is the `Path`-typed options that set `resolve_path=True` -
`cli/_app.py:207-217` and the install and binary options - because click's own
`Path` type only calls `realpath` and never `expanduser`. No document or
example passes `~` as an argument value, and both shells in use here expand it
before the process starts.

### The blast radius is wider than the reported option

`--include-path` and `--exclude-path` (`cli/_search.py:842,852`) are the
archetype, and `index --exclude` (`cli/_index.py:579`) is the same class
without the friendlier error - `handle_index` allows no extra arguments, so it
dies on click's own message. The search query positional and the free-text job
and log filters are exposed to the two substitutions.

### The test suite could not have caught it

Every in-process CLI test invokes through the runner at
`tests/_cli_helpers.py:36`, and `typer/testing.py:302` passes an explicit
argument list, which takes click's other branch. `_expand_args` is unreachable
from roughly two hundred such call sites. A guard must therefore run a real
subprocess, and must run it from a directory where the pattern actually
matches, since the glob resolves against the working directory. One existing
subprocess scenario in `tests/test_cli.py` had already worked around the hazard
by choosing a pattern with no metacharacters.

### The option space

Suppressing the pass at the invocation site is one keyword on the call that
already exists: `main()` takes `windows_expand_args`, `typer/main.py:1133-1137`
forwards keywords unchanged, and it lands on a named parameter rather than
leaking into the context. Measured to fix the reported command.

Detecting the signature after the fact - a run of positionals that are existing
paths sharing the supplied prefix - was raised in the report. It reconstructs
what was destroyed, cannot recover a pattern that matched exactly one file
because nothing distinguishes that from a deliberate path, and does nothing for
the two substitutions. Steering path filters through inline query tokens
instead of options has precedent here for avoiding option-count growth, but the
options are already shipped and documented, so it would deprecate a working
surface to work around a defect rather than remove it.

What remains for the decision: whether suppression should be total or should
preserve home-shorthand expansion for the path-typed options that currently
depend on click for it.

## Sources

- `src/vaultspec_rag/cli/_search.py:842`, `:852`, `:1138`
- `src/vaultspec_rag/cli/_index.py:579`
- `src/vaultspec_rag/cli/_app.py:207-217`
- `src/vaultspec_rag/config.py:368`
- `src/vaultspec_rag/tests/_cli_helpers.py:36`
- `click@8.4.2` `click/core.py:1473-1480`, `click/utils.py:604-653`
- `typer@0.27.0` `typer/main.py:1133-1137`, `typer/testing.py:302`
- Measurements taken on Windows 11, Python 3.13, in PowerShell 7 and Git Bash.

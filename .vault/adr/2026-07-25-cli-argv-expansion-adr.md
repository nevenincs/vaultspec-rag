---
tags:
  - '#adr'
  - '#cli-argv-expansion'
date: '2026-07-25'
modified: '2026-07-25'
body_hash: 'sha256:985de6771d8e3c45a946abca7648cdcb3f1f190ffaafb9af68237190969a9fe3'
related:
  - "[[2026-07-25-cli-argv-expansion-research]]"
---

# `cli-argv-expansion` adr: `the command line reaches the parser verbatim` | (**status:** `accepted`)

## Problem Statement

Click emulates a POSIX shell over the process command line on Windows. Before
the CLI sees anything, every argument is passed through home expansion,
variable expansion and a recursive glob, and a matching argument is replaced by
what it matched. The documented path filters are the casualty:
`--include-path "src/**"` never reaches the search service as a pattern, so the
narrowing the documentation prescribes for noisy code search cannot be
performed. The same pass rewrites arguments that are not paths, including the
query.

The failure is quiet where it matters most. A pattern matching one file becomes
that file, and the search returns plausible, wrongly-narrowed results with no
indication that the filter the caller wrote is not the filter that ran.

## Considerations

- The filters are service-domain behaviour. The service and its non-shell
  callers already receive patterns verbatim; only the command-line adapter
  corrupts them. Any fix must close that gap rather than compensate for it
  downstream, or the two adapters drift apart on the same contract.
- The expansion is a click default, not something this project asked for, and
  it is suppressible at the point of invocation.
- The interactive shells in use expand their own arguments already, so the pass
  is at best a second expansion of something the caller deliberately quoted.
- The behaviour is unreachable from the in-process test runner, which supplies
  its own argument list. Any guard must be a real subprocess, run from a
  directory the pattern actually matches.

## Considered options

- **Suppress the pass at the invocation site.** One keyword on the call that
  already exists. Restores every affected option and argument at once, and
  removes a class of corruption rather than an instance.
- **Reconstruct the pattern after the fact**, by detecting a run of positionals
  that are existing paths sharing a prefix. Rejected: it guesses at what was
  destroyed, is indistinguishable from a caller who deliberately passed paths,
  cannot recover a pattern that matched exactly one file, and leaves the two
  substitutions untouched.
- **Deprecate the options in favour of inline query tokens.** Rejected: the
  options are shipped, documented and correct; this would retire a working
  surface to route around a defect instead of removing it.

## Constraints

- No documented syntax changes. `--include-path "src/**"` is what the
  documentation, the bundled rule and the discovery skill already prescribe;
  this makes that command work rather than replacing it.
- One invocation site owns the decision. A second bare invocation would
  reintroduce the behaviour for whatever path reaches it.
- Home shorthand is not preserved selectively. Expanding it only for path-typed
  options is not expressible at this boundary, and expanding it generally is
  the corruption being removed.

## Implementation

- `cli/_app.py` gains `run_cli`, which invokes the application with the
  expansion pass disabled and carries the reasoning. Every program invocation
  routes through it: the console-script entry point and the package execution
  shim in `__main__.py`, and the module's own execution guard.
- The keyword lands on a named parameter of click's `main`, so it does not leak
  into the context, and it is inert off Windows.
- Guards live in `tests/test_cli_argv_expansion.py` and run the CLI as a
  subprocess from a seeded workspace, because the pass is unreachable from the
  in-process runner and resolves globs against the working directory. Three
  limbs are covered: a repeated pattern option keeping its glob, and a scalar
  option value carrying a variable reference or a home shorthand arriving as
  typed. A companion set proves the delivered pattern does the real filtering,
  and that a substituted file list silently drops what the pattern covered.

## Rationale

The command line is data. The one caller that could have wanted a shell has one
already, and every other caller of this search - the service's own non-shell
consumers included - passes patterns through untouched. Suppression puts the
command-line adapter back on that single contract instead of maintaining a
second, lossy one.

Reconstruction was rejected because it cannot restore information that has been
discarded, and because the quiet single-match case is precisely the one it
cannot detect. A remedy that works only when the failure is already loud leaves
the dangerous case in place.

## Consequences

- The documented path filters work as documented, on every shell, and the query
  reaches the ranker as typed.
- `index --exclude` and the free-text job and log filters stop being rewritten,
  though neither was reported.
- Home shorthand is no longer expanded for the path-typed options that relied
  on click for it. Those options resolve rather than expand, so a bare `~`
  argument now fails visibly as a missing directory instead of resolving. Both
  shells in use expand it before the process starts, and no example passes it,
  so the exposure is a loud failure in a form nothing documents. Should it
  matter, the fix is to expand at those option sites rather than to restore a
  pass that rewrites everything else too.
- Any future invocation of the application added outside `run_cli` silently
  reintroduces the behaviour on that path. The subprocess guards cover the
  entry point that ships.

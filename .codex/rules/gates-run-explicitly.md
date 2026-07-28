---
name: gates-run-explicitly
trigger: always_on
---

# Gates run explicitly

## Rule

- This project has no commit hooks. Never install one, and never add a
  configuration or task that installs one.
- Run the gates yourself before every commit: lint, format, type-check, and the
  tests covering what you touched.
- Never commit code you know to be failing. Never pass a flag that skips a
  check, and never relax a check to make a commit succeed.
- Never run `git stash`, in any form. Set work aside with a commit on your own
  branch.
- Never run a destructive git operation: no `checkout` of paths, no `reset`, no
  `clean`, no `revert`, no `rebase`, no force-push.
- Commit with an explicit pathspec. Never a bare commit.
- Never merge your own branch into the default branch, and never push to it.
  Commit on your branch and stop; landing is the coordinator's call, not yours.
- Never treat a quiet instruction as expiring. "No push, no merge" holds until
  the work is landed by someone else, including after you believe you are done.

## Why

- A hook that rewrites the working tree to the staged state cannot be made safe
  when more than one worker shares that tree. It reverts every unstaged change,
  and a write landing in that window is lost when the snapshot returns.
- A tree-wide hook fails every commit for every worker whenever any file
  anywhere is red, so one unrelated defect halts all work at once.
- The stash stack is shared by every worktree. A stash takes other workers'
  uncommitted changes with it, and a pop restores them somewhere they were never
  meant to land.
- A bare commit records whatever else is staged, so one worker's half-finished
  change lands under another's message.
- Continuous integration is the only backstop once nothing runs locally. That
  raises the bar on verifying by hand; it does not lower it.
- The default branch's CI runs under a concurrency group, so every push cancels
  the run in flight. A run here costs tens of minutes, so a handful of workers
  landing themselves means nothing ever completes: eleven consecutive runs were
  cancelled across two hours during a release cut, and a release once shipped
  with every gate unexecuted for this reason.
- A cancelled run reports as `cancelled`, not `failure`, so this destroys the
  backstop silently. Nobody is paged; the branch merely looks busy.

## How

- Good: run the linter over the package, the type-checker over the files you
  changed, and the tests that exercise the branches you touched, then commit
  those paths by name.
- Good: after a de-shim or a move, run the tests covering the error and fallback
  branches. A function-local import on a cold branch is valid to a linter and a
  type-checker, and fails only when that branch runs.
- Good: before blaming a foreign session for churn on the default branch, read
  the merge commits. `Merge branch 'worktree-agent-<id>'` is a dispatched lane,
  most likely one of your own.
- Good: check CI with the workflow filtered. An unfiltered run list mixes in
  release-automation runs, and reading one of those as CI is how "it is green"
  gets reported when no gate run has completed at all.
- Good: after running the workspace sync, check for a regenerated
  `.pre-commit-config.yaml` and delete it. The sync writes one from its own
  templates, it is not ignored, and it has been dropped from history more than
  once already — so any sweep-style `add` recommits the hooks this rule forbids.
- Bad: reaching for a hook runner, or restoring one that was removed.
- Bad: a test that asserts a hook configuration exists.
- Bad: setting work aside anywhere but a commit on your own branch.
- Bad: merging or pushing because the work looks finished and nobody answered.
  An unanswered lane waits; it does not land itself.

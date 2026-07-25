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

## How

- Good: run the linter over the package, the type-checker over the files you
  changed, and the tests that exercise the branches you touched, then commit
  those paths by name.
- Good: after a de-shim or a move, run the tests covering the error and fallback
  branches. A function-local import on a cold branch is valid to a linter and a
  type-checker, and fails only when that branch runs.
- Bad: reaching for a hook runner, or restoring one that was removed.
- Bad: a test that asserts a hook configuration exists.
- Bad: setting work aside anywhere but a commit on your own branch.

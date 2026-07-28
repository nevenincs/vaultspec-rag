---
name: gates-run-explicitly
trigger: always_on
---

# Gates run explicitly

## Rule

- Run lint, format, type-check, and the tests covering what you touched before
  every commit.
- Capture each gate's exit code on its own. Never read an exit code through a
  pipe.
- Never commit code you know to be failing.
- Never pass a flag that skips a check.
- Never relax a check to make a commit succeed.
- Never install a commit hook. Never add a configuration or task that installs
  one.
- Delete the hook configuration the workspace sync regenerates. Never commit it.
- Never run `git stash`, in any form.
- Never run a destructive git operation: no `checkout` of paths, no `reset`, no
  `clean`, no `revert`, no `rebase`, no force-push.
- Commit with an explicit pathspec. Never a bare commit.
- Commit on your own branch and stop.
- Never merge your own branch into the default branch.
- Never push to the default branch.
- Hold "no push, no merge" until someone else lands the work. Never treat it as
  expiring because you believe you are finished.

## Why

- A hook that rewrites the working tree to the staged state reverts every
  unstaged change, and cannot be made safe when workers share a tree.
- A tree-wide hook fails every worker's commit whenever any file anywhere is
  red, so one unrelated defect halts all work.
- The stash stack is shared by every worktree. A stash takes other workers'
  uncommitted changes with it.
- A bare commit records whatever else is staged, so one worker's half-finished
  change lands under another's message.
- The default branch runs CI under a concurrency group, so every push cancels
  the run in flight. Enough workers landing themselves means no run ever
  finishes, and releases go out over gates that never executed.
- A cancelled run reports as cancelled, not failed, so a destroyed backstop
  raises no alarm.
- Continuous integration is the only backstop once nothing runs locally. That
  raises the bar on verifying by hand; it does not lower it.

## How

- Run the linter over the package, the type-checker over the files you changed,
  and the tests exercising the branches you touched. Commit those paths by name.
- Run the error and fallback branch tests after a de-shim or a move. A
  function-local import on a cold branch passes both linters and fails only when
  that branch runs.
- Read the merge commits before blaming a foreign session for churn on the
  default branch. A merge of a dispatched lane's branch is your own.
- Filter by workflow when reading CI results. An unfiltered list mixes in
  release automation.
- Set work aside with a commit on your own branch. Never anywhere else.
- Wait when nobody answers. Never land because the work looks finished.

"""Reading the workflows and the justfile as ONE model, for the CI guards.

Three guards beside this file ask different questions about the same two
artifacts - are two jobs doing the same work, is every job named the way the
merge box needs, is every job bounded and un-cancellable on main - and each
needs the same three answers first: which events can reach a job, which
platform it lands on, and what its recipes FINALLY run.

Each of those is a place a naive reader gets it wrong, which is why they are
answered once here:

- **The matrix hides the runner.** A job whose ``runs-on`` is
  ``${{ matrix.runner }}`` is invisible to anything grepping for
  ``self-hosted``, and the matrix jobs are exactly the long-running ones - the
  binary builds and the acquisition legs - so a naive check misses precisely
  the jobs whose six-hour default ceiling costs the most.

- **The event decides who is running.** Half this fleet's jobs carry an ``if:``
  on ``github.event_name``, so two jobs naming the same recipe are only
  duplicating work when some ONE event reaches both. Comparing them without
  that partition reports every deliberate pull-request/push split as a repeat.

- **A recipe is not a command.** ``just check-all`` runs thirteen dimensions;
  ``just check-python`` runs two of them. Comparing recipe NAMES sees no
  overlap where the second is wholly inside the first. Only the expanded
  argument vectors compare honestly.

The expression evaluator is deliberately THREE-valued. A condition this reader
cannot decide - a dispatch input, a ``contains()`` over an event payload -
resolves to MAYBE and the job is treated as reachable, so an unreadable guard
over-reports rather than going quiet. A guard that silently stops seeing a job
is worse than one that names a job it need not have.

YAML is parsed as YAML. The indentation-sensitive shapes here - a ``runs-on``
label list, a matrix ``include:`` of mappings, a block-scalar ``run:`` - are
the shapes a line-oriented reader gets wrong first.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

import yaml

from dev import toolchain
from dev.runner import Cmd, Echo, Ref, ToolOrDocker, ToolOrSkip

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator, Sequence

__all__ = [
    "FALSE",
    "MAYBE",
    "TRUE",
    "Job",
    "Tri",
    "evaluate",
    "final_commands",
    "load_jobs",
    "named",
    "recipe_bodies",
    "recipe_groups",
    "repository_root",
    "workflow_events",
]

#: Repository root: this file is ``<root>/dev/guards/<name>.py``.
_ROOT = Path(__file__).resolve().parents[2]

Tri = Literal["true", "false", "maybe"]
TRUE: Tri = "true"
FALSE: Tri = "false"
MAYBE: Tri = "maybe"

#: Returned by the evaluator for anything it cannot resolve to a literal.
_UNKNOWN = object()

#: ``runs-on`` label substrings that name a platform, most specific first.
_PLATFORMS = (("windows", "windows"), ("macos", "macos"), ("linux", "linux"))

#: A justfile recipe header: a name at column zero, optionally parameterised.
_RECIPE_HEADER = re.compile(r"^([a-zA-Z0-9_][a-zA-Z0-9_-]*)")

#: The consequence group a recipe is filed under, from its ``[group(...)]``.
_RECIPE_GROUP = re.compile(r"^\[group\('([a-z]+)'\)\]")

#: A ``runs-on`` that defers to the matrix, which is what hides a runner.
_MATRIX_REFERENCE = re.compile(r"\$\{\{\s*matrix\.([A-Za-z0-9_-]+)\s*\}\}")

#: The justfile's ``dev`` assignment, expanded into recipe bodies.
_DEV_PREFIX = ("uv", "run", "--no-sync", "python", "-m", "dev")


def repository_root() -> Path:
    """Return the repository root this guard suite is reading."""
    return _ROOT


@dataclass(frozen=True)
class Job:
    """One workflow job, with the matrix and the event condition resolved.

    Args:
        workflow: The workflow file name, e.g. ``ci.yml``.
        job_id: The job's key under ``jobs:``.
        name: The job's ``name:``, or the key when it declares none.
        runners: Every ``runs-on`` label set this job can land on, after the
            matrix is resolved. One entry per matrix leg that changes it.
        timeout: ``timeout-minutes``, or ``None`` when the job declares none.
        condition: The job's ``if:`` expression, or ``None``.
        concurrency: The job's ``concurrency:`` mapping, or ``None``.
        steps: The raw step mappings, in order.
        matrix_axes: The matrix variables this job varies over, so a name
            that omits them can be recognised as one label over many rows.
    """

    workflow: str
    job_id: str
    name: str
    runners: tuple[tuple[str, ...], ...]
    timeout: int | None
    condition: str | None
    concurrency: dict[str, Any] | None
    steps: tuple[dict[str, Any], ...]
    matrix_axes: tuple[str, ...] = ()

    @property
    def platforms(self) -> frozenset[str]:
        """Return the platforms this job's resolved runners land on.

        An unrecognised label set reports ``unknown`` rather than being
        dropped, so a runner pool renamed tomorrow surfaces as a job the
        guards cannot place instead of one they stop comparing.
        """
        found: set[str] = set()
        for labels in self.runners:
            lowered = " ".join(labels).lower()
            found.add(
                next(
                    (name for needle, name in _PLATFORMS if needle in lowered),
                    "unknown",
                )
            )
        return frozenset(found or {"unknown"})

    @property
    def self_hosted(self) -> bool:
        """Whether any resolved runner draws from the self-hosted fleet."""
        return any(
            "self-hosted" in {label.lower() for label in labels}
            for labels in self.runners
        )

    def recipes(self) -> tuple[tuple[str, str], ...]:
        """Return ``(step name, recipe)`` for every ``just <recipe>`` step."""
        return tuple((name, recipe) for name, recipe, _ in self._recipe_steps())

    def _recipe_steps(self) -> tuple[tuple[str, str, str | None], ...]:
        """Return ``(step name, recipe, step condition)`` for every recipe step."""
        found: list[tuple[str, str, str | None]] = []
        for step in self.steps:
            run = step.get("run")
            if not isinstance(run, str):
                continue
            own = step.get("if")
            condition = str(own) if isinstance(own, str) else None
            for line in run.splitlines():
                words = line.strip().split()
                if len(words) >= 2 and words[0] == "just":
                    found.append((str(step.get("name") or ""), words[1], condition))
        return tuple(found)

    def recipes_on(self, event: str) -> tuple[str, ...]:
        """Return the recipes *event* actually reaches inside this job.

        A step carries its own ``if``, and two steps of one job whose
        conditions are mutually exclusive never run together. Reading the job
        condition alone would report those two as concurrent work - which is
        how a job that deliberately narrows its scope on pull requests looks
        like a job running both scopes at once.
        """
        if not self.reaches(event):
            return ()
        return tuple(
            recipe
            for _, recipe, condition in self._recipe_steps()
            if condition is None or evaluate(condition, event) in {TRUE, MAYBE}
        )

    def reaches(self, event: str) -> bool:
        """Whether *event* can reach this job.

        An undecidable condition counts as reachable - see this module's
        docstring on why the three-valued evaluator over-reports rather than
        going quiet.
        """
        if self.condition is None:
            return True
        return evaluate(self.condition, event) in {TRUE, MAYBE}


# ---------------------------------------------------------------------------
#  workflows
# ---------------------------------------------------------------------------


def _workflow_files() -> list[Path]:
    """Return every workflow file, sorted, so findings report stably."""
    directory = _ROOT / ".github" / "workflows"
    return sorted([*directory.glob("*.yml"), *directory.glob("*.yaml")])


def _document(path: Path) -> dict[str, Any]:
    """Parse one workflow file into a mapping."""
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    return loaded if isinstance(loaded, dict) else {}


def workflow_events(workflow: str) -> tuple[str, ...]:
    """Return the event names *workflow* triggers on.

    ``on`` is the YAML 1.1 boolean ``True`` once parsed, which is the single
    most common way a workflow reader silently finds nothing.
    """
    for path in _workflow_files():
        if path.name != workflow:
            continue
        document = _document(path)
        triggers = document.get("on", document.get(True))
        if isinstance(triggers, dict | list):
            return tuple(str(key) for key in triggers)
        if isinstance(triggers, str):
            return (triggers,)
    return ()


def _matrix_legs(job: dict[str, Any]) -> tuple[dict[str, Any], ...]:
    """Return one variable mapping per matrix leg, or a single empty leg.

    Handles both matrix shapes, because ``runs-on`` is expressed through each
    in this fleet: an ``include:`` list of complete mappings (the binary
    builds), and plain key/value axes (the interpreter matrix).
    """
    matrix = (job.get("strategy") or {}).get("matrix")
    if not isinstance(matrix, dict):
        return ({},)
    legs: list[dict[str, Any]] = [
        entry for entry in (matrix.get("include") or []) if isinstance(entry, dict)
    ]
    axes = {
        key: value
        for key, value in matrix.items()
        if key not in {"include", "exclude"} and isinstance(value, list)
    }
    if not legs:
        legs = [{}]
    expanded: list[dict[str, Any]] = []
    for leg in legs:
        combinations: list[dict[str, Any]] = [dict(leg)]
        for key, values in axes.items():
            combinations = [
                {**base, key: value} for base in combinations for value in values
            ]
        expanded.extend(combinations)
    return tuple(expanded)


def _resolve_runs_on(raw: Any, leg: dict[str, Any]) -> tuple[str, ...]:
    """Return the label tuple *raw* names once *leg*'s matrix values are in.

    A ``runs-on`` naming ``${{ matrix.runner }}`` is the case this exists for:
    unresolved, it is one opaque string that matches no platform and no
    ``self-hosted`` label, so the longest-running jobs in the fleet read as
    jobs with no runner at all.
    """
    if isinstance(raw, str):
        reference = _MATRIX_REFERENCE.fullmatch(raw.strip())
        if reference is None:
            return (raw,)
        value = leg.get(reference.group(1))
        if isinstance(value, list):
            return tuple(str(item) for item in value)
        return (value,) if isinstance(value, str) else ()
    if isinstance(raw, list):
        return tuple(str(item) for item in raw)
    if isinstance(raw, dict):
        return _resolve_runs_on(raw.get("group") or raw.get("labels"), leg)
    return ()


def load_jobs(workflow: str | None = None) -> tuple[Job, ...]:
    """Return every job in *workflow*, or in every workflow when it is None."""
    jobs: list[Job] = []
    for path in _workflow_files():
        if workflow is not None and path.name != workflow:
            continue
        document = _document(path)
        for job_id, body in (document.get("jobs") or {}).items():
            if not isinstance(body, dict):
                continue
            jobs.append(_job(path.name, str(job_id), body))
    return tuple(jobs)


def _job(workflow: str, job_id: str, body: dict[str, Any]) -> Job:
    """Build one :class:`Job` from its parsed mapping."""
    runners = tuple(
        dict.fromkeys(
            labels
            for leg in _matrix_legs(body)
            if (labels := _resolve_runs_on(body.get("runs-on"), leg))
        )
    )
    timeout = body.get("timeout-minutes")
    concurrency = body.get("concurrency")
    condition = body.get("if")
    return Job(
        workflow=workflow,
        job_id=job_id,
        name=str(body.get("name") or job_id),
        runners=runners,
        timeout=timeout if isinstance(timeout, int) else None,
        condition=str(condition) if isinstance(condition, str) else None,
        concurrency=concurrency if isinstance(concurrency, dict) else None,
        steps=tuple(
            step for step in (body.get("steps") or []) if isinstance(step, dict)
        ),
        matrix_axes=_matrix_axis_names(body),
    )


def _matrix_axis_names(body: dict[str, Any]) -> tuple[str, ...]:
    """Return the matrix variables a job varies over.

    A job with a matrix produces one row per leg while the YAML holds a
    single ``name:``, so a name that omits the variable reads as unique in
    the file and is not in the merge box.
    """
    matrix = (body.get("strategy") or {}).get("matrix")
    if not isinstance(matrix, dict):
        return ()
    names = {
        key
        for key, value in matrix.items()
        if isinstance(value, list) and key not in {"include", "exclude"}
    }
    for entry in matrix.get("include") or []:
        if isinstance(entry, dict):
            names.update(entry)
    return tuple(sorted(names))


# ---------------------------------------------------------------------------
#  expressions
# ---------------------------------------------------------------------------

#: Operators, literals and references, in the order the tokenizer prefers them.
_TOKENS = re.compile(
    r"\s*(\|\||&&|==|!=|!|\(|\)|,|"
    r"'(?:[^']|'')*'|"
    r"[A-Za-z_][A-Za-z0-9_.\-]*|\S)"
)


def _tokenize(expression: str) -> list[str]:
    """Split a GitHub expression into the tokens the parser below reads."""
    tokens: list[str] = []
    position = 0
    while position < len(expression):
        match = _TOKENS.match(expression, position)
        if match is None:
            break
        tokens.append(match.group(1))
        position = match.end()
    return tokens


def _truthy(value: object) -> bool:
    """Return GitHub's truthiness for a resolved value."""
    return value if isinstance(value, bool) else bool(value)


def _and_values(left: object, right: object) -> object:
    """Return ``left && right`` under three-valued logic."""
    known_false = [
        value for value in (left, right) if value is not _UNKNOWN and not _truthy(value)
    ]
    if known_false:
        return False
    if _UNKNOWN in (left, right):
        return _UNKNOWN
    return True


def _or_values(left: object, right: object) -> object:
    """Return ``left || right`` under three-valued logic."""
    known_true = [
        value for value in (left, right) if value is not _UNKNOWN and _truthy(value)
    ]
    if known_true:
        return True
    if _UNKNOWN in (left, right):
        return _UNKNOWN
    return False


class _Parser:
    """A recursive-descent reader for the expression subset this fleet uses.

    Only what the workflows actually contain: string and boolean literals,
    dotted context references, ``==``/``!=``/``&&``/``||``/``!``, parentheses
    and function calls. Anything else evaluates to unknown, which the caller
    reads as MAYBE.
    """

    def __init__(self, tokens: Sequence[str], context: dict[str, str]) -> None:
        """Read *tokens*, resolving context references out of *context*."""
        self._tokens = list(tokens)
        self._index = 0
        self._context = context

    def _peek(self) -> str | None:
        """Return the next token without consuming it."""
        return self._tokens[self._index] if self._index < len(self._tokens) else None

    def _take(self) -> str | None:
        """Consume and return the next token."""
        token = self._peek()
        if token is not None:
            self._index += 1
        return token

    def parse(self) -> object:
        """Parse the whole expression and return its value."""
        return self._or()

    def _or(self) -> object:
        """Parse ``a || b``, left-associative."""
        value = self._and()
        while self._peek() == "||":
            self._take()
            value = _or_values(value, self._and())
        return value

    def _and(self) -> object:
        """Parse ``a && b``, left-associative."""
        value = self._compare()
        while self._peek() == "&&":
            self._take()
            value = _and_values(value, self._compare())
        return value

    def _compare(self) -> object:
        """Parse ``a == b`` and ``a != b``."""
        value = self._unary()
        while self._peek() in {"==", "!="}:
            operator = self._take()
            right = self._unary()
            if _UNKNOWN in (value, right):
                value = _UNKNOWN
            else:
                value = (value == right) if operator == "==" else (value != right)
        return value

    def _unary(self) -> object:
        """Parse ``!a`` and fall through to a primary."""
        if self._peek() != "!":
            return self._primary()
        self._take()
        value = self._unary()
        return _UNKNOWN if value is _UNKNOWN else not _truthy(value)

    def _primary(self) -> object:
        """Parse a literal, a context reference, a call, or a parenthesis."""
        token = self._take()
        if token is None:
            return _UNKNOWN
        if token == "(":
            value = self._or()
            if self._peek() == ")":
                self._take()
            return value
        if token.startswith("'"):
            return token[1:-1].replace("''", "'")
        if self._peek() == "(":
            self._skip_call()
            return _UNKNOWN
        if token in {"true", "false"}:
            return token == "true"
        return self._context.get(token, _UNKNOWN)

    def _skip_call(self) -> None:
        """Consume a function call's argument list, tracking nesting."""
        depth = 0
        while (token := self._take()) is not None:
            if token == "(":
                depth += 1
            elif token == ")":
                depth -= 1
                if depth == 0:
                    return


def evaluate(expression: str, event: str) -> Tri:
    """Return whether *expression* holds for *event*.

    Only ``github.event_name`` is bound. Everything else - a dispatch input, a
    ref, a payload predicate - is deliberately left unknown, so a condition
    resting on one resolves to MAYBE and its job stays visible to the guards.
    """
    inner = expression.strip()
    wrapped = re.fullmatch(r"\$\{\{(.*)\}\}", inner, flags=re.DOTALL)
    if wrapped is not None:
        inner = wrapped.group(1)
    value = _Parser(_tokenize(inner), {"github.event_name": event}).parse()
    if value is _UNKNOWN:
        return MAYBE
    return TRUE if _truthy(value) else FALSE


# ---------------------------------------------------------------------------
#  recipes
# ---------------------------------------------------------------------------


def recipe_bodies() -> dict[str, tuple[str, ...]]:
    """Return every justfile recipe name mapped to its body lines.

    What separates a recipe from an assignment is ``:=`` and nothing else: a
    parameter list may hold ``=``, quotes and spaces, and a dependency list
    puts a name after the colon, so neither half can be excluded by shape.
    """
    return _parse_justfile()[0]


def recipe_groups() -> dict[str, str]:
    """Return every recipe name mapped to its ``[group(...)]`` consequence.

    The group is what says whether a repeat MATTERS: two jobs both running
    ``init`` are both provisioning a worktree, which every job must do, while
    two jobs both running a gate are measuring the same files twice.
    """
    return _parse_justfile()[1]


def _parse_justfile() -> tuple[dict[str, tuple[str, ...]], dict[str, str]]:
    """Return the justfile's recipe bodies and their consequence groups."""
    text = (_ROOT / "justfile").read_text(encoding="utf-8")
    bodies: dict[str, tuple[str, ...]] = {}
    groups: dict[str, str] = {}
    current: str | None = None
    collected: list[str] = []
    pending_group: str | None = None
    for line in text.splitlines():
        if line[:1].isspace():
            stripped = line.strip()
            if current is not None and stripped and not stripped.startswith("#"):
                collected.append(stripped)
            continue
        if current is not None:
            bodies[current] = tuple(collected)
            current, collected = None, []
        attribute = _RECIPE_GROUP.match(line)
        if attribute is not None:
            pending_group = attribute.group(1)
            continue
        head = line.split("#", 1)[0].rstrip()
        match = _RECIPE_HEADER.match(line)
        if match is None or ":=" in head or ":" not in head:
            continue
        if line.startswith(("set ", "mod ", "import ", "export ", "alias ")):
            continue
        current, collected = match.group(1), []
        if pending_group is not None:
            groups[current] = pending_group
            pending_group = None
    if current is not None:
        bodies[current] = tuple(collected)
    return bodies, groups


def _reentry(argv: Sequence[str]) -> tuple[str, str] | None:
    """Return the ``(verb, target)`` an argument vector re-enters, if any."""
    words = list(argv)
    if "-m" not in words:
        return None
    rest = words[words.index("-m") + 1 :]
    if len(rest) < 3 or rest[0] != "dev":
        return None
    return rest[1], rest[2]


def _command_argv(step: Cmd, seen: set[tuple[str, str]]) -> Iterator[tuple[str, ...]]:
    """Yield *step*'s vector, or the vectors it reaches by re-entering a verb.

    ``ci all`` composes across verbs by re-running this harness rather than
    reaching into another verb's internals, so a reader that stopped at the
    literal vector would report ``ci`` as one command and see none of the
    dimensions it runs.
    """
    argv = tuple(step.argv)
    reentry = _reentry(argv)
    verb = toolchain.find_verb(reentry[0]) if reentry is not None else None
    target = verb.find(reentry[1]) if verb is not None and reentry is not None else None
    if target is None or verb is None:
        yield argv
        return
    yield from _target_commands(verb, target, seen)


def _target_commands(
    verb: toolchain.Verb, target: toolchain.Target, seen: set[tuple[str, str]]
) -> Iterator[tuple[str, ...]]:
    """Yield every argument vector *target* finally runs, following references."""
    key = (verb.name, target.name)
    if key in seen:
        return
    seen.add(key)
    for step in target.steps:
        if isinstance(step, Echo):
            continue
        if isinstance(step, Ref):
            referenced = verb.find(step.target)
            if referenced is not None:
                yield from _target_commands(verb, referenced, seen)
        elif isinstance(step, ToolOrDocker | ToolOrSkip):
            yield (step.tool, *step.argv)
        else:
            yield from _command_argv(step, seen)


def final_commands(recipe: str) -> tuple[tuple[str, ...], ...]:
    """Return every argument vector *recipe* finally runs.

    A recipe body that dispatches into this harness is expanded through
    :mod:`dev.toolchain` - the registry the justfile delegates to - so
    ``check-all`` compares as its dimensions rather than as one opaque line.
    Anything else contributes its own literal vector.
    """
    body = recipe_bodies().get(recipe)
    if body is None:
        return ()
    commands: list[tuple[str, ...]] = []
    for line in body:
        flat = tuple(
            word
            for token in line.split()
            for word in (_DEV_PREFIX if token == "{{dev}}" else (token,))
        )
        commands.extend(_command_argv(Cmd(flat), set()))
    return tuple(commands)


def named(commands: Iterable[tuple[str, ...]]) -> tuple[str, ...]:
    """Render argument vectors as single-line strings, for finding text."""
    return tuple(" ".join(command) for command in commands)

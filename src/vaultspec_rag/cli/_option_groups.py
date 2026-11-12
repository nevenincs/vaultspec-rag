"""Declare a command's options as one dataclass instead of callback arguments.

A command with many options would otherwise spell each one as a callback
parameter and exceed the project's argument-count cap. Here the options live
as fields of a frozen dataclass, each annotated with its public
``typer.Option`` declaration, and the callback takes the assembled instance
as its ``options`` parameter. Typer still builds, parses, and documents every
option through its own public path: the decorator only presents the fields to
it as keyword parameters of the registered callback.
"""

from __future__ import annotations

import dataclasses
import functools
import inspect
from typing import TYPE_CHECKING, Any, get_type_hints

if TYPE_CHECKING:
    from collections.abc import Callable

_OPTIONS_PARAMETER = "options"


def with_option_group[R](run: Callable[..., R]) -> Callable[..., R]:
    """Expose the fields of ``run``'s ``options`` dataclass as Typer options.

    Every other parameter of ``run`` (such as a ``typer.Context``) is kept as
    declared. The returned callback receives the parsed values by keyword,
    builds the dataclass, and calls ``run`` with it.

    Args:
        run: The command body. Its ``options`` parameter must be annotated
            with a dataclass whose fields carry ``Annotated`` Typer option
            declarations and defaults.

    Returns:
        The callback to register with Typer.

    Raises:
        TypeError: When ``run`` has no ``options`` parameter annotated with a
            dataclass.
    """
    hints = get_type_hints(run, include_extras=True)
    options_type = hints.get(_OPTIONS_PARAMETER)
    if not (isinstance(options_type, type) and dataclasses.is_dataclass(options_type)):
        msg = f"{run!r} needs an '{_OPTIONS_PARAMETER}' dataclass parameter"
        raise TypeError(msg)

    field_hints = get_type_hints(options_type, include_extras=True)
    fields = dataclasses.fields(options_type)
    # The fields take the place of ``options`` so the declared order is the
    # order ``--help`` lists them in.
    parameters: list[inspect.Parameter] = []
    for name, parameter in inspect.signature(run).parameters.items():
        if name != _OPTIONS_PARAMETER:
            parameters.append(
                parameter.replace(
                    kind=inspect.Parameter.KEYWORD_ONLY, annotation=hints[name]
                )
            )
            continue
        parameters.extend(
            inspect.Parameter(
                field.name,
                inspect.Parameter.KEYWORD_ONLY,
                default=field.default,
                annotation=field_hints[field.name],
            )
            for field in fields
        )

    @functools.wraps(
        run, assigned=("__module__", "__name__", "__qualname__", "__doc__"), updated=()
    )
    def callback(**values: Any) -> R:
        options = options_type(
            **{field.name: values.pop(field.name) for field in fields}
        )
        return run(**values, options=options)

    # Typer reads the parameters through ``inspect.signature`` and resolves
    # their annotations with ``get_type_hints``; both must describe the
    # expanded keywords, already resolved, rather than ``**values``.
    callback.__dict__["__signature__"] = inspect.Signature(parameters)
    callback.__annotations__ = {
        parameter.name: parameter.annotation for parameter in parameters
    }
    return callback

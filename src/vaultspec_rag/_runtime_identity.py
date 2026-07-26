"""The one description of the interpreter and process this code runs in.

Four places derived the same facts independently - the job runtime context, the
job-manager snapshot, the discovery pointer, and the health payload - and all
four read ``VIRTUAL_ENV`` as a bare string rather than through
:class:`~vaultspec_rag.config.EnvVar`. Four copies means a field added to one
is missing from three, and a fix to how the venv is detected lands in whichever
copy the author happened to open.

The split between the two functions here is the one the consumers actually
need, not a convenience: the discovery pointer and the health payload describe
WHICH INTERPRETER is serving, and must not grow a ``user`` field, because both
are read by other processes as a stable contract. The job snapshots describe
WHICH PROCESS ran a job, where the operating-system user is part of the answer.
"""

from __future__ import annotations

import getpass
import os
import sys
from typing import TypedDict

from .config import EnvVar

__all__ = [
    "InterpreterFields",
    "ProcessIdentityFields",
    "interpreter_fields",
    "process_identity_fields",
]


class InterpreterFields(TypedDict):
    """Which Python interpreter is running."""

    executable: str
    prefix: str
    base_prefix: str
    virtual_env: str | None


class ProcessIdentityFields(InterpreterFields):
    """Which process is running, interpreter included."""

    pid: int
    parent_pid: int
    user: str


def interpreter_fields() -> InterpreterFields:
    """Return which Python interpreter this process is running.

    ``virtual_env`` is ``None`` outside a virtualenv, which is a real answer
    and not a failure: a system-interpreter daemon is a supported deployment,
    and consumers distinguish it from a venv one by exactly this field.
    """
    return {
        "executable": sys.executable,
        "prefix": sys.prefix,
        "base_prefix": sys.base_prefix,
        "virtual_env": os.environ.get(EnvVar.VIRTUAL_ENV.value),
    }


def process_identity_fields() -> ProcessIdentityFields:
    """Return which process this is, interpreter included.

    Adds the OS-level identity - pid, parent pid, and user - to
    :func:`interpreter_fields`. Used where the answer to "who ran this" matters
    (job records), not where "what is serving" does (discovery, health).
    """
    return {
        "pid": os.getpid(),
        "parent_pid": os.getppid(),
        "user": getpass.getuser(),
        **interpreter_fields(),
    }

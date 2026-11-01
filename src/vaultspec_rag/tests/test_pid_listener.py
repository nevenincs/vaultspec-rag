"""Listener ownership must follow the socket, not the OS's per-row state label.

Some Windows builds report every user-mode listening socket with a TCP state
outside the ``MIB_TCP_STATE`` range. psutil maps that to ``NONE``, so a check
that keeps only ``LISTEN`` rows finds no listener on a socket that is accepting
connections, and the managed Qdrant's ownership witness fails on a healthy
child. These bind real sockets in real processes: a substituted connection
table returns whichever state it was told to and proves nothing about the
table the OS actually serves.

MUTATION PROOF, run in one uninterrupted sequence: making the Windows branch
of ``_pid_tcp_listeners`` in ``_process_probe.py`` keep only rows whose psutil
status is ``LISTEN`` fails all four tests here, each on its positive
``assert pid_listens_on_loopback_port(...)``, on a host whose table reports
listeners outside the state range; restoring the listener-table read turns all
four green again.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
from contextlib import contextmanager
from typing import TYPE_CHECKING

import pytest

from .._process_probe import pid_listens_on_loopback_port

if TYPE_CHECKING:
    from collections.abc import Generator

pytestmark = [pytest.mark.unit]


@contextmanager
def _loopback_listener() -> Generator[int]:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        yield int(listener.getsockname()[1])


def test_a_listening_socket_is_owned_by_its_process() -> None:
    with _loopback_listener() as port:
        assert pid_listens_on_loopback_port(os.getpid(), port, timeout=5.0)


def test_another_port_is_not_owned() -> None:
    with _loopback_listener() as port, _loopback_listener() as other:
        assert pid_listens_on_loopback_port(os.getpid(), port, timeout=5.0)
        with socket.socket() as bound_only:
            bound_only.bind(("127.0.0.1", 0))
            unlistened = int(bound_only.getsockname()[1])
            assert unlistened not in {port, other}
            # Bound but never listening holds the port without accepting on it.
            assert not pid_listens_on_loopback_port(
                os.getpid(), unlistened, timeout=5.0
            )


def test_a_listener_in_another_process_is_not_ours() -> None:
    script = (
        "import os, socket, sys\n"
        "s = socket.socket(); s.bind(('127.0.0.1', 0)); s.listen()\n"
        "print(os.getpid(), s.getsockname()[1], flush=True)\n"
        "sys.stdin.read()\n"
    )
    child = subprocess.Popen(
        [sys.executable, "-I", "-c", script],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        assert child.stdout is not None
        # A venv interpreter on Windows is a launcher that runs the real one as
        # its child, so the socket's owner is the pid the script reports.
        owner, port = (int(field) for field in child.stdout.readline().split())
        assert pid_listens_on_loopback_port(owner, port, timeout=5.0)
        assert not pid_listens_on_loopback_port(os.getpid(), port, timeout=5.0)
    finally:
        assert child.stdin is not None
        child.stdin.close()
        child.wait(timeout=10)


def test_a_listener_on_ipv6_loopback_is_owned() -> None:
    if not socket.has_ipv6:
        pytest.skip("host has no IPv6 stack")
    with socket.socket(socket.AF_INET6, socket.SOCK_STREAM) as listener:
        try:
            listener.bind(("::1", 0))
        except OSError:
            pytest.skip("host has no IPv6 loopback")
        listener.listen()
        port = int(listener.getsockname()[1])
        assert pid_listens_on_loopback_port(os.getpid(), port, timeout=5.0)

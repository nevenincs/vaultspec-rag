"""Exec a verified monitor with kernel denial of outbound socket creation/use."""

from __future__ import annotations

import ctypes
import errno
import os
import platform
import sys
from pathlib import Path


class SockFilter(ctypes.Structure):
    _fields_ = [
        ("code", ctypes.c_ushort),
        ("jt", ctypes.c_ubyte),
        ("jf", ctypes.c_ubyte),
        ("k", ctypes.c_uint32),
    ]


class SockFprog(ctypes.Structure):
    _fields_ = [("len", ctypes.c_ushort), ("filter", ctypes.POINTER(SockFilter))]


def deny_outbound() -> None:
    architecture = {
        "x86_64": (0xC000003E, 41, 42),
        "aarch64": (0xC00000B7, 198, 203),
    }.get(platform.machine())
    if architecture is None:
        raise RuntimeError("No reviewed seccomp syscall map for this native host")
    audit_arch, socket_nr, connect_nr = architecture
    denied = 0x00050000 | errno.EPERM
    allowed = 0x7FFF0000
    instructions = [
        (0x20, 0, 0, 4),  # seccomp_data.arch
        (0x15, 1, 0, audit_arch),
        (0x06, 0, 0, 0x80000000),  # kill unexpected ABI
        (0x20, 0, 0, 0),  # seccomp_data.nr
        (0x15, 0, 1, connect_nr),
        (0x06, 0, 0, denied),
        (0x15, 0, 1, 425),  # deny io_uring_setup bypass
        (0x06, 0, 0, denied),
        (0x15, 1, 0, socket_nr),
        (0x06, 0, 0, allowed),
        (0x20, 0, 0, 16),  # socket domain
        (0x15, 0, 1, 1),  # AF_UNIX stays local
        (0x06, 0, 0, allowed),
        (0x15, 2, 0, 2),  # AF_INET
        (0x15, 1, 0, 10),  # AF_INET6
        (0x06, 0, 0, denied),  # deny other socket families
        (0x20, 0, 0, 24),  # socket type
        (0x54, 0, 0, 15),  # remove CLOEXEC/NONBLOCK flags
        (0x15, 1, 0, 1),  # SOCK_STREAM listener only
        (0x06, 0, 0, denied),  # deny datagram/raw egress
        (0x06, 0, 0, allowed),
    ]
    filters = (SockFilter * len(instructions))(
        *(SockFilter(*instruction) for instruction in instructions)
    )
    program = SockFprog(len(instructions), filters)
    libc = ctypes.CDLL(None, use_errno=True)
    libc.prctl.argtypes = [ctypes.c_int, *([ctypes.c_ulong] * 4)]
    libc.prctl.restype = ctypes.c_int
    address = ctypes.cast(ctypes.pointer(program), ctypes.c_void_p).value
    if libc.prctl(38, 1, 0, 0, 0) or libc.prctl(22, 2, address, 0, 0):
        raise OSError(ctypes.get_errno(), "Could not install outbound seccomp denial")


def main() -> None:
    # Absolute script launch under the smoke probe's empty PATH and unrelated cwd.
    sys.path[:0] = [
        str(Path(__file__).resolve().parents[2]),
        str(Path(__file__).resolve().parents[2] / "src"),
    ]
    from vaultspec_rag.qdrant_runtime._provision import verify_native_binary

    digest, binary, *arguments = sys.argv[1:]
    verify_native_binary(Path(binary), digest)
    deny_outbound()
    os.execv(binary, [binary, *arguments])


if __name__ == "__main__":
    main()

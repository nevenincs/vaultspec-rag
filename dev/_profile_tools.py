"""Bounded native sampling and exclusive profiling artifacts."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from contextlib import contextmanager
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

PY_SPY_VERSION = "0.4.2"
PY_SPY_SHA256 = "6e83ab095f40453742d01a2719a178f308534015da519ec0659d2584139dc995"
PY_SPY_WHEEL_SHA256 = "8b06a353c177677e4e1701b288d8c58e2f8d4208ee81a8048d9f72ba800918f8"
PY_SPY_WHEEL_URL = (
    "https://files.pythonhosted.org/packages/6f/ed/"
    "1409cdb557e558a6c98003ab12fdd4284699e158c167c187cb0f124eea4c/"
    "py_spy-0.4.2-py2.py3-none-win_amd64.whl"
)


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def verify_py_spy(path: Path) -> Path:
    resolved = path.resolve(strict=True)
    if not resolved.is_file() or digest(resolved) != PY_SPY_SHA256:
        raise ValueError("py-spy binary does not match the reviewed SHA256 pin")
    if os.name != "nt":
        raise ValueError("The reviewed py-spy binary is for Windows x64")
    return resolved


def write_json(path: Path, value: object) -> None:
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False)
        stream.write("\n")


def sampling_command(
    binary: Path, output: Path, duration: int, *, gil: bool = False
) -> list[str]:
    if not 1 <= duration <= 60:
        raise ValueError("Sampling duration must be between 1 and 60 seconds")
    if output.exists():
        raise FileExistsError(output)
    command = [
        str(binary),
        "record",
        "--pid",
        str(os.getpid()),
        "--duration",
        str(duration),
        "--rate",
        "100",
        "--format",
        "speedscope",
        "--threads",
        "--native",
        "--output",
        str(output),
    ]
    if gil:
        command.append("--gil")
    return command


@contextmanager
def sample_stacks(
    binary: Path | None, output: Path, duration: int, *, gil: bool = False
) -> Iterator[None]:
    if binary is None:
        yield
        return
    command = sampling_command(binary, output, duration, gil=gil)
    # Rehash at the execution boundary, even when preflight already verified it.
    command[0] = str(verify_py_spy(binary))
    with output.with_suffix(".log").open("x", encoding="utf-8") as log:
        process = subprocess.Popen(command, stdout=log, stderr=log)
        try:
            yield
            code = process.wait(timeout=duration + 15)
            if code != 0:
                raise RuntimeError(f"py-spy exited {code}; inspect {log.name}")
            if not output.is_file() or output.stat().st_size == 0:
                raise RuntimeError("py-spy did not produce a sampling artifact")
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)


def trace_kernel_count(path: Path) -> int:
    trace = json.loads(path.read_text(encoding="utf-8"))
    return sum(
        1
        for event in trace.get("traceEvents", [])
        if event.get("cat") == "kernel" and event.get("ph") == "X"
    )

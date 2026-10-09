"""Opening the on-disk store strands no SQLite connection, on any platform.

A fresh interpreter each time: the client keeps its answer for the life of the
process, so only a process that has not opened a store yet can show whether
the client had to ask.
"""

from __future__ import annotations

import ast
import os
import subprocess
import sys
from pathlib import Path

import pytest

from .. import _qdrant_local_client
from ._child_signal import CHILD_PROCESS_TIMEOUT_SECONDS

pytestmark = [pytest.mark.unit]

_PACKAGE_ROOT = Path(_qdrant_local_client.__file__).parent

#: Open a store, use it, close it, collect, then report the sharing mode the
#: client was given and the one SQLite was compiled with.
_SCRIPT = """
import gc
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path
from qdrant_client import models
from qdrant_client.local.persistence import CollectionPersistence
from vaultspec_rag._qdrant_local_client import open_local_client

assert CollectionPersistence.CHECK_SAME_THREAD is None
with tempfile.TemporaryDirectory(prefix="qdrant-local-client-") as directory:
    client = open_local_client(Path(directory) / "qdrant")
    try:
        client.create_collection(
            collection_name="held",
            vectors_config=models.VectorParams(size=4, distance=models.Distance.COSINE),
        )
        client.upsert(
            collection_name="held",
            points=[models.PointStruct(id=1, vector=[1.0, 0.0, 0.0, 0.0])],
            wait=True,
        )
        assert client.count(collection_name="held", exact=True).count == 1
    finally:
        client.close()
    gc.collect()
with closing(sqlite3.connect(":memory:")) as connection:
    compiled = connection.execute(
        "select * from pragma_compile_options "
        "where compile_options like 'THREADSAFE=%'"
    ).fetchone()[0]
print(f"given={CollectionPersistence.CHECK_SAME_THREAD}")
print(f"compiled={compiled != 'THREADSAFE=1'}")
"""


def _fresh_process() -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-W", "error", "-c", _SCRIPT],
        env={**os.environ, "PYTHONWARNINGS": "error"},
        capture_output=True,
        text=True,
        timeout=CHILD_PROCESS_TIMEOUT_SECONDS,
        check=False,
    )


def test_opening_the_store_leaves_no_connection_for_the_collector() -> None:
    """A process's first store open closes every SQLite connection it made.

    Mutation proof: opening the store without stating the sharing mode first
    made this fail on the empty-stderr assertion, with the interpreter's
    ``unclosed database`` report for the client's own probe; stating it made
    this pass.
    """
    child = _fresh_process()
    assert child.returncode == 0, child.stderr
    assert child.stderr == "", child.stderr


def test_the_sharing_mode_given_is_the_one_sqlite_was_compiled_with() -> None:
    """What the client is told matches what it would have found by asking.

    Mutation proof: stating the opposite mode made this fail on the equality,
    ``given`` and ``compiled`` disagreeing; restoring it made this pass.
    """
    child = _fresh_process()
    assert child.returncode == 0, child.stderr
    reported = dict(line.split("=", 1) for line in child.stdout.split())
    assert set(reported) == {"given", "compiled"}
    assert reported["given"] == reported["compiled"]


def _direct_store_opens(tree: ast.AST) -> list[int]:
    """Return the line of every client constructed straight onto a path."""
    return [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and (
            (isinstance(node.func, ast.Name) and node.func.id.endswith("QdrantClient"))
            or (
                isinstance(node.func, ast.Attribute)
                and node.func.attr.endswith("QdrantClient")
            )
        )
        and any(keyword.arg == "path" for keyword in node.keywords)
    ]


def test_only_the_one_constructor_opens_a_store_on_disk() -> None:
    """Nothing else in the package builds a client onto a path.

    A client built directly asks SQLite its question again, in whichever
    process does it first.

    Mutation proof: building the receipt-recovery fixture's client directly
    made this fail naming that file and line; opening it through the
    constructor made this pass.
    """
    sources = sorted(_PACKAGE_ROOT.rglob("*.py"))
    assert sources, f"no source under {_PACKAGE_ROOT}; this guard checks nothing"
    owner = Path(_qdrant_local_client.__file__)
    findings = [
        f"{path.relative_to(_PACKAGE_ROOT).as_posix()}:{line}"
        for path in sources
        if path != owner
        for line in _direct_store_opens(ast.parse(path.read_text(encoding="utf-8")))
    ]
    assert not findings, (
        "open the on-disk store with open_local_client, not directly: "
        + ", ".join(findings)
    )

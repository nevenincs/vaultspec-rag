"""Tests that repository code runs only from bytes that matched their digest.

One default model builds itself from a source file its repository ships.
Verifying that file in the snapshot is not enough on its own: the model
library does not import from the snapshot. It copies the file into a modules
cache of its own and, when a copy is already there, imports that copy without
comparing it to anything. So a stale or planted file in that cache is what
would run.

The guarantee tested here is that the bytes hashed are the bytes executed,
with nothing read in between: not a changed file on disk, not a bytecode
cache beside it, and not the library's copy.

Each source used here writes a marker file when it runs, so "was not
executed" is observed, not inferred.
"""

from __future__ import annotations

import ast
import hashlib
import importlib.util
import os
import py_compile
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from .. import _sparse_encoder
from .._sparse_profile import SPARSE_MODEL_ID, SPARSE_MODEL_REVISION
from .._verified_import import UnverifiedSourceError, import_verified_source
from ..config._types import EnvVar

if TYPE_CHECKING:
    from collections.abc import Iterator

pytestmark = [pytest.mark.unit]

_PACKAGE = Path(_sparse_encoder.__file__).parent


def _source(marker: Path, word: str) -> bytes:
    """Return module source that records that it ran, and defines one class."""
    return (
        "from pathlib import Path\n"
        f"Path({str(marker)!r}).write_text({word!r}, encoding='utf-8')\n"
        "class Model:\n"
        f"    origin = {word!r}\n"
    ).encode()


def _digest(source: bytes) -> str:
    return hashlib.sha256(source).hexdigest()


def test_matching_source_is_executed_once_and_returned(tmp_path: Path) -> None:
    marker = tmp_path / "ran"
    source = _source(marker, "reviewed")

    module = import_verified_source(
        source, expected_sha256=_digest(source), filename=str(tmp_path / "model.py")
    )

    assert marker.read_text(encoding="utf-8") == "reviewed"
    assert vars(module)["Model"].origin == "reviewed"
    assert _digest(source) in module.__name__
    marker.unlink()
    again = import_verified_source(
        source, expected_sha256=_digest(source), filename=str(tmp_path / "model.py")
    )
    assert again is module
    assert not marker.exists()


def test_source_that_does_not_match_is_never_executed(tmp_path: Path) -> None:
    """A changed file is refused before a line of it runs.

    Mutation: with the digest comparison removed the changed source ran,
    wrote its marker, and this failed DID NOT RAISE; restored, it passed.
    """
    marker = tmp_path / "ran"
    reviewed = _source(marker, "reviewed")
    changed = _source(marker, "changed")

    with pytest.raises(UnverifiedSourceError) as excinfo:
        import_verified_source(
            changed,
            expected_sha256=_digest(reviewed),
            filename=str(tmp_path / "model.py"),
        )

    assert not marker.exists()
    assert "model.py" in str(excinfo.value)
    assert _digest(reviewed) in str(excinfo.value)


def test_a_bytecode_cache_beside_the_source_is_not_what_runs(tmp_path: Path) -> None:
    """A compiled file next to the source is a third thing that could run.

    The file on disk and its bytecode cache are both made to hold other
    code. Importing the reviewed buffer runs the reviewed buffer.

    Mutation: with the loader made to stat its source and read the path it is
    asked for, the import machinery read the cache and this failed on the
    marker assertion with ``planted``; restored, it passed.
    """
    marker = tmp_path / "ran"
    path = tmp_path / "model.py"
    reviewed = _source(marker, "reviewed")
    path.write_bytes(_source(marker, "planted"))
    py_compile.compile(
        str(path), cfile=importlib.util.cache_from_source(str(path)), doraise=True
    )
    # The cache is valid for the planted file as it stands on disk, which is
    # exactly the state in which the import machinery would prefer it.
    assert Path(importlib.util.cache_from_source(str(path))).is_file()

    module = import_verified_source(
        reviewed, expected_sha256=_digest(reviewed), filename=str(path)
    )

    assert marker.read_text(encoding="utf-8") == "reviewed"
    assert vars(module)["Model"].origin == "reviewed"


_LIBRARY_COPY_PROBE = """
import hashlib
import sys
from pathlib import Path

from vaultspec_rag._sparse_encoder import class_from_verified_source

snapshot = Path(sys.argv[1])


class Held:
    directory = snapshot

    def read(self, name):
        return (snapshot / name).read_bytes()


source = (snapshot / "modeling_splade.py").read_bytes()
model = class_from_verified_source(
    Held(),
    source="modeling_splade.py",
    expected_sha256=hashlib.sha256(source).hexdigest(),
    name="Model",
)
entered = sorted(name for name in sys.modules if name.startswith("transformers"))
print("ORIGIN=" + model.origin)
print("LIBRARY=" + ",".join(entered))
"""


def test_the_librarys_own_copy_of_the_code_is_never_what_runs(tmp_path: Path) -> None:
    """A planted file where the model library keeps repository code does not run.

    The library imports repository code from a modules cache, under a path
    built from the repository and commit, and reuses a copy it finds there.
    A modified copy is planted at that path, in both spellings the library
    uses for a repository id, and the class is then resolved the way the
    sparse adapter resolves it. The reviewed bytes run; the planted copy does
    not; and the library's machinery is never entered, which is what makes
    the first two true whatever that machinery does with its cache.

    Run in a fresh interpreter, because the library fixes its modules cache
    location when it is first imported.

    Mutation: with the class resolved through the library's dynamic-module
    loader instead of from the verified buffer, this failed on the
    library-not-entered assertion; restored, it passed.
    """
    snapshot = tmp_path / "snapshot"
    snapshot.mkdir()
    ran = tmp_path / "ran"
    (snapshot / "modeling_splade.py").write_bytes(_source(ran, "reviewed"))

    modules_cache = tmp_path / "modules"
    planted_marker = tmp_path / "planted-ran"
    owner, name = SPARSE_MODEL_ID.split("/")
    for spelled_owner, spelled_name in (
        (owner, name),
        (owner.replace("-", "_hyphen_"), name.replace("-", "_hyphen_")),
    ):
        copy = (
            modules_cache
            / "transformers_modules"
            / spelled_owner
            / spelled_name
            / SPARSE_MODEL_REVISION
        )
        copy.mkdir(parents=True)
        (copy / "modeling_splade.py").write_bytes(_source(planted_marker, "planted"))

    env = dict(os.environ)
    env["HF_MODULES_CACHE"] = str(modules_cache)
    env[EnvVar.HF_HOME.value] = str(tmp_path / "hf-home")
    proc = subprocess.run(
        [sys.executable, "-c", _LIBRARY_COPY_PROBE, str(snapshot)],
        capture_output=True,
        text=True,
        check=False,
        env=env,
        timeout=180,
    )

    assert proc.returncode == 0, proc.stderr
    assert "ORIGIN=reviewed" in proc.stdout.splitlines()
    assert "LIBRARY=" in proc.stdout.splitlines(), proc.stdout
    assert ran.read_text(encoding="utf-8") == "reviewed"
    assert not planted_marker.exists()


def _shipped_sources() -> Iterator[tuple[Path, ast.Module]]:
    for path in sorted(_PACKAGE.rglob("*.py")):
        if "tests" in path.relative_to(_PACKAGE).parts:
            continue
        yield path, ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def test_no_shipped_module_lets_a_model_library_run_repository_code() -> None:
    """Nothing in the package turns repository code on, or reaches for the
    library's loader for it.

    Three things are refused in shipped source: passing ``trust_remote_code``
    as anything but the literal ``False``; passing ``code_revision``, which
    only means something when repository code is trusted; and naming the
    library's dynamic-module machinery at all.

    Mutation: with ``trust_remote_code=True`` restored on one loader call
    this failed naming that file and line; restored, it passed.
    """
    offences: list[str] = []
    for path, tree in _shipped_sources():
        where = path.relative_to(_PACKAGE).as_posix()
        for node in ast.walk(tree):
            if isinstance(node, ast.keyword) and node.arg == "trust_remote_code":
                value = node.value
                if not (isinstance(value, ast.Constant) and value.value is False):
                    offences.append(f"{where}:{value.lineno} trust_remote_code")
            if isinstance(node, ast.keyword) and node.arg == "code_revision":
                offences.append(f"{where}:{node.value.lineno} code_revision")
            if isinstance(node, (ast.Name, ast.Attribute, ast.alias)):
                spelled = (
                    node.id
                    if isinstance(node, ast.Name)
                    else node.attr
                    if isinstance(node, ast.Attribute)
                    else node.name
                )
                if "dynamic_module" in spelled:
                    offences.append(f"{where} {spelled}")

    assert not offences, offences

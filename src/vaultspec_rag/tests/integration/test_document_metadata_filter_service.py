"""Declared metadata filters end to end through a real model-bearing service.

A hook emits per-unit metadata, the service indexes it on GPU, and searches
through the real ``/search`` route narrow on it, on an extractor family, and
refuse an undeclared key.
"""

from __future__ import annotations

import shlex
import sys
import textwrap
import time
from typing import TYPE_CHECKING, cast

import pytest

from ...indexer._run_ledger_models import RunAuthority
from ...serviceclient._search_transport import try_http_search
from ...serviceclient._transport import (
    DocumentSearchFilters,
    _try_http_get_job,
    _try_http_reindex,
)
from .._preprocess_approval import approve_preprocess_policy

if TYPE_CHECKING:
    from pathlib import Path

# Starts a second model-bearing service, so it runs in the separate subprocess
# GPU invocation with the other service-owning document tests.
pytestmark = [
    pytest.mark.subprocess_gpu,
    pytest.mark.timeout(900),
]

_PHRASE = "calibration torque specification"


def _write_fixture(root: Path) -> None:
    (root / ".vault").mkdir(exist_ok=True)
    (root / "manuals").mkdir(exist_ok=True)
    for name in ("pump", "valve"):
        (root / "manuals" / f"{name}.blob").write_bytes(b"\x00\xff " + name.encode())
    extractor = root / "extract.py"
    extractor.write_text(
        textwrap.dedent(f"""
            import json, sys
            path = sys.argv[1]
            pump = "pump" in path
            print(json.dumps({{
                "schema_version": 1,
                "preprocessor_id": "manuals.pdf.text" if pump else "manuals.pdfx",
                "preprocessor_version": "1",
                "source_path": path,
                "units": [
                    {{
                        "text": {_PHRASE!r} + " for the " + path,
                        "metadata": {{"lang": ["en", "de"] if pump else "fr"}},
                    }},
                    {{
                        "text": {_PHRASE!r} + " appendix " + path,
                        "metadata": {{"lang": 3}},
                    }},
                ],
            }}))
        """),
        encoding="utf-8",
    )
    command = f"{shlex.quote(sys.executable)} {shlex.quote(str(extractor))} {{path}}"
    (root / ".vaultragpreprocess.toml").write_text(
        "version = 2\n\n"
        '[[rule]]\npattern = "*.blob"\n'
        f"command = '''{command}'''\n"
        'target = "document"\nextractor_version = "1"\non_error = "fail"\n\n'
        '[[filterable_metadata]]\nkey = "lang"\nscope = "unit"\n',
        encoding="utf-8",
    )
    approve_preprocess_policy(root)


def _index(port: int, root: Path) -> dict[str, object]:
    created = _try_http_reindex(
        "document",
        True,
        port,
        str(root),
        authority=RunAuthority.REBUILD,
        initiator_kind="cli",
    )
    assert created is not None
    assert created["ok"] is True, created
    deadline = time.monotonic() + 300.0
    job: dict[str, object] = {}
    while time.monotonic() < deadline:
        response = _try_http_get_job(cast("str", created["job_id"]), port, timeout=5)
        if response is not None and isinstance(response.get("job"), dict):
            job = cast("dict[str, object]", response["job"])
            if job.get("state") == "succeeded":
                return job
            if job.get("state") in {"cancelled", "failed", "interrupted"}:
                pytest.fail(f"document index job ended as {job.get('state')}: {job}")
        time.sleep(0.1)
    pytest.fail(f"document index job did not succeed: {job}")


def _search(
    port: int, root: Path, filters: DocumentSearchFilters, query: str = _PHRASE
) -> dict[str, object]:
    result = try_http_search(
        query, "document", 20, port, str(root), document_filters=filters
    )
    assert result is not None
    return result


def _sources(result: dict[str, object]) -> set[str]:
    assert result.get("ok") is not False, result
    rows = cast("list[dict[str, object]]", result["results"])
    return {str(row["source_path"]) for row in rows}


def test_declared_metadata_and_extractor_family_narrow_a_served_search(
    live_service: tuple[int, Path],
) -> None:
    port, root = live_service
    _write_fixture(root)
    _index(port, root)

    german = DocumentSearchFilters(metadata_filters={"lang": ["de"]})
    any_of = _search(port, root, german)
    assert _sources(any_of) == {"manuals/pump.blob"}
    inline = _search(port, root, DocumentSearchFilters(), f"{_PHRASE} meta.lang=fr")
    assert _sources(inline) == {"manuals/valve.blob"}
    # "manuals.pdf" covers manuals.pdf.text and not manuals.pdfx.
    family = _search(port, root, DocumentSearchFilters(extractor_prefix="manuals.pdf"))
    assert _sources(family) == {"manuals/pump.blob"}
    nothing = _search(port, root, DocumentSearchFilters(extractor_prefix="other"))
    assert _sources(nothing) == set()

    refused = _search(
        port, root, DocumentSearchFilters(metadata_filters={"owner": ["me"]})
    )
    assert refused["ok"] is False
    assert refused["error"] == "unknown_filter_key"

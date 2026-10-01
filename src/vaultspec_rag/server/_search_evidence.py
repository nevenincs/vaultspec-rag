"""Finite JSON evidence for the input and returned body of a served search."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import cast

from ..store_schema import CODE_FILTER_KEYS, DOCUMENT_FILTER_KEYS, VAULT_FILTER_KEYS

MAX_REQUEST_EVIDENCE_BYTES = 64 * 1024
MAX_RESPONSE_EVIDENCE_BYTES = 128 * 1024
MAX_LEDGER_EVIDENCE_BYTES = 4 * 1024 * 1024
_MAX_DEPTH = 12
_MAX_ITEMS = 128
_MAX_TEXT_CHARS = 8192
_MAX_TRUNCATION_PATHS = 128

SEARCH_INPUT_FIELDS = frozenset(
    {
        *CODE_FILTER_KEYS,
        *VAULT_FILTER_KEYS,
        *DOCUMENT_FILTER_KEYS,
        "query",
        "top_k",
        "project_root",
        "type",
        "freshness_policy",
        "freshness_wait_seconds",
        "like_ids",
        "unlike_ids",
        "include_paths",
        "exclude_paths",
        "dedup_locales",
        "prefer",
        "exclude_domains",
        "only_domains",
        "include_domains",
        "intent",
    }
)


@dataclass(frozen=True, slots=True)
class JsonEvidence:
    """An immutable, detached JSON observation with explicit clipping paths."""

    encoded: str
    truncated_paths: tuple[str, ...]

    @property
    def size_bytes(self) -> int:
        return len(self.encoded.encode("utf-8")) + len(
            json.dumps(self.truncated_paths, ensure_ascii=False).encode("utf-8")
        )

    def materialize(self) -> object:
        return cast("object", json.loads(self.encoded))


class _JsonBudget:
    def __init__(self, maximum: int, *, path_bytes: int) -> None:
        self.remaining = maximum
        self.paths: list[str] = []
        self.path_bytes = path_bytes - 2

    def clipped(self, path: str) -> None:
        clipped = path[:512]
        size = len(json.dumps(clipped, ensure_ascii=False).encode("utf-8")) + 2
        if len(self.paths) < _MAX_TRUNCATION_PATHS and size <= self.path_bytes:
            self.paths.append(clipped)
            self.path_bytes -= size
        elif self.paths:
            self.paths[-1] = "$"

    def take(self, size: int) -> bool:
        if size > self.remaining:
            return False
        self.remaining -= size
        return True

    def clone(self, value: object, path: str, depth: int) -> object:
        if depth > _MAX_DEPTH:
            self.clipped(path)
            return None
        if isinstance(value, dict):
            return self.mapping(cast("dict[object, object]", value), path, depth)
        if isinstance(value, list):
            return self.sequence(cast("list[object]", value), path, depth)
        if isinstance(value, str):
            original = value
            value = value[:_MAX_TEXT_CHARS]
            if value != original:
                self.clipped(path)
        elif (isinstance(value, float) and not math.isfinite(value)) or (
            value is not None and not isinstance(value, bool | int | float)
        ):
            self.clipped(path)
            value = None
        encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        if not self.take(len(encoded.encode("utf-8"))):
            self.clipped(path)
            self.take(4)
            return None
        return value

    def mapping(self, value: dict[object, object], path: str, depth: int) -> object:
        self.take(2)
        result: dict[str, object] = {}
        for index, (key, item) in enumerate(value.items()):
            if index >= _MAX_ITEMS or self.remaining < 16:
                self.clipped(path)
                break
            if not isinstance(key, str):
                self.clipped(path)
                continue
            item_path = f"{path}.{key}"
            key_bytes = len(json.dumps(key, ensure_ascii=False).encode("utf-8")) + 2
            if len(key) > 512 or not self.take(key_bytes):
                self.clipped(item_path)
                continue
            result[key] = self.clone(item, item_path, depth + 1)
        return result

    def sequence(self, value: list[object], path: str, depth: int) -> object:
        self.take(2)
        result: list[object] = []
        for index, item in enumerate(value):
            if index >= _MAX_ITEMS or self.remaining < 8:
                self.clipped(path)
                break
            self.take(1)
            result.append(self.clone(item, f"{path}[{index}]", depth + 1))
        return result


def capture_json_evidence(value: object, *, maximum_bytes: int) -> JsonEvidence:
    """Copy JSON data while bounding bytes, depth, children and text length."""
    path_budget = min(8192, maximum_bytes // 4)
    budget = _JsonBudget(maximum_bytes - path_budget, path_bytes=path_budget)
    captured = budget.clone(value, "$", 0)
    encoded = json.dumps(captured, ensure_ascii=False, separators=(",", ":"))
    evidence = JsonEvidence(encoded, tuple(budget.paths))
    if evidence.size_bytes > maximum_bytes:
        return JsonEvidence("null", ("$",))
    return evidence

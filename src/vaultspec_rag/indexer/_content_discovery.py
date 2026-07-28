"""Code discovery and admission for source indexing.

Owns the read-only half of a code index operation: resolving one immutable
policy snapshot, walking the project tree with ignore-aware pruning,
classifying every visited file against that snapshot, and verifying that a
caller-supplied preflight still authorizes the work about to run.

Nothing here mutates index state. Discovery performs only configuration and
ignore-file reads plus tree traversal; it never acquires the indexer's writer
lock and never touches collection, manifest, metadata, preprocessing-cache,
or embedding resources.
"""

from __future__ import annotations

import dataclasses
import os
import pathlib
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ..index_profiles import SupportMeasurement
from ..job_control import NO_RUN_CONTROL
from . import _ignore_specs
from ._chunking import _MAX_FILE_SIZE, _is_binary
from ._content_policy import (
    AdmissionDisposition,
    AdmissionReason,
    ClassifiedContent,
    ContentKind,
    RootContentPolicy,
    SourceProfileVersion,
)
from ._scan_cache import MembershipScanCache

if TYPE_CHECKING:
    from collections.abc import Iterable

    import pathspec

    from ..config._types import PreprocessMode
    from ..job_control import RunControl
    from ._resolved_policy import ResolvedIndexPolicy

DEFAULT_SCAN_SAMPLE_LIMIT = 100


@dataclass(frozen=True, slots=True)
class AdmissionCount:
    """One stable content-kind/disposition count from a structured scan."""

    def as_payload(self) -> dict[str, object]:
        """Return the wire shape both the CLI and the route report this as."""
        return {
            "kind": self.kind.value if self.kind is not None else None,
            "admitted": self.admitted,
            "reason": self.reason.value,
            "count": self.count,
        }

    kind: ContentKind | None
    admitted: bool
    reason: AdmissionReason
    count: int


@dataclass(frozen=True, slots=True)
class _ScanFileRequest:
    dirpath: str
    files: list[str]
    rel_dir: str
    policy: ResolvedIndexPolicy
    result: list[pathlib.Path]
    counts: dict[tuple[ContentKind | None, bool, AdmissionReason], int]
    samples: list[AdmissionSample]
    sample_limit: int
    run_control: RunControl = NO_RUN_CONTROL


@dataclass(frozen=True, slots=True)
class AdmissionSample:
    """One bounded, project-relative example from a structured scan."""

    def as_payload(self) -> dict[str, object]:
        """Return the wire shape both the CLI and the route report this as.

        Two adapters projected these four fields by hand. A field added to the
        sample reaches neither until someone remembers both, and the two are
        in different packages, so nothing makes them disagree loudly.
        """
        return {
            "path": self.path,
            "kind": self.kind.value if self.kind is not None else None,
            "admitted": self.admitted,
            "reason": self.reason.value,
        }

    path: str
    kind: ContentKind | None
    admitted: bool
    reason: AdmissionReason


@dataclass(frozen=True, slots=True)
class InspectedSource:
    """One classified file and the size observed by the same probe."""

    classified: ClassifiedContent
    source_bytes: int


def _rejected_code(reason: AdmissionReason) -> ClassifiedContent:
    """Return a non-admitted code disposition for one probe outcome."""
    return ClassifiedContent(AdmissionDisposition(ContentKind.CODE, False, reason))


@dataclass(frozen=True, slots=True)
class ContentScanResult:
    """Structured discovery result and path-list compatibility authority."""

    files: tuple[pathlib.Path, ...]
    counts: tuple[AdmissionCount, ...]
    samples: tuple[AdmissionSample, ...]
    policy_fingerprint: str
    preprocess_mode: PreprocessMode
    preprocess_rule_count: int
    hooks_will_run: bool
    measurement: SupportMeasurement


@dataclass(frozen=True, slots=True)
class CodeIndexPreflight:
    """Read-only policy and discovery authority for one code operation."""

    root_dir: pathlib.Path
    policy: ResolvedIndexPolicy
    scan: ContentScanResult


@dataclass(frozen=True, slots=True)
class CodeScopedPreflight:
    """Read-only policy and exact changed-path authority for scoped work."""

    root_dir: pathlib.Path
    policy: ResolvedIndexPolicy
    changed_paths: tuple[pathlib.Path, ...]
    measurement: SupportMeasurement = field(
        default_factory=lambda: SupportMeasurement(0, 0)
    )


type CodeExecutionPreflight = CodeIndexPreflight | CodeScopedPreflight


class CodeContentDiscovery:
    """Resolves policy, discovers admissible code, and accepts preflights.

    Constructed from the three inputs that fully determine which files a root
    admits - the root directory, the caller-authored content policy, and any
    extra exclusion patterns. The only per-instance mutable state is a
    bounded-staleness cache of the last walk, so instances built from the
    same inputs stay interchangeable up to that cache's TTL: a fresh instance
    walks at once, a warm one may answer from a walk taken seconds ago.
    """

    def __init__(
        self,
        root_dir: pathlib.Path,
        *,
        content_policy: RootContentPolicy | None = None,
        extra_excludes: Iterable[str] = (),
    ) -> None:
        """Bind one root to the policy inputs that decide its admissions.

        Args:
            root_dir: Path to the project root directory to discover.
            content_policy: Caller-authored content ownership policy. The
                versioned conventional source profile is used when omitted.
            extra_excludes: Additional gitignore-syntax exclusion patterns
                (e.g. from CLI ``--exclude``). Merged into the
                ``.vaultragignore`` spec.
        """
        self.root_dir = root_dir
        self.content_policy = content_policy or RootContentPolicy(
            SourceProfileVersion.CONVENTIONAL_V1
        )
        self.extra_excludes = list(extra_excludes)
        # Cached alongside the sample limit it was taken with: a wider-limit
        # walk can serve any narrower request by truncating its samples, but
        # a narrower one cannot invent the samples a wider request needs.
        self._scan_cache: MembershipScanCache[tuple[int, ContentScanResult]] = (
            MembershipScanCache()
        )

    def invalidate_scan_cache(self) -> None:
        """Drop the cached walk after any membership-changing observation."""
        self._scan_cache.invalidate()

    def resolve_policy(self) -> ResolvedIndexPolicy:
        """Resolve and validate one immutable snapshot before mutation authority.

        Policy resolution performs only configuration and ignore-file reads. In
        particular, it does not acquire the writer lock or touch collection,
        manifest, metadata, preprocessing-cache, or embedding resources.
        """
        from ._resolved_policy import IndexPolicyResolutionOptions, resolve_index_policy

        return resolve_index_policy(
            self.root_dir,
            IndexPolicyResolutionOptions(
                content_policy=self.content_policy,
                extra_excludes=self.extra_excludes,
            ),
        )

    def preflight_content(
        self,
        *,
        sample_limit: int = DEFAULT_SCAN_SAMPLE_LIMIT,
    ) -> CodeIndexPreflight:
        """Resolve and discover once before any mutable index resource."""
        policy = self.resolve_policy()
        scan = self.scan_content(policy, sample_limit=sample_limit)
        return CodeIndexPreflight(
            root_dir=self.root_dir.resolve(),
            policy=policy,
            scan=scan,
        )

    def preflight_changed_paths(
        self,
        changed_paths: Iterable[pathlib.Path],
    ) -> CodeScopedPreflight:
        """Resolve policy and classify one exact normalized changed-path scope."""
        policy = self.resolve_policy()
        normalized = self.normalize_changed_paths(changed_paths)
        source_files = 0
        source_bytes = 0
        for path in normalized:
            rel = path.relative_to(self.root_dir).as_posix()
            policy.classify(rel)
            if path.is_file():
                inspected = self.inspect_file(path, rel, policy)
                disposition = inspected.classified.disposition
                if disposition.admitted and disposition.kind is ContentKind.CODE:
                    source_files += 1
                    source_bytes += inspected.source_bytes
        return CodeScopedPreflight(
            root_dir=self.root_dir.resolve(),
            policy=policy,
            changed_paths=normalized,
            measurement=SupportMeasurement(source_files, source_bytes),
        )

    def normalize_changed_paths(
        self,
        changed_paths: Iterable[pathlib.Path],
    ) -> tuple[pathlib.Path, ...]:
        """Return deterministic canonical paths wholly contained by this root."""
        root = self.root_dir.resolve()
        normalized = {path.resolve() for path in changed_paths}
        if any(not path.is_relative_to(root) for path in normalized):
            raise ValueError("code index scope contains a path outside its root")
        return tuple(sorted(normalized, key=lambda path: path.as_posix()))

    def accept_preflight(
        self,
        preflight: CodeExecutionPreflight,
        *,
        changed_paths: Iterable[pathlib.Path] | None,
    ) -> tuple[ResolvedIndexPolicy, tuple[pathlib.Path, ...] | None]:
        """Verify and return one exact caller-owned execution authority."""
        if preflight.root_dir != self.root_dir.resolve():
            raise ValueError(
                "code index preflight root does not match the indexer root"
            )
        if preflight.policy.root_dir != preflight.root_dir:
            raise ValueError("code index preflight policy belongs to another root")
        if isinstance(preflight, CodeIndexPreflight):
            if changed_paths is not None:
                raise ValueError("full code preflight cannot authorize scoped work")
            if (
                preflight.scan.policy_fingerprint
                != preflight.policy.fingerprints.snapshot
            ):
                raise ValueError(
                    "code index preflight policy fingerprint is inconsistent"
                )
            root = preflight.root_dir
            if any(
                not path.resolve().is_relative_to(root) for path in preflight.scan.files
            ):
                raise ValueError(
                    "code index preflight contains a path outside its root"
                )
            for path in preflight.scan.files:
                rel = path.relative_to(root).as_posix()
                disposition = preflight.policy.classify(rel).disposition
                if not (disposition.admitted and disposition.kind is ContentKind.CODE):
                    raise ValueError(
                        "code index preflight contains a path not admitted as code"
                    )
            return preflight.policy, preflight.scan.files
        if changed_paths is None:
            raise ValueError("scoped code preflight requires changed paths")
        normalized = self.normalize_changed_paths(changed_paths)
        if normalized != preflight.changed_paths:
            raise ValueError("code index scope does not match its validated preflight")
        for path in normalized:
            rel = path.relative_to(preflight.root_dir).as_posix()
            preflight.policy.classify(rel)
        return preflight.policy, None

    def collect_gitignore_patterns(self) -> list[str]:
        """Collect the hardcoded and ``.gitignore``-sourced exclusion patterns."""
        return _ignore_specs.collect_gitignore_patterns(self.root_dir)

    def collect_vaultragignore_patterns(self) -> list[str]:
        """Collect the root ``.vaultragignore`` patterns (excluding ``--exclude``)."""
        return _ignore_specs.collect_vaultragignore_patterns(self.root_dir)

    def build_vaultragignore_spec(self) -> pathspec.GitIgnoreSpec | None:
        """Build a pathspec from ``.vaultragignore`` and CLI ``--exclude`` patterns."""
        return _ignore_specs.build_vaultragignore_spec(
            self.root_dir, self.extra_excludes
        )

    def scan_codebase(
        self,
        policy: ResolvedIndexPolicy | None = None,
        *,
        run_control: RunControl = NO_RUN_CONTROL,
    ) -> list[pathlib.Path]:
        """Project structured policy discovery to admitted code paths."""
        resolved = policy or self.resolve_policy()
        return list(
            self.scan_content(
                resolved,
                sample_limit=0,
                run_control=run_control,
            ).files
        )

    @staticmethod
    def is_ignored(policy: ResolvedIndexPolicy, rel_path: str) -> bool:
        """Return ignore precedence from the resolved classifier snapshot."""
        classified = policy.classify(rel_path)
        return classified.disposition.reason is AdmissionReason.IGNORED

    @staticmethod
    def has_transform(
        policy: ResolvedIndexPolicy,
        rel_path: str,
    ) -> bool:
        """Return whether ownership includes a matched transform."""
        return policy.match_preprocess(rel_path) is not None

    def inspect_file(
        self,
        path: pathlib.Path,
        rel_path: str,
        policy: ResolvedIndexPolicy,
    ) -> InspectedSource:
        """Classify one file and report the size observed while doing it.

        The size is returned rather than left for the caller to fetch because
        every caller needs it and the classification cannot be made without
        it. Statting twice was not merely wasteful: the two probes could
        disagree on a tree being written, so a file could be admitted against
        one observation and measured against another, and each site carried
        its own copy of the "a failed probe is not admissible" rule.

        A rejected file, and any file whose probe fails, reports zero bytes:
        nothing is admitted, so there is no admitted breadth to account for.
        """
        classified = policy.classify(rel_path)
        disposition = classified.disposition
        if not (disposition.admitted and disposition.kind is ContentKind.CODE):
            return InspectedSource(classified, 0)
        # A matched transform expands the indexable set past the raw-code size
        # and binary limits, so those two checks are skipped - but the file is
        # still measured, because it is still admitted.
        transformed = self.has_transform(policy, rel_path)
        try:
            source_bytes = path.stat().st_size
            if not transformed:
                if source_bytes > _MAX_FILE_SIZE:
                    return InspectedSource(
                        _rejected_code(AdmissionReason.SOURCE_TOO_LARGE),
                        0,
                    )
                if _is_binary(path):
                    return InspectedSource(
                        _rejected_code(AdmissionReason.SOURCE_BINARY),
                        0,
                    )
        except OSError:
            return InspectedSource(
                _rejected_code(AdmissionReason.SOURCE_PROBE_FAILED),
                0,
            )
        return InspectedSource(classified, source_bytes)

    def scan_content(
        self,
        policy: ResolvedIndexPolicy,
        *,
        sample_limit: int,
        run_control: RunControl = NO_RUN_CONTROL,
    ) -> ContentScanResult:
        """Scan through one immutable policy with bounded disposition samples.

        Walks the project tree using ``os.walk``, pruning directories
        rejected by the snapshot's ignore rules. Every visited file is
        classified by that same snapshot; only admitted code paths enter the
        compatibility projection.

        Args:
            policy: Exact operation snapshot used for every disposition.
            sample_limit: Maximum number of deterministic path samples.
            run_control: Cooperative control checked between directories and
                between files so a long walk stays cancellable.

        Returns:
            Structured counts, bounded samples, and admitted code paths.

        Raises:
            OSError: If the root directory cannot be traversed.
            ValueError: If ``sample_limit`` is negative.
        """
        if sample_limit < 0:
            raise ValueError("sample_limit must be non-negative")

        fingerprint = policy.fingerprints.snapshot
        cached = self._served_from_scan_cache(fingerprint, sample_limit)
        if cached is not None:
            return cached

        result: list[pathlib.Path] = []
        source_files = 0
        source_bytes = 0
        counts: dict[tuple[ContentKind | None, bool, AdmissionReason], int] = {}
        samples: list[AdmissionSample] = []
        root_str = str(self.root_dir)
        for dirpath, dirs, files in os.walk(self.root_dir, topdown=True):
            run_control.checkpoint()
            # Prune ignored directories in-place to avoid traversal
            rel_dir = os.path.relpath(dirpath, root_str).replace("\\", "/")
            if rel_dir == ".":
                dirs[:] = [d for d in dirs if not self.is_ignored(policy, f"{d}/")]
            else:
                dirs[:] = [
                    d for d in dirs if not self.is_ignored(policy, f"{rel_dir}/{d}/")
                ]
            admitted_files, admitted_bytes = self._process_scan_files(
                _ScanFileRequest(
                    dirpath,
                    files,
                    rel_dir,
                    policy,
                    result,
                    counts,
                    samples,
                    sample_limit,
                    run_control,
                )
            )
            source_files += admitted_files
            source_bytes += admitted_bytes
            run_control.checkpoint()
        ordered_counts = tuple(
            AdmissionCount(kind, admitted, reason, count)
            for (kind, admitted, reason), count in sorted(
                counts.items(),
                key=lambda item: (
                    item[0][0].value if item[0][0] is not None else "",
                    item[0][1],
                    item[0][2].value,
                ),
            )
        )
        scan = ContentScanResult(
            files=tuple(result),
            counts=ordered_counts,
            samples=tuple(samples),
            policy_fingerprint=fingerprint,
            preprocess_mode=policy.execution_mode,
            preprocess_rule_count=len(policy.preprocess_rules),
            hooks_will_run=(
                policy.execution_mode != "off" and bool(policy.preprocess_rules)
            ),
            measurement=SupportMeasurement(
                source_files=source_files,
                source_bytes=source_bytes,
            ),
        )
        self._scan_cache.put(fingerprint, (sample_limit, scan))
        return scan

    def _served_from_scan_cache(
        self,
        fingerprint: str,
        sample_limit: int,
    ) -> ContentScanResult | None:
        """Serve *sample_limit* from the cached walk, or ``None`` to rescan.

        A cached walk can answer any request whose sample budget it covers:
        either the cached limit was at least as wide, or the walk produced
        fewer samples than its limit allowed (so the sample set is complete
        and truncation to any budget is exact).
        """
        cached = self._scan_cache.get(fingerprint)
        if cached is None:
            return None
        cached_limit, cached_result = cached
        samples_complete = len(cached_result.samples) < cached_limit
        if sample_limit > cached_limit and not samples_complete:
            return None
        if len(cached_result.samples) <= sample_limit:
            return cached_result
        return dataclasses.replace(
            cached_result,
            samples=cached_result.samples[:sample_limit],
        )

    def _process_scan_files(self, request: _ScanFileRequest) -> tuple[int, int]:
        (
            dirpath,
            files,
            rel_dir,
            policy,
            result,
            counts,
            samples,
            sample_limit,
            run_control,
        ) = (
            request.dirpath,
            request.files,
            request.rel_dir,
            request.policy,
            request.result,
            request.counts,
            request.samples,
            request.sample_limit,
            request.run_control,
        )
        admitted_files = 0
        admitted_bytes = 0
        for fname in files:
            run_control.checkpoint()
            p = pathlib.Path(dirpath) / fname
            rel = fname if rel_dir == "." else f"{rel_dir}/{fname}"
            inspected = self.inspect_file(p, rel, policy)
            disposition = inspected.classified.disposition
            source_size = inspected.source_bytes
            key = (disposition.kind, disposition.admitted, disposition.reason)
            counts[key] = counts.get(key, 0) + 1
            if len(samples) < sample_limit:
                samples.append(
                    AdmissionSample(
                        rel,
                        disposition.kind,
                        disposition.admitted,
                        disposition.reason,
                    )
                )
            if disposition.admitted and disposition.kind is ContentKind.CODE:
                result.append(p)
                admitted_files += 1
                admitted_bytes += source_size
            run_control.checkpoint()
        return admitted_files, admitted_bytes

    def scan_admission(
        self,
        *,
        sample_limit: int = DEFAULT_SCAN_SAMPLE_LIMIT,
    ) -> ContentScanResult:
        """Return structured admission from one freshly resolved snapshot."""
        return self.preflight_content(sample_limit=sample_limit).scan

    def scan_files(self) -> list[pathlib.Path]:
        """Return the list of files that would be indexed.

        Requires neither GPU nor vector store - discovery reads configuration,
        ignore files, and path metadata only.

        Returns:
            List of absolute paths to indexable source files.
        """
        return list(self.scan_admission(sample_limit=0).files)

"""Synthetic vault corpus generator for deterministic testing.

Generates `.vault/` directories with predictable content, unique needle
keywords per document, and configurable graph density.  Each document is
parseable by `vaultspec_core.vaultcore.parse_vault_metadata` and
`prepare_document`.

ADR documents additionally exercise the three real-world heading formats so
status extraction has deterministic coverage: the modern
``| (**status:** `value`)`` marker, the legacy ``# ADR: ...`` heading with no
marker (status ``unknown``), and a spread of status values. Pipeline-role
edges (research <- adr <- plan <- exec, reference <- research) are added on
top of the density-based random edges so the related-link graph expresses
pipeline lineage, not just arbitrary links.
"""

import random
from dataclasses import dataclass, field
from pathlib import Path

__all__ = [
    "CorpusManifest",
    "GeneratedDoc",
    "build_multi_project_fixture",
    "build_synthetic_vault",
]

DOC_TYPES: list[str] = ["adr", "plan", "research", "exec", "reference", "audit"]
FEATURES: list[str] = ["alpha-engine", "beta-pipeline", "gamma-index", "delta-store"]

# ADR status values cycled across generated ADRs (after the first, which is a
# legacy no-marker heading resolving to ``unknown``). Mostly accepted, with the
# inactive statuses represented so status-derank has something to derank.
_ADR_STATUS_CYCLE: list[str] = ["proposed", "superseded", "accepted", "accepted"]

# Pipeline-role link targets: a document of the key type links to the first
# document of the value type, expressing research <- adr <- plan <- exec and
# reference <- research lineage.
_PIPELINE_LINK_TARGET: dict[str, str] = {
    "adr": "research",
    "plan": "adr",
    "exec": "plan",
    "reference": "research",
}

# Topical paragraphs keyed by doc_type - each doc gets its type paragraph
# plus its needle keyword for deterministic retrieval.
_TYPE_PARAGRAPHS: dict[str, str] = {
    "adr": (
        "This architecture decision record evaluates trade-offs between "
        "competing approaches. The decision balances performance, "
        "maintainability, and operational complexity."
    ),
    "plan": (
        "This implementation plan outlines phases, milestones, and "
        "deliverables. Each phase has clear entry and exit criteria "
        "with defined verification steps."
    ),
    "research": (
        "This research document investigates technical options through "
        "literature review, benchmarking, and prototype evaluation. "
        "Findings inform downstream architectural decisions."
    ),
    "exec": (
        "This execution record documents completed implementation work "
        "including code changes, test results, and deployment notes. "
        "It traces back to the originating plan."
    ),
    "reference": (
        "This reference document captures API contracts, data schemas, "
        "and integration patterns. It serves as the authoritative "
        "specification for implementors."
    ),
    "audit": (
        "This audit report assesses code quality, security posture, "
        "and compliance status. Findings are categorized by severity "
        "with recommended remediation steps."
    ),
}


@dataclass
class GeneratedDoc:
    """A single generated vault document.

    Attributes:
        doc_id: Relative path without extension (e.g. ``"adr/test-001"``).
        doc_type: One of the 6 vault doc types.
        feature: Feature tag (without ``#``).
        needle: Unique keyword embedded in the document body.
        path: Absolute path to the written ``.md`` file.
        related_ids: List of doc_ids this document links to.
        status: For ADRs, the status the heading encodes (``accepted``,
            ``proposed``, ``superseded``, or ``unknown`` for the legacy
            no-marker heading). Empty string for non-ADR types.
    """

    doc_id: str
    doc_type: str
    feature: str
    needle: str
    date: str
    path: Path
    related_ids: list[str] = field(default_factory=list)
    status: str = ""


@dataclass
class CorpusManifest:
    """Result of a synthetic vault generation.

    Attributes:
        root: Project root directory containing ``.vault/``.
        docs: All generated documents.
        needles: Mapping from needle keyword to doc_id.
        graph_edges: Directed edges ``(from_id, to_id)`` in the
            related-links graph.
        statuses: Mapping from doc_id to the ADR status it encodes; only
            ADR doc_ids appear (``accepted``/``proposed``/``superseded``/
            ``unknown``).
    """

    root: Path
    docs: list[GeneratedDoc]
    needles: dict[str, str]
    graph_edges: list[tuple[str, str]]
    statuses: dict[str, str] = field(default_factory=dict)


def _needle_for(doc_type: str, index: int) -> str:
    """Generate a unique needle keyword for a document."""
    return f"NEEDLE_{doc_type.upper()}_{index:03d}"


def _adr_status_for(adr_ordinal: int) -> str:
    """Return the status an ADR encodes given its 0-based ADR ordinal.

    The first ADR uses the legacy no-marker heading and resolves to
    ``unknown``; subsequent ADRs cycle through the status cycle.
    """
    if adr_ordinal == 0:
        return "unknown"
    return _ADR_STATUS_CYCLE[(adr_ordinal - 1) % len(_ADR_STATUS_CYCLE)]


def _make_frontmatter(
    doc_type: str,
    feature: str,
    date: str,
    related: list[str],
) -> str:
    """Render YAML frontmatter for a vault document."""
    tags_str = f'  - "#{doc_type}"\n  - "#{feature}"'
    related_str = ""
    if related:
        lines = [f'  - "[[{r}]]"' for r in related]
        related_str = "\n".join(lines)
    else:
        related_str = "  []"

    return f"---\ntags:\n{tags_str}\ndate: {date}\nrelated:\n{related_str}\n---\n"


def _make_title(
    doc_type: str,
    feature: str,
    index: int,
    status: str,
) -> str:
    """Render the H1 title, ADR-aware.

    For ADRs the heading mirrors the canonical vaultspec-core forms: an
    ``unknown`` status renders the legacy ``# ADR: ...`` heading with no status
    marker; any other status renders the modern
    ``# `feature` adr: `...` | (**status:** `value`)`` form. Non-ADR types keep
    the simple ``# feature doc_type index`` heading.
    """
    if doc_type == "adr":
        subject = f"{feature} decision {index:03d}"
        if status == "unknown":
            return f"# ADR: {subject}"
        return f"# `{feature}` adr: `{subject}` | (**status:** `{status}`)"
    return f"# {feature} {doc_type} {index:03d}"


def _make_body(
    doc_type: str,
    feature: str,
    needle: str,
    index: int,
    status: str,
) -> str:
    """Render the markdown body with type-specific content and needle."""
    title = _make_title(doc_type, feature, index, status)
    paragraph = _TYPE_PARAGRAPHS[doc_type]
    needle_line = (
        f"This document contains the unique identifier {needle} which "
        f"can be used for precision retrieval testing."
    )
    return f"{title}\n\n{paragraph}\n\n{needle_line}\n"


def _add_pipeline_edges(
    docs: list[GeneratedDoc],
    graph_edges: list[tuple[str, str]],
) -> None:
    """Add deterministic pipeline-role edges on top of random edges.

    Links each document of a type in ``_PIPELINE_LINK_TARGET`` to the first
    document of its target type, expressing pipeline lineage. Skips
    self-links and duplicates already present from the density pass.
    """
    first_of_type: dict[str, str] = {}
    for doc in docs:
        first_of_type.setdefault(doc.doc_type, doc.doc_id)

    existing = set(graph_edges)
    for doc in docs:
        target_type = _PIPELINE_LINK_TARGET.get(doc.doc_type)
        if target_type is None:
            continue
        target_id = first_of_type.get(target_type)
        if target_id is None or target_id == doc.doc_id:
            continue
        edge = (doc.doc_id, target_id)
        if edge in existing:
            continue
        if target_id not in doc.related_ids:
            doc.related_ids.append(target_id)
        graph_edges.append(edge)
        existing.add(edge)


def build_synthetic_vault(
    root: Path,
    *,
    n_docs: int = 24,
    include_malformed: bool = False,
    graph_density: float = 0.3,
    seed: int = 42,
) -> CorpusManifest:
    """Generate a ``.vault/`` directory with predictable, searchable content.

    Args:
        root: Project root directory. ``.vault/`` is created inside.
        n_docs: Total number of well-formed documents to generate.
            Distributed evenly across the 6 doc types.
        include_malformed: If True, add extra documents with missing
            frontmatter, broken tags, and empty bodies.
        graph_density: Fraction of documents that link to another
            document via ``related:``.
        seed: Random seed for reproducible generation.

    Returns:
        A ``CorpusManifest`` with all generated documents, their
        needle keywords, status map, and the graph edge list.
    """
    rng = random.Random(seed)
    vault_dir = root / ".vault"
    docs: list[GeneratedDoc] = []
    needles: dict[str, str] = {}
    graph_edges: list[tuple[str, str]] = []
    statuses: dict[str, str] = {}

    # Ensure all doc_type subdirs exist.
    for dt in DOC_TYPES:
        (vault_dir / dt).mkdir(parents=True, exist_ok=True)

    # Also create .vaultspec so workspace resolution works.
    (root / ".vaultspec").mkdir(parents=True, exist_ok=True)

    per_type = max(1, n_docs // len(DOC_TYPES))
    doc_index = 0

    for dt in DOC_TYPES:
        for type_ordinal in range(per_type):
            feature = FEATURES[doc_index % len(FEATURES)]
            needle = _needle_for(dt, doc_index)
            date = f"2026-01-{(doc_index % 28) + 1:02d}"
            stem = f"2026-01-{(doc_index % 28) + 1:02d}-{feature}-test-{doc_index:03d}"
            doc_id = f"{dt}/{stem}"
            status = _adr_status_for(type_ordinal) if dt == "adr" else ""

            docs.append(
                GeneratedDoc(
                    doc_id=doc_id,
                    doc_type=dt,
                    feature=feature,
                    needle=needle,
                    date=date,
                    path=vault_dir / dt / f"{stem}.md",
                    related_ids=[],
                    status=status,
                ),
            )
            needles[needle] = doc_id
            if dt == "adr":
                statuses[doc_id] = status
            doc_index += 1

    # Build graph links based on density.
    for doc in docs:
        if rng.random() < graph_density:
            candidates = [d for d in docs if d.doc_id != doc.doc_id]
            if candidates:
                target = rng.choice(candidates)
                doc.related_ids.append(target.doc_id)
                graph_edges.append((doc.doc_id, target.doc_id))

    # Add deterministic pipeline-role edges on top of the random ones.
    _add_pipeline_edges(docs, graph_edges)

    # Write all documents.
    for doc in docs:
        # related: strip doc_type prefix for wiki-link stem
        related_stems = [rid.split("/", 1)[1] for rid in doc.related_ids]
        fm = _make_frontmatter(doc.doc_type, doc.feature, doc.date, related_stems)
        idx = int(doc.doc_id.split("-")[-1])
        body = _make_body(doc.doc_type, doc.feature, doc.needle, idx, doc.status)
        doc.path.write_text(fm + "\n" + body, encoding="utf-8")

    # Optionally add malformed documents.
    if include_malformed:
        _add_malformed_docs(vault_dir, docs)

    return CorpusManifest(
        root=root,
        docs=docs,
        needles=needles,
        graph_edges=graph_edges,
        statuses=statuses,
    )


def _add_malformed_docs(vault_dir: Path, docs: list[GeneratedDoc]) -> None:
    """Add malformed documents for edge-case testing."""
    # Missing frontmatter entirely.
    p = vault_dir / "adr" / "malformed-no-frontmatter.md"
    p.write_text(
        "# No Frontmatter\n\nThis document has no YAML frontmatter.\n",
        encoding="utf-8",
    )
    docs.append(
        GeneratedDoc(
            doc_id="adr/malformed-no-frontmatter",
            doc_type="adr",
            feature="",
            needle="NEEDLE_MALFORMED_NOFM",
            date="",
            path=p,
        ),
    )

    # Empty body (frontmatter only).
    p = vault_dir / "plan" / "malformed-empty-body.md"
    p.write_text(
        '---\ntags:\n  - "#plan"\n  - "#broken"\ndate: 2026-01-01\n'
        "related:\n  []\n---\n",
        encoding="utf-8",
    )
    docs.append(
        GeneratedDoc(
            doc_id="plan/malformed-empty-body",
            doc_type="plan",
            feature="broken",
            needle="NEEDLE_MALFORMED_EMPTY",
            date="2026-01-01",
            path=p,
        ),
    )

    # Broken tags (not a list).
    p = vault_dir / "research" / "malformed-broken-tags.md"
    p.write_text(
        "---\ntags: not-a-list\ndate: 2026-01-01\nrelated:\n  []\n---\n\n"
        "# Broken Tags\n\nTags field is a string, not a list.\n",
        encoding="utf-8",
    )
    docs.append(
        GeneratedDoc(
            doc_id="research/malformed-broken-tags",
            doc_type="research",
            feature="",
            needle="NEEDLE_MALFORMED_TAGS",
            date="2026-01-01",
            path=p,
        ),
    )


def build_multi_project_fixture(
    base: Path,
    *,
    n_projects: int = 2,
    docs_per_project: int = 12,
    seed: int = 42,
) -> list[CorpusManifest]:
    """Create multiple project roots with distinct, non-overlapping corpora.

    Args:
        base: Parent directory; each project is a subdirectory.
        n_projects: Number of project roots to create.
        docs_per_project: Documents per project.
        seed: Base random seed (incremented per project).

    Returns:
        List of ``CorpusManifest`` instances, one per project.
    """
    manifests: list[CorpusManifest] = []
    for i in range(n_projects):
        project_root = base / f"project-{i}"
        project_root.mkdir(parents=True, exist_ok=True)
        manifest = build_synthetic_vault(
            project_root,
            n_docs=docs_per_project,
            seed=seed + i,
        )
        manifests.append(manifest)
    return manifests

"""Code-search noise policy: resolve the active profile and apply it.

Pure functions and one value type that turn the persistent noise profile
(``config``) plus per-call overrides into a concrete policy, then enforce it
over a result set: hard-drop hidden domains, restrict to an ``only`` set, and
soft-demote the rest. The classifier is the shared :func:`classify_domain`, so
a chunk that predates the stored ``domain`` payload is classified the same way
at query time - the pushdown and the fallback never disagree.

All functions here are pure (no I/O, no GPU); the searcher owns the Qdrant
fetch and the GPU rerank and calls these to shape candidates and final scores.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from .._domain import NOISE_DOMAINS, classify_domain

if TYPE_CHECKING:
    from collections.abc import Iterable

    from ..config import VaultSpecConfigWrapper
    from ._models import SearchResult

__all__ = [
    "NoisePolicy",
    "apply_domain_demotion",
    "domain_of_payload",
    "partition_hard_domains",
    "resolve_noise_policy",
]


@dataclass(frozen=True)
class NoisePolicy:
    """The resolved, per-request code-search noise policy.

    Attributes:
        hide: Domains hard-dropped from results (profile hide set plus
            per-call ``--exclude-domain``, minus ``--include-domain``).
        only: When non-empty, keep only chunks whose domain is in this
            set (per-call ``--only-domain``).
        demote: Domains kept but score-penalised so production ranks
            first (profile demote set, minus hidden and re-admitted).
        penalty: Score subtraction applied to a demoted result.
    """

    hide: frozenset[str]
    only: frozenset[str]
    demote: frozenset[str]
    penalty: float

    @property
    def has_hard_filter(self) -> bool:
        """True when the policy drops or restricts candidates."""
        return bool(self.hide or self.only)


def _clean(domains: Iterable[str] | None) -> frozenset[str]:
    """Normalise caller domain tokens to the known noise-domain set."""
    if not domains:
        return frozenset()
    return frozenset(d.strip().lower() for d in domains) & NOISE_DOMAINS


def resolve_noise_policy(
    cfg: VaultSpecConfigWrapper,
    *,
    exclude_domains: Iterable[str] | None = None,
    only_domains: Iterable[str] | None = None,
    include_domains: Iterable[str] | None = None,
) -> NoisePolicy:
    """Combine the persistent profile with per-call overrides into a policy.

    ``--include-domain`` re-admits a domain the profile would hide or demote;
    ``--exclude-domain`` adds to the hide set; ``--only-domain`` restricts.
    Hidden always wins over demoted, and re-admitted always wins over both, so
    no domain is acted on twice.
    """
    include = _clean(include_domains)
    hide = (frozenset(cfg.code_noise_hide_domains) | _clean(exclude_domains)) - include
    demote = frozenset(cfg.code_noise_demote_domains) - include - hide
    only = _clean(only_domains)
    return NoisePolicy(
        hide=hide,
        only=only,
        demote=demote,
        penalty=float(cfg.code_noise_demote_penalty),
    )


def domain_of_payload(raw: dict[str, object]) -> str:
    """Return a raw result's stored domain, classifying its path as fallback.

    A chunk indexed before the ``domain`` payload existed carries no ``domain``
    field; classify its path so the query-time filter still applies.
    """
    stored = raw.get("domain")
    if isinstance(stored, str) and stored:
        return stored
    return classify_domain(str(raw.get("path", "")))


def partition_hard_domains(
    raw_results: list[dict[str, object]],
    policy: NoisePolicy,
) -> tuple[list[dict[str, object]], dict[str, int]]:
    """Drop hidden/non-``only`` raw results; return survivors and drop counts.

    The post-query counterpart of the Qdrant ``domain`` pushdown: it re-applies
    the same hide/only decision so chunks the pushdown could not match (no
    stored ``domain`` payload yet) are still filtered. Returns the kept results
    and a per-domain count of what was dropped, so depletion is reportable
    rather than silent.
    """
    if not policy.has_hard_filter:
        return raw_results, {}
    kept: list[dict[str, object]] = []
    dropped: dict[str, int] = {}
    for raw in raw_results:
        domain = domain_of_payload(raw)
        if policy.only and domain not in policy.only:
            dropped[domain] = dropped.get(domain, 0) + 1
            continue
        if domain in policy.hide:
            dropped[domain] = dropped.get(domain, 0) + 1
            continue
        kept.append(raw)
    return kept, dropped


def apply_domain_demotion(results: list[SearchResult], policy: NoisePolicy) -> None:
    """Subtract the demote penalty from demoted-domain results, then re-sort.

    Mutates scores in place and re-sorts descending. A no-op when the demote
    set is empty or the penalty is non-positive. The CrossEncoder's
    query-relevance score stays primary; this only sinks noise below
    production near-ties.
    """
    if not policy.demote or policy.penalty <= 0:
        return
    for result in results:
        if classify_domain(result.path) in policy.demote:
            result.score -= policy.penalty
    results.sort(key=lambda r: r.score, reverse=True)

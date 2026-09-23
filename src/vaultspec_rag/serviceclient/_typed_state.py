"""Parse what a service reports about itself into the shared typed models.

The service serialises its health and state through the operator state models,
so the client parses the same models back instead of picking dicts apart. A
payload that does not validate - a service from another release, or a body
that is not a report at all - parses to ``None``, and the caller reports the
version or reachability problem it already knows how to explain, rather than
rendering fields it cannot trust.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast

import pydantic

from ..operator_state._models import HealthReport, ServiceStateReport

__all__ = ["parse_report"]


def parse_report[Report: (HealthReport, ServiceStateReport)](
    model: type[Report], payload: object
) -> Report | None:
    """Return the typed report of *model* in *payload*, or ``None``."""
    if not isinstance(payload, Mapping):
        return None
    try:
        return model.model_validate(dict(cast("Mapping[str, object]", payload)))
    except pydantic.ValidationError:
        return None

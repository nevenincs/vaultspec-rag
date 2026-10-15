"""Every wait layered over a lifecycle verb covers that verb's own budget.

A restart stops the service and then starts it. The start it runs can
legitimately spend most of an hour building the managed runtime before it
fetches a model, so a wrapper holding it to anything shorter kills a working
start after the stop has already succeeded: no service running, and a
half-built runtime behind it. The same holds for the monitor, which forwards
the same verbs through its own server and its own browser request.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from ..cli._service_restart import _step_timeout_seconds
from ..cli._service_start import start_budget_seconds
from ..cli._service_stop import STOP_BUDGET_SECONDS
from ..service_runtime import RUNTIME_PROVISION_BUDGET_SECONDS

pytestmark = pytest.mark.unit


def test_restart_waits_out_each_step_s_own_budget() -> None:
    """Holding the start step to a constant fails the budget assertion.

    Mutation: ``_step_timeout_seconds`` returning ``1020.0`` for the start
    step fails ``start step must cover the start budget`` (1020.0 against
    22850.0); returning the start budget passes. Returning the start budget
    for the stop step too fails ``assert stop == STOP_BUDGET_SECONDS``
    (22850.0 against 150.0); returning ``STOP_BUDGET_SECONDS`` passes.
    """
    start = _step_timeout_seconds("start")
    stop = _step_timeout_seconds("stop")
    assert start >= start_budget_seconds(), "start step must cover the start budget"
    # The term the restart used to cut short: a first build of the managed
    # runtime downloads the GPU stack, which the start alone allows an hour.
    assert start > RUNTIME_PROVISION_BUDGET_SECONDS
    assert stop == STOP_BUDGET_SECONDS
    assert stop < start, "stop must not wait out a start it never provisions for"


def test_the_monitor_waits_out_the_verb_it_forwards() -> None:
    """Shortening either monitor budget fails the covering assertion.

    Mutation: the ``start`` the budget module returns set to ``900 * second``
    fails ``monitor start must cover the start budget`` (900.0 against
    22850.0); the derived sum passes. ``restart`` returned as the start
    budget alone fails ``monitor restart must cover a stop and a start``
    (22850.0 against 23000.0); ``start + stop`` passes.
    """
    node = shutil.which("node")
    assert node is not None
    source = Path(__file__).resolve().parents[2] / "monitor/lifecycle-budget.ts"
    script = (
        "import { lifecycleBudgetMilliseconds, clientMarginMilliseconds } "
        f"from {json.dumps(source.as_uri())};"
        "console.log(JSON.stringify({...lifecycleBudgetMilliseconds(),"
        "margin:clientMarginMilliseconds}));"
    )
    result = subprocess.run(
        [node, "--input-type=module", "-e", script],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    budget = json.loads(result.stdout.strip().splitlines()[-1])

    start = start_budget_seconds()
    assert budget["start"] / 1000 >= start, "monitor start must cover the start budget"
    assert budget["stop"] / 1000 >= STOP_BUDGET_SECONDS, (
        "monitor stop must cover the stop budget"
    )
    assert budget["restart"] / 1000 >= start + STOP_BUDGET_SECONDS, (
        "monitor restart must cover a stop and a start"
    )
    # The browser outlasts the server it waits on, so a verb that runs out of
    # time is reported by the owner rather than aborted by the page.
    assert budget["margin"] > 0

# Automatic convergence reference

Automatic convergence keeps code and vault indexes current after filesystem changes.
The resident service owns collection, admission, retries, and publication.

For service setup, see [Service mode](service-mode.md). For command-wide syntax, see
the [CLI reference](cli.md). Automatic updates require `watch_enabled = true`, which
is the default.

## Operator surfaces

| Surface             | Lookup                                                                                           |
| ------------------- | ------------------------------------------------------------------------------------------------ |
| CLI, human          | `vaultspec-rag server updates status`                                                            |
| CLI, JSON           | `vaultspec-rag server updates status --json`                                                     |
| Filtered CLI        | `vaultspec-rag server updates status --root PATH --source code --state backpressured --limit 20` |
| HTTP                | `GET /watcher?root=PATH&source=code&state=backpressured&limit=20`                                |
| Jobs                | `GET /jobs` and `GET /jobs/{job_id}` expose the matching `controller` object                     |
| Service state       | `GET /service-state` exposes `watcher.controllers`                                               |
| Python admin client | `get_watcher_state(root=..., source=..., state=..., limit=...)`                                  |

The HTTP and JSON surfaces return one canonical controller object. Human output labels
the same values without recalculating state, age, deadlines, or pressure.

`GET /watcher` returns at most 256 controllers by default. `limit` accepts `0` through
`256`. The response includes `controllers_total`, `controllers_returned`,
`controllers_truncated`, and the applied `filters`.

## Controller identity and fields

Each controller owns one canonical project root and one source: `code` or `vault`.

| Field                     | Meaning                                                                            |
| ------------------------- | ---------------------------------------------------------------------------------- |
| `root`                    | Canonical absolute project root                                                    |
| `source`                  | `code` or `vault`                                                                  |
| `state`                   | Current state from the state table                                                 |
| `reason`                  | Stable reason code from the reason table                                           |
| `pending_count`           | Changed paths waiting outside the captured batch                                   |
| `oldest_age_seconds`      | Age of the oldest pending or captured observation; `null` when empty               |
| `first_observed_at`       | Earliest retained observation timestamp                                            |
| `latest_observed_at`      | Latest retained observation timestamp                                              |
| `captured_generation`     | Scope generation captured by the active attempt                                    |
| `captured_count`          | Paths captured by the active attempt                                               |
| `next_decision_at`        | Timestamp for the next controller decision, or `null`                              |
| `freshness_deadline`      | Latest bounded convergence timestamp, or `null`                                    |
| `measurement`             | Timestamped, generation-stamped service measurements                               |
| `measurement_unavailable` | Measurement names the service could not observe                                    |
| `backpressure`            | Ordered stable reason codes blocking admission                                     |
| `last_transition`         | Previous state, new state, reason, timestamp, deadline, and measurement generation |
| `job_id`                  | Associated service job identifier, or `null`                                       |
| `retry_at`                | Next retry timestamp, or `null`                                                    |
| `circuit_state`           | Retry circuit state                                                                |
| `remediation`             | Operator action for a refusal, or `null`                                           |

`measurement` contains `generation`, `observed_at`, `job_backlog`, `index_in_flight`,
`index_waiters`, `search_in_flight`, `search_latency_seconds`, `gpu_pressure`,
`storage_available`, and `service_quiesced`. Missing facts stay explicit. They never
justify an unbounded delay.

## States

| State           | Meaning                                                             |
| --------------- | ------------------------------------------------------------------- |
| `idle`          | No retained work                                                    |
| `collecting`    | Changes are accumulating inside the coalescing window               |
| `ready`         | A bounded scope is eligible for admission                           |
| `admitted`      | The scheduler selected the scope                                    |
| `running`       | The associated index job is running                                 |
| `cooling_down`  | A successful job is inside its post-success cost delay              |
| `backpressured` | Current service measurements delay admission                        |
| `retrying`      | A retry delay or retry admission is active                          |
| `refused`       | The controller cannot converge automatically; inspect `remediation` |
| `converged`     | The captured scope completed without remaining work                 |

## Stable reason codes

| Reason                          | Meaning                                                        |
| ------------------------------- | -------------------------------------------------------------- |
| `change_observed`               | A filesystem change entered the scope                          |
| `coalesce_window_active`        | The minimum or adaptive collection window remains open         |
| `quiet_tree_deadline`           | The quiet-tree collection deadline arrived                     |
| `batch_limit_reached`           | The captured batch reached its path limit                      |
| `maximum_freshness_due`         | The freshness deadline requires a decision                     |
| `fair_turn_selected`            | The admission arbiter selected this eligible controller        |
| `job_admitted`                  | The service admitted the captured scope                        |
| `job_started`                   | Its service job started                                        |
| `job_completed`                 | Its service job completed                                      |
| `job_cancelled`                 | Its service job was cancelled                                  |
| `job_superseded`                | A newer authoritative attempt superseded the job               |
| `post_success_cost_delay`       | The controller is observing its cooling ceiling                |
| `job_backlog`                   | Job backlog blocks admission                                   |
| `search_pressure`               | Search concurrency or latency blocks admission                 |
| `gpu_pressure`                  | Device pressure blocks admission                               |
| `storage_pressure`              | Storage or backend pressure blocks admission                   |
| `service_quiesced`              | The service is not accepting this work                         |
| `retry_delay_active`            | The next retry time has not arrived                            |
| `retry_admitted`                | A retry is eligible to run                                     |
| `circuit_open`                  | The retry circuit blocks automatic attempts                    |
| `full_reindex_required`         | Incremental convergence is unsafe; request an explicit rebuild |
| `scope_state_invalid`           | Persisted scope state cannot be resumed safely                 |
| `scope_capacity_exceeded`       | Retained scope exceeded its configured capacity                |
| `controller_schema_unsupported` | Persisted controller data uses an unsupported schema           |
| `converged`                     | No pending path remains                                        |

Reason codes are additive API values. Automation should handle unknown future values
without treating them as success.

## Policy settings

Set keys in configuration or use the matching `VAULTSPEC_RAG_` environment variable.

| Key                                      | Environment variable                                   |   Default | Valid values              |
| ---------------------------------------- | ------------------------------------------------------ | --------: | ------------------------- |
| `watch_coalesce_min_seconds`             | `VAULTSPEC_RAG_WATCH_COALESCE_MIN_SECONDS`             |     `2.0` | Number, at least `0`      |
| `watch_coalesce_max_seconds`             | `VAULTSPEC_RAG_WATCH_COALESCE_MAX_SECONDS`             |    `30.0` | Number, at least `0`      |
| `watch_cooling_max_seconds`              | `VAULTSPEC_RAG_WATCH_COOLING_MAX_SECONDS`              |   `120.0` | Number, at least `0`      |
| `watch_maximum_freshness_seconds`        | `VAULTSPEC_RAG_WATCH_MAXIMUM_FRESHNESS_SECONDS`        |   `300.0` | Number, greater than `0`  |
| `watch_measurement_reevaluation_seconds` | `VAULTSPEC_RAG_WATCH_MEASUREMENT_REEVALUATION_SECONDS` |     `5.0` | Number, greater than `0`  |
| `watch_batch_path_limit`                 | `VAULTSPEC_RAG_WATCH_BATCH_PATH_LIMIT`                 |   `10000` | Integer, greater than `0` |
| `watch_scope_max_paths`                  | `VAULTSPEC_RAG_WATCH_SCOPE_MAX_PATHS`                  |  `100000` | Integer, greater than `0` |
| `watch_scope_max_bytes`                  | `VAULTSPEC_RAG_WATCH_SCOPE_MAX_BYTES`                  | `8388608` | Integer, greater than `0` |

The complete policy must satisfy these relations:

- `watch_coalesce_min_seconds <= watch_coalesce_max_seconds`
- `watch_maximum_freshness_seconds` is at least the coalescing maximum, cooling
  maximum, and measurement reevaluation interval
- `watch_batch_path_limit <= watch_scope_max_paths`

Invalid relationships fail configuration loading with a `ValueError` that names the
conflicting keys and values.

### Deprecated timing mapping

`watch_debounce_ms` and `VAULTSPEC_RAG_WATCH_DEBOUNCE_MS` remain accepted for
compatibility. When explicitly set, the millisecond value supplies both coalescing
bounds unless the corresponding adaptive key is explicit.

`watch_cooldown_s` and `VAULTSPEC_RAG_WATCH_COOLDOWN_S` remain accepted for
compatibility. When explicitly set, the value supplies the cooling maximum unless
`watch_cooling_max_seconds` is explicit.

The `server updates timing` flags retain the same mapping:
`--update-delay-ms` maps to the coalescing bounds, and
`--repeat-update-delay-s` maps to the cooling maximum.

## Freshness, fairness, and scope

The coalescing bounds let a busy tree form efficient batches. The freshness deadline
bounds that delay. Measurement reevaluation also has a bounded interval, so unavailable
or stale pressure evidence cannot postpone work indefinitely.

Admission is fair across eligible root/source controllers. A busy project cannot claim
every turn while another eligible controller waits.

Each attempt captures an exact path scope and generation. New observations remain
pending for a later attempt. Completion consumes only the captured generation, which
prevents path loss and duplicate consumption.

Persisted scope and retry state survive service restart. Generation fencing prevents a
stale job or callback from publishing over a newer attempt.

## Refusals and remediation

A `refused` controller needs operator action. Read `reason`, `remediation`,
`measurement_unavailable`, and `last_transition` together.

| Reason                          | Operator response                                                        |
| ------------------------------- | ------------------------------------------------------------------------ |
| `full_reindex_required`         | Inspect the refusal and request an explicit rebuild                      |
| `scope_state_invalid`           | Inspect service logs, then rebuild the affected source                   |
| `scope_capacity_exceeded`       | Increase the scope limits or reduce the changed set, then rebuild        |
| `controller_schema_unsupported` | Run a compatible service version or rebuild the affected source          |
| `circuit_open`                  | Inspect the job failure and retry evidence before requesting another run |

The service supplies `remediation`. If a refusal lacks a specific message, the canonical
default is `Inspect the refusal reason and request an explicit rebuild.`

## Troubleshooting lookups

```text
vaultspec-rag server updates status --state refused
vaultspec-rag server updates status --source code --limit 20 --json
vaultspec-rag server jobs --trigger watcher
vaultspec-rag server logs --limit 200
```

Use the `job_id` from a controller with the jobs and logs commands. For service startup,
shutdown, and recovery details, see [Service mode](service-mode.md). For every jobs and
updates option, see the [CLI reference](cli.md).

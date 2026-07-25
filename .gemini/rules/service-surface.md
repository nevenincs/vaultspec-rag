---
name: service-surface
trigger: always_on
---

# Service surface

## Rule

- Implement health, status, jobs, logs and search diagnostics as service-domain
  behaviour. Adapt CLI and MCP to it. Never let an entry point own or duplicate
  it.
- Bound every operator list and tail command. Make them filterable. Bias them to
  current actionable state, not full history.
- Emit exactly one structured envelope on every exit path of a lifecycle verb in
  JSON mode, success and failure alike.
- Treat an already-satisfied request as success: exit zero with an already-done
  status.
- Exit non-zero in both human and JSON mode when the requested state is not
  achieved.

## Why

- Entry points that drift show operators conflicting names, contracts and
  remediation for one condition.
- Full history and unfiltered tails hide running work behind stale noise.
- A broker misreads a non-zero already-running start as a gateway error, and
  must be able to start or stop speculatively.
- A stop that leaves the service running is a failure and must not report
  success.

## How

- Good: filter in the service route, pass the same parameters through the CLI
  verb and the MCP tool, keep the envelope stable across adapters.
- Good: default the jobs view to a bounded set; expose state, failed, job-id and
  since filters; search a bounded log window before returning a filtered tail.
- Good: converge every terminal branch on one success or one failure helper per
  verb, and carry initiator attribution on terminating outcomes.
- Bad: a CLI-only path computing different phases from the service.
- Bad: rendering every recorded job by default.
- Bad: printing human text on a JSON path, or emitting zero or two envelopes.

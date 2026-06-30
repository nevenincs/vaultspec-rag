---
tags:
  - '#research'
  - '#service-observability'
date: '2026-06-01'
modified: '2026-06-30'
related:
  - "[[2026-06-01-service-operability-research]]"
---

# service-observability research: server state surface (#142)

The #142 slice of the broader service-operability investigation. The full
grounding (current-source analysis + prior-ADR reconciliation) lives in the
service-operability research; this records the observability-specific findings
that ADR-B builds on. ADR-A already delivered the watcher config + control half
(#143/#144/#145); this is the read/observe half.

## Findings

- **Only `/health` + `/mcp` exist** on the resident service today. The CLI reaches
  the daemon as an MCP client through the `_try_mcp_admin` seam (post-split, in
  the `cli/` package); `list_projects`/`evict_project` already ride it.
- **Governing principle (from the cluster): CLI ⇄ MCP parity, read-only
  monitoring + MCP-transported control — not a second control plane.** The prior
  admin-route rejection covered duplicate *control* over HTTP; read-only
  monitoring and MCP-transported reads are consistent with it. New HTTP routes
  are justified only where MCP's structured tool protocol serves poorly: raw
  log-as-text and a Prometheus scrape target.
- **No server-side job/progress state exists.** Reindex tools run synchronously
  with `NullProgressReporter`; the watcher reindexes invisibly. A jobs/queue view
  is therefore net-new: it needs a small in-flight activity registry the watcher
  and reindex paths write to.
- **Service log is rotated** (`DaemonRotatingFileHandler`, 10 MiB × 5): a `/logs`
  reader must span `service.log`, `.log.1`, … and tolerate mid-rollover races.
- **Routing rule:** new routes are Starlette `Route`s on the inner app (now
  assembled in the `mcp_server/` package), never additional ASGI wrappers.
- **`service_token` is identity-only today** — gating the new HTTP routes is a
  fresh decision (bearer header vs loopback-only); `/health` stays ungated.
- **Tiering by cost:** Tier 1 structured status/projects/watcher-state (mirror
  existing state, MCP tool + CLI subcommand, optional HTTP); Tier 2a logs (HTTP
  route + MCP tool + CLI); Tier 2b jobs/queue (the net-new registry); Tier 3
  `/metrics` (greenfield, HTTP-native, pull/on-demand to avoid a background
  thread).

---
tags:
  - '#adr'
  - '#monitor-capability'
date: '2026-10-04'
modified: '2026-10-04'
body_schema: 'body-v2'
body_hash: 'sha256:c39ebc128ab1a6497aab7bd57f9d1f7819ceba3686d7fd200404ed919b79c8fd'
related:
  - "[[2026-10-04-monitor-capability-reference]]"
  - "[[2026-10-04-monitor-access-adr]]"
  - "[[2026-10-04-loopback-http-security-adr]]"
  - "[[2026-09-30-monitor-browser-adr]]"
  - "[[2026-10-02-monitor-delivery-adr]]"
  - "[[2026-10-02-monitor-lifecycle-adr]]"
  - "[[2026-09-30-monitor-tooling-adr]]"
---

# `monitor-capability` adr: `Require an owner capability at the local monitor bridge` | (**status:** `accepted`)

## Problem Statement

The loopback monitor admits any local OS account and then acts with the service owner's backend credential and owner subprocesses. Loopback reachability is not owner authentication. Evidence: `2026-10-04-monitor-capability-reference`.

## Considerations

The user's 2026-10-04 instruction asks for this validated finding to be fixed and supplies the remediation: a distinct high-entropy monitor capability required before the backend token is read, Host/Origin checks retained, and an authenticated owner decision for repository enrollment. Earlier accepted rulings promise a monitor with no login, credential prompt or browser token; those promises were made against a remote-attacker model and must be reconciled. The owner already has two private channels to the monitor and a browser cannot use owner-ACL sockets, as the reference establishes.

## Considered options

- A capability minted by the monitor, delivered through the owner's launch link and presented as a bearer credential on every bridge call. Chosen: it authenticates the owner on all three entry points with no prompt, and the browser holds it only in per-origin session storage.
- A capability minted by the daemon and handed to the monitor. Rejected: an older monitor ignores it and stays open while the daemon reports it protected.
- A cookie set from the launch link. Rejected: loopback cookies are shared across ports and reach another account's listener.
- Peer-credential checks on the loopback socket, or owner-ACL Unix sockets. Rejected for this fix: no browser transport for the latter, and the former needs a separate privileged mechanism per platform that the Vite entry cannot load.
- Keep loopback, Host and Origin checks as the only gate. Rejected: they do not distinguish the owner from another local account.

## Constraints

Authorization: the user's explicit 2026-10-04 security-fix request and supplied remediation authorize this ruling. It is a scoped reversal of the credential-free local operation committed in `2026-09-30-monitor-browser-adr`, `2026-10-02-monitor-delivery-adr` and `2026-10-04-monitor-access-adr`, and of the bare-port readiness line in `2026-10-02-monitor-lifecycle-adr`. Reconcile their current wording to this boundary; their other commitments, including loopback binding and Host/Origin admission, remain in force.

Every monitor bridge operation requires the monitor capability, checked after loopback admission and before the request body, the route, service discovery, the backend credential or any owner subprocess is touched. A missing or wrong capability is refused with 401 and reaches none of them. The comparison is constant-time. The backend service token is never accepted as the capability, and the capability is never sent to the backend. Static assets and build metadata carry no protected state and stay behind loopback admission only.

The capability is at least 256 bits from the platform CSPRNG, minted by the monitor process at startup, held in memory, and never written to disk by the monitor. It is distinct for every monitor incarnation. It leaves the process only as the fragment of the access link written to the launcher's channel: the readiness line in the compiled command, and the server log line in Vite dev and preview. It never appears in a query string, a response body, a redirect or a log record written by the service.

The managed daemon reads the access link from the readiness pipe without logging it, validates that it names the loopback address and the reported port, and publishes it only in protected same-user service discovery. `server start` reports that link, on first start and on idempotent reuse, in human output and as `data.monitor_url`. A readiness line without a valid link fails the coupled start. The bridge strips the link from every response it returns.

The browser moves the capability from the fragment into session storage for its own origin, removes it from the address bar, and presents it as a bearer credential. There is still no login form, credential prompt, admin role or storage that outlives the tab. Without the link the page loads and reports that the access link is required.

Repository enrollment is authorized by the capability-authenticated submission of the existing explicit enrollment dialog. No unauthenticated or backend-token-only caller can enroll. A second confirmation factor is not added.

## Implementation

We will mint the capability in the shared bridge module, gate the bridge prefix in the shared middleware, and expose one access-link builder that the compiled server and the Vite plugin print. The Python supervisor parses the link, the start verb reports it, and the browser fetch helper adopts and presents it. Tests, the delivered-binary smoke and the installed-browser driver use the same link. This bounded direct work needs no plan. The fragment key and the line spelling are implementation details.

## Rationale

Minting in the monitor makes version skew fail closed and keeps one owner for the secret's shape. The fragment and per-origin session storage keep it away from servers, referrers and other loopback ports. Gating at the shared middleware covers the credential read, the lifecycle subprocesses and the persisted-inventory fallback with one check, as `2026-10-04-monitor-capability-reference` traces.

## Consequences

Opening the bare monitor address no longer operates the service; the owner opens the link reported by `server start` or printed by a directly launched monitor. A new browser tab needs the link again. Scripts that called the bridge without a credential must present the capability from `data.monitor_url`. Anyone who can read the owner's protected discovery file or terminal holds the capability, which is the existing owner boundary. Acceptance records the authorized boundary, not completion of verification. Reconsider if a second confirmation factor for enrollment, a multi-user monitor or direct remote access becomes a requirement.

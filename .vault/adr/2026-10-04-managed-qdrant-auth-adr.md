---
tags:
  - '#adr'
  - '#managed-qdrant-auth'
date: '2026-10-04'
modified: '2026-10-04'
body_schema: 'body-v2'
body_hash: 'sha256:c986327e9b729f038eea29fd35ea0c42c18d0d599944a51d0ecc43c17308b610'
related:
  - "[[2026-10-04-managed-qdrant-auth-audit]]"
  - "[[2026-06-12-qdrant-server-provisioning-adr]]"
  - "[[2026-10-04-loopback-http-security-adr]]"
---

# `managed-qdrant-auth` adr: `Require a per-instance credential on the managed Qdrant data plane` | (**status:** `accepted`)

## Problem Statement

The supervised Qdrant child listens on predictable loopback TCP ports with no credential, so any local account reaches the indexed collections directly and bypasses the token-gated service in front of them. Loopback binding separates hosts, not operating-system users. The managed-qdrant-auth audit records the finding and the pinned binary's behaviour under a key.

## Considerations

- The child is configured only through its curated environment, and the pinned server reads one service API key that it enforces on REST and gRPC alike while leaving readiness, liveness and the root version route anonymous (managed-qdrant-auth audit, pinned-binary-key-behaviour).
- More than one process is a client: the daemon's stores and maintenance tasks, a second daemon attaching to a running child, and the storage command group in a separate CLI process. The credential must reach all of them without travelling over the network.
- loopback-http-security already publishes the service credential through same-user protected files written by the private atomic writer; the same mechanism is available here.
- Supervised restarts reuse the supervisor while stores hold long-lived clients, so a key that changed on restart would strand every open store.
- The server's service settings offer a host and two TCP ports. It has no socket-path or named-pipe listener, and a network namespace is unavailable on Windows and macOS and needs privilege on Linux.

## Considered options

- Per-instance API key over loopback TCP, published to an owner-only file: chosen. Works on every supported platform with the pinned binary and closes both protocols with one setting.
- Owner-isolated IPC (Unix socket or named pipe): rejected because the server cannot listen on one, and a proxy in front of it would leave the TCP listeners open behind the proxy.
- Network namespace around the child: rejected as Linux-only and privileged; the product supports Windows and macOS equally.
- Publish the key through the daemon's process environment only: rejected because the storage commands run in another process, and because every subprocess the daemon starts would inherit the secret.
- Disable the gRPC listener instead of protecting it: not pursued; one key covers both listeners, and removing a listener is a separate compatibility question.

## Constraints

Authorization: the user's 2026-10-04 request to fix the reported finding, whose remediation names a generated, owner-protected per-instance credential required on both protocols, passed to every internal client, with startup verification that anonymous requests fail. This ruling refines qdrant-server-provisioning: its statement that API-key plumbing is only the remote-server escape hatch no longer holds for the managed child. Loopback binding, the curated child environment, binary verification and supervision in that record continue to apply. It reuses loopback-http-security's rule that credentials are obtained only from same-user protected files and protected before secret bytes are written.

- Every supervised child requires a key on REST and gRPC. No supervised start path spawns an unauthenticated server.
- The key comes from the operating system's secure random source with at least 256 bits, is created per supervisor instance and kept for that supervisor's lifetime including its restarts. An operator-configured key is adopted instead of a generated one.
- The key is written to an owner-only file beside the managed identity record before the child is spawned, and reaches the child only through its curated environment. It never appears in logs, status, health or state surfaces.
- Every internal server client is built by one constructor that resolves the credential. A configured key wins; otherwise the managed credential is sent, and only to the managed loopback endpoint, never to another host. The managed endpoint is the literal loopback address at the managed port: a host name, including localhost, is resolved outside this process and does not qualify.
- After the server reports ready, on spawn, restart and attach, an anonymous data request must be refused and the credential must be accepted. Otherwise the start fails and an owned child is stopped. Attaching to a running managed server that accepts anonymous requests is refused.
- Readiness and version probes stay anonymous.

## Implementation

We will give the supervisor a credential it generates or adopts, publish it through the private atomic writer next to the identity sidecar, add the service API-key setting to the child environment, and verify the data plane after readiness. One client constructor replaces the seven direct constructions and suppresses the client's plaintext-key warning for loopback only. The managed-endpoint test already used by storage reconciliation becomes the shared definition of which URL may receive the managed credential.

Hypotheses that may change within the constraints: the file name and JSON shape of the credential record; verifying over REST only at startup while gRPC is covered by a test against the pinned binary; leaving a stale credential file in place after a clean stop.

## Rationale

A key enforced by the server is the only option that closes both listeners on all three platforms with the binary already pinned. A protected file is how the service credential is already distributed, so no second mechanism is introduced and a separate CLI process is served by the same read. One constructor makes a client without the credential impossible to add by omission, which is the defect the audit's second finding records. Verifying after readiness turns a binary that ignores the setting into a refused start instead of a silently open store.

## Consequences

- A different local account can still connect to the ports but cannot read or change collections; liveness and version stay visible to it.
- A daemon upgraded in place refuses to attach to a child started by an older daemon; restarting the service replaces it. Storage commands from the new version still work against an old child because no credential file exists and none is sent.
- Operators pointing at their own server keep using the configured key; the managed credential is never sent to it.
- The same local user, and an administrator, can read the key from the file or from the child's environment. That is the trust boundary the service token already has.
- Reconsider if the server gains an owner-isolated listener, or if a read-only client appears that should hold a narrower credential.

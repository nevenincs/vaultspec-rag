---
tags:
  - '#research'
  - '#service-health-client-hardening'
date: '2026-07-22'
modified: '2026-07-22'
body_hash: 'sha256:9a767386deb7b5a0cbceeb7ace8760abfaf7efe31de9a1e057b5afc328669dfb'
related:
  - "[[2026-07-22-codebase-dedup-centralization-audit]]"
---

# `service-health-client-hardening` research: `health probe duplication, redirect policy, and stop-path identity`

Two HTTP clients reach the service health endpoint: a CLI probe in
`src/vaultspec_rag/cli/_process.py:307` and the shared wire transport in
`src/vaultspec_rag/serviceclient/_transport.py:306`. The question asked was
whether the duplication is a justified split - the CLI probe running before a
service status file exists, and therefore unable to use the transport - or
redundancy whose ownership should move.

The premise behind the justified-split reading is false. The transport has no
status-file dependency, and it already serves the health endpoint itself. But
the duplication is not simple redundancy either, because the two clients differ
in three behaviours - redirect policy, timeout bounding, and error signalling -
and in each the CLI probe's behaviour is the safer one. One of those
differences is a live defect rather than a design choice, and it interacts with
a second defect found in the stop path while tracing it. The terrain is
therefore neither of the two options originally posed, and the decision the ADR
must make is correspondingly different from the one that was framed.

## Findings

### The transport does not depend on the service status file

The justification offered for the split does not hold. `_do_http_call` at
`src/vaultspec_rag/serviceclient/_transport.py:306` takes the port as an
explicit required parameter; it performs no discovery and therefore needs no
status file to address the service. Its token acquisition tolerates absence at
every stage: `_status_file_token` at `_transport.py:178` returns an empty string
when no status file is present rather than failing, and the empty token is sent
as-is. Only if the route answers 401 does `_fetch_health_token` at
`_transport.py:189` read the ungated health endpoint for a live token, and that
function returns an empty string on any failure, including connection refused,
so the caller's normal error handling still applies.

The decisive evidence is that the transport already does the thing it was
believed unable to do. `_health_summary` at `_transport.py:870` calls
`_do_http_call(port, "/health", None, timeout=1.0)` at `_transport.py:872`.
A health call through the transport, with no status file required, is existing
shipped behaviour.

This matters beyond correcting a premise: every prior recommendation about this
duplication rested on the belief that a bootstrap ordering barrier existed. No
such barrier exists, so the reasoning that produced those recommendations does
not survive, independently of what is decided next.

### The nine call sites consume payload fields, not liveness

Consolidation is expensive rather than trivial because no caller wants a
boolean. Every site parses the response body:

- `src/vaultspec_rag/cli/_service_start.py:186` reads `status` to report an
  already-running service; `_service_start.py:809` reads `status` and
  `service_token`, persisting the token into the status file so delegated
  authentication works before the first heartbeat tick lands.
- `src/vaultspec_rag/cli/_service_stop.py:244`, inside `_service_pid_on_port`
  (defined at `_service_stop.py:233`), reads `pid` and `service_token`.
- `src/vaultspec_rag/cli/_status_render.py:88` reads `service_token` for an
  identity comparison; `_status_render.py:140` embeds the entire response as a
  nested payload in JSON output; `_status_render.py:688`, `:812`, and `:1016`
  read `status` and pass the parsed dict onward to summary helpers.
- `src/vaultspec_rag/cli/_process.py:162`, inside `_is_our_service`, reads
  `service_token`.
- `src/vaultspec_rag/tests/integration/_helpers.py:122` uses it to wait for
  readiness.

A replacement must therefore return the parsed body with the same field
availability, not a liveness verdict.

### The two clients disagree on redirects, and the CLI is correct

The CLI probe explicitly refuses redirects. `_NoRedirect` at
`src/vaultspec_rag/cli/_process.py:238` is documented as rejecting HTTP
redirects to prevent server-side request forgery via the health endpoint, and
`_health_probe` installs it at `_process.py:322`. The transport does the
opposite on the same endpoint: `_fetch_health_token` at `_transport.py:203` and
`_send_call` at `_transport.py:256` both use the bare standard-library opener,
which follows redirects by default. The project has already decided, in code
and in a comment, that redirects are a risk on this endpoint; the transport
contradicts that decision.

Refusing redirects is the correct behaviour for a liveness and identity check
against a loopback machine-singleton, and the consequence is not theoretical.
The stop path runs `_service_pid_on_port` at `_service_stop.py:314`, takes the
`pid` from the health response, and reaches `_terminate_and_confirm(pid)` at
`_service_stop.py:340`. A followed redirect would source the process identifier
selected for termination from whichever host the redirect named.

Two mitigating facts are recorded so severity is not overstated. No route in
`src/vaultspec_rag/server/_routes.py` emits a 3xx response, so the service
itself never redirects; exploitation requires a hostile or confused listener
holding the target port, reachable by pointing the port option at it or by
another process binding the default port before the daemon does. The condition
is real but requires a local adversary or a port collision, and the corrective
change is confined to how the opener is constructed.

### A followed redirect transmits the service bearer token to the redirect target

The redirect divergence has a second and more serious consequence than the
process-identifier confusion above, on the transport's general request path
rather than its health path.

The standard library's redirect handler copies every header from the original
request onto the follow-up request except `content-length` and `content-type`.
It performs no host comparison and strips no credentials, which differs from
some third-party HTTP clients that drop an authorization header when a redirect
crosses to another host. The follow-up request therefore carries whatever
authorization the original carried, to whatever URL the redirect names.

The transport sets exactly such a header. `_build_call_request` assigns
`Authorization` as a bearer credential at
`src/vaultspec_rag/serviceclient/_transport.py:231` and passes that header
mapping into the request object at `_transport.py:236-242`, on both the
payload-carrying and payload-free branches. Those become the request headers the
redirect handler copies.

Because that path uses the bare opener at `_transport.py:256`, a redirect
answered on the target port causes the service bearer token to be transmitted to
an attacker-chosen destination. This is credential disclosure rather than
misdirection, and it is materially more serious than the health path's
process-identifier consequence: the health endpoint is ungated and its response
is a value the client misreads, whereas here a secret the client holds leaves
the machine.

The same mitigating conditions apply as for the health path - no route the
transport calls emits a 3xx, so a hostile or confused listener on the target
port is required - and the same single corrective change, constructing the
opener to refuse redirects, removes both consequences at once.

### The stop-path identity gate cannot distinguish our service from any consistent responder

This was found while tracing the redirect consequence and is a separate defect,
recorded because it changes how load-bearing the redirect policy is.

The stop path treats the health response as an identity proof, but the proof is
self-referential. `_service_stop.py:324` unpacks both `pid` and `token` from the
health response, then passes that same token as the expected value into
`_is_our_service` at `_service_stop.py:325`. That function, at
`_process.py:161`, probes the health endpoint again and compares the returned
token to the expected one at `_process.py:168`. Both sides of the comparison
originate from the same responder, so the check is satisfied by any listener
that answers consistently with itself. It can detect a service whose token has
rotated between two reads; it cannot detect an impostor.

The interaction with the previous finding is the point. The no-redirect opener
is presently compensating for an identity check that does not establish
identity: it is what confines a consistent responder to the local port rather
than allowing an arbitrary redirect target to supply both halves of the
comparison. Any change that moves the health call onto a redirect-following
client removes that compensation while leaving the weak check in place.

Not investigated: whether other callers of `_is_our_service` supply an
independently sourced expected token - for example one read from the status
file rather than from the same probe - in which case the weakness would be
specific to the stop path rather than general to the function.

### The transport's default timeout is unbounded, latently

`_do_http_call` declares `timeout` with a default of `None` at
`_transport.py:310`. When it is `None` the internal deadline helper returns
`None`, which reaches the standard-library opener as no timeout at all, so the
call blocks on the socket default rather than on any bound the caller intended.
The CLI probe cannot exhibit this: `_health_probe` at `_process.py:307`
declares a five-second default.

This is latent, not active. Every current health caller passes an explicit
timeout - one second at `_transport.py:872`. The hazard is that consolidation
would point nine further call sites at a client whose default is unbounded.
Relatedly, `_fetch_health_token` defaults to the thirty-second administrative
timeout at `_transport.py:204` for what is a liveness-shaped request.

A correction to an earlier characterisation belongs here: the one-hundred-and-
twenty-second timeout associated with this area is not in this transport. It is
`store_operation_timeout_seconds` at `src/vaultspec_rag/config.py:624`, which
governs the vector-store client. This transport's own constants are a
three-hundred-second search default and a thirty-second administrative default
at `_transport.py:59-60`.

### The error contracts differ, which makes consolidation a contract change

The two clients signal failure incompatibly. `_health_probe` never raises: it
returns `None` for connection-level failure and a dict carrying an error status
and HTTP code when the server answered unhealthily, and its call sites branch on
the `None` sentinel. `_do_http_call` raises on connection-level failure, routing
the exception through its deadline-exhausted helper.

Moving ownership therefore rewrites failure handling at all nine sites, not just
their call syntax. Two of those sites are in the service stop and service start
verbs, which are bound by the codified requirement that a broker-facing verb
emit exactly one structured outcome envelope on every exit path. An exception
escaping a stop branch that previously read a sentinel is precisely the failure
that requirement exists to prevent, so the consolidation cannot be treated as a
mechanical substitution.

### What the decision must settle

The evidence supports separating two questions that the original framing
combined, but the research does not settle either.

First, ownership: whether the health call has one owner or two. The
justification previously offered for two is false, but the CLI probe's redirect
policy, bounded default, and non-raising contract are each safer than the
transport's, so consolidation is only sound onto a client that has adopted
those behaviours. The ADR must decide which client owns the call, and if
ownership moves, what happens to the nine call sites and to the module
docstring at `_transport.py:1-8`, which currently claims every call funnels
through the transport - a claim the nine bypassing call sites already falsify.

Second, the error contract: whether the owning client signals unreachability by
sentinel or by exception, and how that reconciles with the one-envelope
requirement on the lifecycle verbs.

The redirect divergence and the self-referential identity gate are defects on
their own merits, independent of how ownership is decided. Whether they are
remedied before, within, or after the ownership change is itself a sequencing
question for the ADR, with the constraint that the identity gate's weakness is
currently masked by the very redirect policy under discussion.

## Sources

Transport:

- `src/vaultspec_rag/serviceclient/_transport.py:1-8` - module docstring
  claiming every call funnels through the transport
- `src/vaultspec_rag/serviceclient/_transport.py:59-60` - search and
  administrative timeout defaults
- `src/vaultspec_rag/serviceclient/_transport.py:178` - status-file token
  reader, tolerates absence
- `src/vaultspec_rag/serviceclient/_transport.py:189` - health-token fetch;
  `:203` bare opener; `:204` administrative timeout default
- `src/vaultspec_rag/serviceclient/_transport.py:231` - bearer authorization
  header assignment; `:236-242` - header mapping passed into the request on both
  branches
- `src/vaultspec_rag/serviceclient/_transport.py:245` - request sender; `:256`
  bare opener
- `src/vaultspec_rag/serviceclient/_transport.py:306` - the shared call entry
  point; `:310` unbounded timeout default
- `src/vaultspec_rag/serviceclient/_transport.py:870` - health summary; `:872`
  health call through the transport

CLI probe and identity:

- `src/vaultspec_rag/cli/_process.py:238` - redirect-refusing handler and its
  stated rationale
- `src/vaultspec_rag/cli/_process.py:307` - the probe; `:322` opener
  construction
- `src/vaultspec_rag/cli/_process.py:161-168` - identity check and token
  comparison

Call sites:

- `src/vaultspec_rag/cli/_service_start.py:186`, `:809`
- `src/vaultspec_rag/cli/_service_stop.py:233`, `:244`, `:314`, `:324`, `:325`,
  `:340`
- `src/vaultspec_rag/cli/_status_render.py:88`, `:140`, `:688`, `:812`, `:1016`
- `src/vaultspec_rag/tests/integration/_helpers.py:122`

Supporting:

- `src/vaultspec_rag/config.py:624` - vector-store operation timeout, the
  hundred-and-twenty-second value misattributed to the transport
- `src/vaultspec_rag/server/_routes.py` - scanned for redirect responses; none
  found

Standard library:

- `urllib.request.HTTPRedirectHandler.redirect_request` - copies all request
  headers to the redirect target except `content-length` and `content-type`,
  with no host comparison and no credential stripping; read from the source of
  the interpreter this project targets on 2026-07-22

All code claims above were established by reading the code at the locators cited
on 2026-07-22. No claim rests on a live exploit: no request was made against a
running service or a redirecting listener, so both redirect consequence chains -
the process-identifier confusion and the token disclosure - are traced
statically through the call graph and the standard library's source rather than
demonstrated end to end. The header-copying behaviour was read from the
interpreter's own source rather than taken from documentation or memory. The
remaining general-knowledge claim is that the default opener follows redirects
while a custom handler can refuse them, which is why the two constructions
differ.

---
tags:
  - '#research'
  - '#service-quiesce'
date: '2026-08-02'
modified: '2026-08-13'
body_schema: 'body-v1'
body_hash: 'sha256:8d6f36b7663877afb198cdaf1164de55c300707b3f853128df62d4ed8232bec8'
related:
  - '[[2026-07-24-service-quiesce-adr]]'
  - '[[2026-07-24-service-quiesce-research]]'
  - '[[2026-07-24-service-quiesce-plan]]'
---

# `service-quiesce` research: `paused state legibility`

A deliberately paused service currently presents itself to operators and agents as a
broken one. The question is how the quiesced state should read across the CLI, MCP, and
JSON envelopes so that it is recognisable as intentional, retryable, and recoverable,
without weakening the fail-closed borrower coordination that the pause exists to serve.
The stakes are concrete: every caller that meets a paused service today is routed to a
remediation that cannot help, and the one field the service publishes to say "this will
pass" never reaches the caller. The evidence shows the governing decision already
mandates the answer for five surfaces and was never carried to three of them, so the
rendering work is conformance debt rather than an open design space.

Driving pause live then surfaced a second question that outranks the first. An operator's
pause can be captured by an unrelated borrower that arrives while it is held, converting a
hold the operator can release into one they cannot, for an unbounded time, across every
project on the machine. That is not a rendering defect, and the same missing controller
field sits underneath both: nothing published says a pause is borrower-bound. The
legibility work is still worth doing, but it would otherwise ship a surface that states a
remediation which is sometimes simply unavailable.

## Findings

### An operator pause can be captured by a borrower and then has no undo

A borrower that arrives while an operator's pause is held binds to that pause and takes
ownership of releasing it. Binding is gated only on a supplied capability and an achieved
transition (`src/vaultspec_rag/server/_routes.py:1247`), and a pause request against an
already-quiesced service returns `ALREADY_QUIESCED` with `achieved: true`
(`src/vaultspec_rag/service_quiesce.py:367-371`). Both conditions hold for a borrower
calling pause on a service an operator already quiesced, so the binding is recorded at
`src/vaultspec_rag/server/_routes.py:1254`. The borrower never needed to cause the pause
to own it.

Reproduced against the live service on `vaultspec-rag@0.4.1` on 2026-08-02, driving the
production borrower APIs from the service's own interpreter. An operator pause carrying no
capability reached `quiesced` at `admission_epoch: 11`. A borrower then acquired the
machine lease and called pause on that already-quiesced service, receiving `ok: true` with
`status: already_quiesced` — a call that changed no state and yet took ownership of it. The
operator's own unqualified resume was then refused with `ok: false`,
`status: borrower_lease_required`, `retryable: true`, and the controller still reporting
`state: quiesced`. Only the borrower-qualified resume restored the service, at
`admission_epoch: 12`. The capture is real, and it is reachable through documented public
routes with no misuse.

From that point the operator has no lever. An unqualified resume is refused at the route
before the controller is reached (`src/vaultspec_rag/server/_routes.py:1265-1271`, with the
refusal set at `.vault/adr/2026-07-24-service-quiesce-adr.md:70`). `abort_pause` is not an
alternative: it refuses every state except `pausing`
(`src/vaultspec_rag/service_quiesce.py:486-490`) and is reachable only from inside resume
(`src/vaultspec_rag/service.py:624`). There is no clock-based expiry
(`.vault/adr/2026-07-24-service-quiesce-adr.md:68`). Recovery is contingent solely on the
borrower releasing its OS lease or dying, after which the heartbeat resumes that
quiescence (`:70`).

The blast radius is the machine, not the caller: the service is the single hardware
authority (`:26`) and was serving four projects in the observed capture. The remaining
lever — killing the borrower — requires a PID the design deliberately withholds (`:70`).
The reported incident self-recovered in roughly a minute, but nothing bounds it; a borrower
holding the lease for a full GPU test run holds search down for every project for that
run's duration.

The code still assumes otherwise. `src/vaultspec_rag/service.py:609-612` documents resume
as "the single operator-facing way back to `running`", which stops being true the moment a
binding exists.

The refusal envelope carries its own legibility defect: `message` is the literal string
`borrower_lease_required`, a repeat of the error code rather than a sentence. Any surface
that renders `message` shows an operator a bare token for the one condition they most need
explained.

The binding itself is not the defect. It exists to stop an operator resuming underneath a
live borrower and rebuilding GPU residency while another process is using the card, which
is the fail-closed property the whole feature was built for. So the question is not whether
to bind but which pauses a borrower may take ownership of, and what the operator is owed
when it has.

Declining to bind a pause the borrower did not initiate is only safe if the borrower also
declines to borrow. An unbound borrower proceeding against a service the operator can
resume at will is the original hazard restored. Paired with a refusal it is coherent and
fail-closed: the borrower is turned away and waits for the operator rather than taking the
pause from them. Its cost is real and worth stating plainly — the GPU is genuinely free
during an operator pause, `safe_to_borrow_gpu` reports true, and a borrower that could have
used it safely is refused anyway because ownership of that pause is not available. The
operator's ability to undo is bought with some borrower throughput.

The other candidates are weaker. Capping a bound hold and auto-releasing past the cap
reopens admission while the borrower may still hold the card, which contradicts the property
the binding enforces; an operator force-release verb has the same defect with a human
pressing it. Publishing a non-secret bound indicator carries no such conflict and is
required by any of them, because a surface that cannot name the holder cannot explain the
wait. A held-since or expected-release signal is additive to it.

### A new snapshot field costs a TUI rendering degradation, not borrower safety

Publishing anything new on the controller snapshot is not free, but it is affordable.
Three consumers validate the block against `QUIESCE_ENVELOPE_FIELDS`, which each compiles
from its own build (`src/vaultspec_rag/service_quiesce.py:180`): the borrower safety gate
compares the field set for exact equality (`src/vaultspec_rag/cli/_gpu_lease.py:451`), the
TUI does the same (`src/vaultspec_rag/cli/_jobs_tui.py:145`), and preflight requires an
exact field count (`src/vaultspec_rag/cli/_service_preflight.py:84`).

A version skew in either direction therefore fails the whole block, not just the unknown
field. The module's own docstring (`src/vaultspec_rag/service_quiesce.py:183-185`)
anticipates it: a copy of the name set away from the controller turns any added field into
a silent rendering failure.

The cost is nonetheless smaller than that implies, because release compatibility is exact
version equality — `is_compatible` is true only in the match state
(`src/vaultspec_rag/serviceclient/_compat.py:99-101`), which is why a `0.4.0` client is
refused by a `0.4.1` service. The two safety-critical consumers are already behind that
gate: the borrower resolves compatibility before it may pause
(`src/vaultspec_rag/cli/_gpu_lease.py:229-234`) and preflight derives compatibility from the
published version before reading state (`.vault/adr/2026-07-24-service-quiesce-adr.md:81`).
A mismatched field set is therefore unreachable on those paths — a skewed pair is refused
earlier, with a clearer error.

That leaves the TUI, which renders the block without a hard version gate and would degrade
to its `quiesce unavailable` row against a skewed daemon. So a new snapshot field costs one
release-boundary rendering degradation in the TUI, not a borrower-safety regression, and it
does not require relaxing the exact-set validators.

### The mandate already exists and the plan never carried it to the CLI

The accepted decision record already requires this. `.vault/adr/2026-07-24-service-quiesce-adr.md:66`
states that health, service-state, jobs output, MCP service-state, and the TUI render the
same controller block. Measured by reference count across the candidate surfaces, only
two modules honour it: `src/vaultspec_rag/server/_routes.py` publishes the block, and
`src/vaultspec_rag/cli/_jobs_tui.py` renders it. `_status_render.py`, `_status_labels.py`,
`_service_status.py`, `_jobs_tui_status.py`, `_service_jobs_presentation.py`, `_render.py`,
`_search.py`, `_index.py`, and `server/_routes_jobs.py` contain zero references to it.

This is unaudited conformance debt, not a rejected option. `.vault/plan/2026-07-24-service-quiesce-plan.md`
has no unchecked steps and no step naming the status renderer or the health verdict, and
none of the eight quiesce audits in `.vault/audit/` mentions the degraded verdict, the
status renderer, or `server doctor`. The gap was never considered and rejected; it was
never in scope.

### The health verdict reports the pause's success criterion as a fault

`src/vaultspec_rag/server/_lifespan.py:917-925` derives the verdict from `model_loaded`
alone and never consults the controller. Pause deliberately releases the shared embedding
and reranker objects and the allocator cache (`.vault/adr/2026-07-24-service-quiesce-adr.md:60`),
and `quiesced` is reachable only once resident GPU components are unloaded
(`:47`). The unloaded model is therefore the pause working, not a defect.

Observed live on `vaultspec-rag@0.4.1` on 2026-08-02 at `admission_epoch: 9`, with the
controller reporting `state: quiesced`, `vram_released: true`, `safe_to_borrow_gpu: true`:
`health.status` was `degraded`, `degraded_reasons` was `["embedding models are not loaded"]`,
and `next_action` was `vaultspec-rag server doctor`. The remediation is authored at
`src/vaultspec_rag/cli/_status_labels.py:418-423` and addresses a condition that is not
present; `server doctor` cannot resolve a deliberate pause.

### Human status output names neither the pause nor the paused jobs

Captured verbatim from `vaultspec-rag server status` while quiesced:

```
Server: running
Requests: degraded
Degraded because:
  - embedding models are not loaded
    run server warmup when the model files are missing
    vaultspec-rag server doctor
Busy: idle
Next action:
  vaultspec-rag server doctor
```

Neither "paused" nor "quiesced" appears. `_status_health_label`
(`src/vaultspec_rag/cli/_status_labels.py:111-126`) has no controller branch and falls
through to `status.replace("_", " ")`. `_status_busy_label` (`:157-170`) derives every row
from `running` and `queued` only, so the four jobs held in `paused` rendered as `idle` and
as `0 active` in the processed-jobs row.

That fall-through is also evidence for the option space below: an unrecognised status
value already renders as itself rather than failing, and the comment at `:261` explicitly
anticipates "a status this build has never seen". A new status value would therefore
degrade legibly on an older CLI.

### The CLI discards the retryability the service publishes

`src/vaultspec_rag/server/_routes_search.py:1068-1088` emits `retryable: true` alongside a
`quiesce` block carrying `state`, `admission_epoch`, and `safe_to_borrow_gpu`. The CLI
forwards a fixed six-key allowlist — `db_path`, `backend_capabilities`, `diagnostics`,
`port`, `timeout_seconds`, `remediation` (`src/vaultspec_rag/cli/_render.py:189-200`) — so
both are silently dropped. Observed output was `{"ok": false, "command": "search", "error": "quiesce_admission_closed", "message": "..."}` and nothing further, at exit 1.

The retryability is contractual: `.vault/adr/2026-07-24-service-quiesce-adr.md:92` records
that search requests during transition receive a retryable outcome. It reaches the HTTP
boundary and stops there.

The allowlist shape makes recurrence the default: every field a future envelope adds is
dropped until someone remembers to widen it. The alternatives are to extend the allowlist,
which is minimal but leaves the shape that caused this, or to invert to pass-through with
a denylist for fields the CLI owns, which fixes the class at the cost of forwarding
service fields the CLI has not vetted for rendering.

### Correct remediation is not currently expressible

The capture hazard above has a rendering consequence that survives whatever is decided
about the hold itself: `vaultspec-rag server resume` is correct advice for an operator
pause and wrong for a bound one, and no surface can tell which it is looking at.
`QuiesceSnapshot` (`src/vaultspec_rag/service_quiesce.py:146`, whose fields define the
published envelope at `:180`) carries no binding indicator — the fields are state,
admission epoch, admissions-open, ticket count, drain and VRAM evidence, borrower safety,
four timestamps, and a failure reason.

Any remediation string printed today is therefore a guess, and printing the wrong one is
worse than printing none: it sends an operator to a verb that returns a refusal naming a
lease they have no way to inspect. The secrecy constraints bind the capability and the PID
(`.vault/adr/2026-07-24-service-quiesce-adr.md:53`, `:70`); a boolean stating that some
binding exists is neither, so publishing one appears compatible with them. Whether to do
so is for the ADR, and it is the field both this finding and the capture hazard need.

### The borrow-lease refusal is the same root cause on a second path

`src/vaultspec_rag/cli/_gpu_lease.py:150-154` raises `gpu_borrow_lease_unavailable` with
"Another process already holds the GPU borrower lease." Its only reachable caller is
`src/vaultspec_rag/cli/_index.py:568`, behind `index --borrow-gpu`. The message names
neither the pause nor the fact that the holder is a borrower that will release it, which
leaves a caller with no reason to retry rather than escalate. A pause-aware message is
available without naming the holder, which the secrecy constraints forbid.

This corrects the hypothesis that opened this research: search never emits this code.
Search emits `quiesce_admission_closed` (`src/vaultspec_rag/server/_routes_search.py:1076`).
The two are distinct paths sharing one root cause — the borrower pause is legible to the
service and to nothing else.

### An observer discipline already exists and should be imported, not restated

The TUI is the working analogue. `_canonical_quiesce_block`
(`src/vaultspec_rag/cli/_jobs_tui.py:137-141`) accepts only the complete controller
vocabulary, repairs nothing, and derives no lifecycle state from a single field. Its
rendering vocabulary (`:2106`) is one line carrying the controller state, then `vram` as
either `released` or `held`, then `borrower safety` as either `safe` or `unsafe`, toned by
`safe_to_borrow_gpu`. Its absence handling (`:2110-2132`) deliberately gives both failure
modes one name so that one condition does not wear two.

The canonical vocabulary is `QUIESCE_ENVELOPE_FIELDS` (`src/vaultspec_rag/service_quiesce.py:180`),
already imported by the TUI at `:36` and by `src/vaultspec_rag/cli/_gpu_lease.py:29`. Any
new renderer must import it rather than restate the field set.

Whether the TUI's pill vocabulary suits a line-oriented non-interactive surface is
untested; it was designed for a bounded-width cell.

### Option space for the health verdict

Three shapes, all compatible with the mandate:

- **Suppress the models reason while quiesced, keep `degraded`.** Smallest change and no
  contract movement, but still reports a working pause as degraded, so automation keyed on
  the verdict is unchanged.
- **Publish a distinct status value for the paused state.** Matches what the state is, and
  the fall-through above means older clients render it legibly rather than breaking. It
  moves a published contract consumed by start-path classification
  (`src/vaultspec_rag/cli/_service_start.py:396`) and by version compatibility, so the blast
  radius needs weighing.
- **Keep the verdict, replace only the remediation.** Fixes the actively wrong advice at
  the lowest cost and leaves the misleading verdict in place.

The evidence favours the second on legibility and forward compatibility, but the contract
movement is exactly the trade-off the ADR must weigh rather than research.

### Not investigated

The heartbeat recovery path was not forced. The reproduction restored the service through
the borrower-qualified resume rather than by releasing the lease and waiting, because the
former cannot be refused by a process holding the capability and the latter would have left
search closed machine-wide for an unbounded interval. Recovery after borrower death or
release is therefore still evidenced only by the accepted record
(`.vault/adr/2026-07-24-service-quiesce-adr.md:70`) and the reported incident, not by
observation here. How long that recovery takes, and whether it is bounded at all, is the
open measurement.

MCP tool-level rendering was not observed: the connected client is `0.4.0` against a
`0.4.1` service, and the version-compatibility refusal masks the paused-state response.
Whether "jobs output" in the mandate means the jobs route payload or the CLI jobs view is
unresolved; `server/_routes_jobs.py` has no controller reference either way. Whether a
bounded cap on a held pause can be reconciled with the fail-closed rule was not analysed —
auto-releasing past a cap reopens admission under a borrower that may still hold the card,
which is the exact condition the binding prevents. No load or timing behaviour was
examined.

### What the ADR must settle

First, what an operator is owed while a borrower holds their pause — the bound-hold
question above, which governs whether this feature is safe to use on a shared machine and
which the remaining items depend on.

Then: whether the controller publishes a non-secret bound indicator, which both the hold
question and correct remediation require; which health-verdict option to take; whether the
CLI envelope forwarding becomes pass-through or a widened allowlist; and the wording of the
borrow-lease refusal within the no-identity constraint.

Sequencing matters here. Deciding the verdict and the renderers first would produce a
surface whose most important sentence — what to do about the pause — is still unanswerable.

## Sources

- `.vault/adr/2026-07-24-service-quiesce-adr.md:26`, `:47`, `:53`, `:60`, `:66`, `:68`, `:70`, `:92`
- `.vault/plan/2026-07-24-service-quiesce-plan.md`
- `src/vaultspec_rag/server/_lifespan.py:917-925`
- `src/vaultspec_rag/server/_routes.py:1247`, `:1254`, `:1265-1271`
- `src/vaultspec_rag/server/_routes_search.py:1068-1088`, `:1076`
- `src/vaultspec_rag/service.py:609-612`, `:624`
- `src/vaultspec_rag/service_quiesce.py:146`, `:180`, `:367-371`, `:486-490`
- `src/vaultspec_rag/cli/_status_labels.py:111-126`, `:157-170`, `:261`, `:418-423`
- `src/vaultspec_rag/cli/_render.py:189-200`
- `src/vaultspec_rag/cli/_gpu_lease.py:29`, `:150-154`, `:229-234`, `:451`
- `src/vaultspec_rag/serviceclient/_compat.py:99-101`
- `src/vaultspec_rag/cli/_jobs_tui.py:145`
- `src/vaultspec_rag/cli/_service_preflight.py:84`
- `src/vaultspec_rag/service_quiesce.py:183-185`
- `src/vaultspec_rag/cli/_index.py:568`
- `src/vaultspec_rag/cli/_jobs_tui.py:36`, `:137-141`, `:2106`, `:2110-2132`
- `src/vaultspec_rag/cli/_service_start.py:396`
- Live capture of `vaultspec-rag server status` and `vaultspec-rag search`, `vaultspec-rag@0.4.1`, 2026-08-02, controller `admission_epoch: 9`
- Live reproduction of borrower capture against `vaultspec-rag@0.4.1`, 2026-08-02, controller `admission_epoch: 11` through `12`

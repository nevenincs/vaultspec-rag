---
tags:
  - '#audit'
  - '#platform-backend-selection'
date: '2026-09-01'
modified: '2026-09-01'
body_schema: 'body-v1'
body_hash: 'sha256:494dcf38834d5e3f2785f1610c9022b79f94706edd725d839ce8d876b7928c21'
related:
  - "[[2026-08-28-platform-backend-selection-adr]]"
  - "[[2026-09-01-platform-backend-selection-plan]]"
---

# `platform-backend-selection` audit: MPS production support

## Scope

Audited the accepted accelerator decision, its implementation across core compute and operator surfaces, the dedicated Apple-silicon acceptance lane, documentation, and regression evidence for issue 400.

## Findings

### benchmark-mps-reporting | medium | The public benchmark result still reports Apple MPS as unavailable CUDA

`run_benchmark` derived `gpu` and `vram_mib` exclusively from `torch.cuda`. A benchmark that successfully executed through MPS therefore returned `gpu: "N/A"` and `vram_mib: 0.0`, preserving the false zero-VRAM claim the accepted decision prohibited.

### mps-fallback-cli-diagnosis | medium | CLI diagnosis can approve or misdiagnose an MPS environment whose CPU fallback is enabled

`_active_torch_diagnosis` classified any available MPS device as working without applying the canonical `PYTORCH_ENABLE_MPS_FALLBACK` refusal. Install could emit no warning even though compute would be rejected, while generic Darwin error handling could claim no Metal accelerator was detected instead of naming enabled CPU fallback.

### unavailable-status-label | low | Human status presents an unsupported CPU as the active compute choice

When neither supported backend resolved, `_render_status_text` rendered `Compute: CPU only (no supported GPU detected)`. CPU is deliberately never a candidate, so this could suggest a valid slower execution mode rather than accelerator unavailability.

### mps-device-load-reading | medium | The canonical device-load observation still evaluates CUDA on an MPS service

`device_load_reading` called `evaluate_device_admission` without the resolved backend, so its default CUDA probe reported `reason: "no_cuda"` on an admitted MPS host. Service health and job evidence could therefore contradict the selected backend.

### mps-acceptance-device-proof | high | The real-model guard can pass while the models execute on CPU

`test_configured_model_stack_runs_together_on_mps` asserted resolver and wrapper metadata but did not inspect the dense, sparse, or reranker modules' actual parameter devices. CPU fallback refusal does not prevent a constructor regression from leaving a model entirely on CPU.

### mps-publication-gate | high | The required Apple-silicon result runs only after publication or by manual dispatch

The `tests-macos` job was selected only for a published release or explicit workflow dispatch. It did not run for pushes to `main`, so MPS support could merge and be advertised without the required real-model check running before publication.

### macos-install-prompt-guidance | medium | The introductory guides incorrectly imply macOS skips torch configuration

The getting-started guide and README implied only Linux and Windows received the managed torch source step. The implementation still prompts and writes the managed entry on macOS; its CUDA source marker is merely inactive there.

## Recommendations

- Resolved `benchmark-mps-reporting`: results expose backend and memory kind, report MPS unified-memory allocation, and leave CUDA VRAM undefined rather than inventing zero. The guard was mutation-proven.
- Resolved `mps-fallback-cli-diagnosis`: install diagnostics invoke the canonical resolver, and fallback refusal is named before generic Darwin diagnosis. Focused CLI guards were mutation-proven.
- Resolved `unavailable-status-label`: status reports that neither CUDA nor MPS is available and that CPU is unsupported. The wording guard was mutation-proven.
- Resolved `mps-device-load-reading`: the production observation resolves the active backend before admission evaluation. Its MPS routing guard was mutation-proven.
- Resolved `mps-acceptance-device-proof`: the real-model guard checks all three models' parameters for actual MPS placement before forwards. Marker protection was mutation-proven.
- Resolved `mps-publication-gate`: the blocking macOS job runs on pushes to `main` before publication, as well as release and manual paths. Its guard was mutation-proven and actionlint passes.
- Resolved `macos-install-prompt-guidance`: primary guidance now describes the macOS prompt and inactive platform marker accurately.

## Validation disposition

All feature-focused tests and static gates pass. The integrated feature suite reports 402 passed and 44 deselected; focused reviewer suites report 184 core, 173 operator, and 39 CI/marker tests passing. Ruff, ty, actionlint, Markdown formatting, diff hygiene, MPS collect-only selection, and unsupported-host refusal pass. The complete ordinary Python lane reached 4300 passed and 2 skipped; five reproducible terminal/progress tests in untouched areas remain environment-sensitive, while one transient model-setup failure passed on rerun.

The provisioned Apple-silicon host earlier ran the three-model stack co-resident on MPS with CPU fallback disabled and bounded unified-memory use. Because it reported battery power during final validation, the heavy integrated guard was not rerun; the blocking self-hosted main-push gate remains the authoritative exact-code verdict when the runner is AC-powered.

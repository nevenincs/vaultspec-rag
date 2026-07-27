---
tags:
  - '#audit'
  - '#gpu-rag-stack'
date: '2026-03-06'
modified: '2026-07-27'
---

# Audit: CLI and API Facade

## Scope

Provenance gap: the manifest locator for this record is `intro_commit=none; template_commit=none`, and its original body has no separately labelled scope section. This scope is limited to the retained audit content in Findings.

## Findings

Feature: cli.py Typer CLI, api.py engine singleton

### 2026-03-06 -- Review (Passes 9-26)

### cli.py: GPU Status Display Updated

Lines 194-201: Status command now uses `torch.cuda` to detect GPU and display device info. Correctly shows GPU name and VRAM.

### cli.py Previous Issues (ALL RESOLVED)

- Task #22 \[CRITICAL\]: Imported removed `get_device_info()` -- CLI crashed on import. FIXED.
- Task #14 \[MEDIUM\]: Passed unsupported `model_name` kwarg to `EmbeddingModel()`. FIXED.

### cli.py Open Issues

- Task #50 \[LOW\]: cli.py:126-128 `overrides` dict built but never used in `handle_index`. Dead code.

### api.py: CLEAN

Engine singleton pattern with `get_engine()` / `reset_engine()`. Delegates to EmbeddingModel, VaultStore, VaultIndexer. No GPU-specific code.

### workspace.py: CLEAN (Pass 26)

Workspace layout resolution with git worktree detection, UNC path stripping, `.gt` container support. No GPU-specific code. Well-structured with frozen dataclasses.

### logging_config.py: CLEAN (Pass 26)

RichHandler-based logging with singleton console, `VAULTSPEC_RAG_LOG_LEVEL` env var support. No issues.

## Recommendations

Provenance gap: the manifest locator for this record is `intro_commit=none; template_commit=none`, and its original body has no separately labelled recommendations section. Any recommendation context remains only in the retained findings.

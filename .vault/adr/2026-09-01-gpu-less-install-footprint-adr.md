---
tags:
  - '#adr'
  - '#gpu-less-install-footprint'
date: '2026-09-01'
modified: '2026-09-01'
body_schema: 'body-v1'
body_hash: 'sha256:aee2cd1496adcbe412cfcfe7dea31b21e0f7238051605e9cf01c463e1081bc86'
related:
  - "[[2026-09-01-gpu-less-install-footprint-research]]"
  - "[[2026-09-01-platform-backend-selection-reference]]"
---

# `gpu-less-install-footprint` adr: `publish a thin base and provision CUDA explicitly` | (**status:** `accepted`)

## Problem Statement

Published installation currently acquires an unusable CUDA stack on Linux hosts without an NVIDIA GPU. The package needs a footprint boundary that preserves the existing GPU-only compute contract. `2026-09-01-gpu-less-install-footprint-research` and `2026-09-01-platform-backend-selection-reference` establish the package and runtime constraints.

## Considerations

- A base package must support its control-plane and service-client surfaces without local inference dependencies.
- The compute path must continue to fail loudly when CUDA dependencies or a CUDA device are absent.
- Published package metadata cannot rely on workspace-only source routing to select an accelerator wheel.
- A regression guard must exercise built published metadata and a Linux resolver rather than merely inspect configuration source.

## Considered options

**Keep inference dependencies in the base package.** Rejected because it retains the reported Linux CUDA resolution.

**Default to CPU inference and add a CUDA extra.** Rejected because CPU inference violates the project contract and a published extra cannot reliably select the required accelerator index.

**Publish platform and ABI-specific direct wheel variants.** Rejected because it adds a maintained wheel matrix without enabling supported CPU inference.

**Publish a thin base and explicitly provision CUDA (chosen).** The package base contains no local inference stack; the existing provisioner installs the pinned CUDA stack only where local GPU computation is requested.

## Constraints

The established CUDA runtime gate remains authoritative: CPU inference is not a fallback. The new boundary must include every dependency that independently imports or requires torch. Existing package users need actionable remediation when an operation requires provisioning. The accepted GPU-only stack remains stable and is not superseded by this record.

## Implementation

Move the complete local inference dependency set out of published base metadata into an explicit compute dependency group or extra used by development and GPU-capable installations. Keep the installer as the owner of CUDA source configuration and synchronization. Update missing-dependency remediation, installer and package metadata guards, acquisition coverage, and installation documentation so storage selection and dependency selection are never conflated.

## Rationale

This choice is the only option grounded by `2026-09-01-gpu-less-install-footprint-research` that makes a normal GPU-less install light without advertising a runtime the product refuses. It uses the lazy import and existing provisioning seams recorded in `2026-09-01-platform-backend-selection-reference` instead of adding a second inference implementation.

## Consequences

A plain install becomes substantially smaller and can run non-compute commands. Local indexing and search require an explicit GPU provisioning step and still fail on a host without CUDA. Release validation gains a real published-metadata guard, and documentation must state the separate storage, dependency, model, and CUDA costs before a user chooses a setup.

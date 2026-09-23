"""Typed operator-facing state: one vocabulary per concept, rendered everywhere.

Every verdict an operator reads - what this installation is, whether it can
run inference, what the service is doing, which optional features are active -
is a member of an enum defined here, and each enum owns its human label and
remediation. The service authors the verdicts about itself; the service client
composes lifecycle from discovery facts; the CLI and MCP only render. Nothing
in this package imports torch, so every service-control path can use it.

Import each name from the module that defines it; this package exports nothing
itself.
"""

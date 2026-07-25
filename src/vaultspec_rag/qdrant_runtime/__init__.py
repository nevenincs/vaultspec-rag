"""Qdrant server runtime: pinning, provisioning, and supervision.

This package owns everything needed to run the real Rust qdrant
server as a supervised child of the resident service: the committed
version/digest pin (``_constants``), platform asset mapping and
binary resolution (``_resolve``), download-on-first-use provisioning
(``_provision``), and child-process supervision with readiness
polling and the Windows kill-on-close Job Object (``_supervise``).

Stdlib-only by design: the CLI imports this package at startup, so it
must never pull torch, qdrant-client, or any other heavy dependency.


Import each name from the module that defines it; this package exports
nothing itself.
"""

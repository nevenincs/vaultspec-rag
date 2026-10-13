"""Shared machinery for fetching, verifying and running a native executable.

The service runs more than one native program it does not build in Python:
the vector server and the compiled monitor. Both reach a host the same way -
an archive pinned by digest, fetched over a host-pinned HTTPS transport,
verified before anything is unpacked, staged, verified again, and only then
installed into a versioned directory this package's owner manages. Both are
hashed once more, while the file is held, immediately before a process is
created from them.

That sequence is the security boundary, so it exists once. This package owns
the parts that say nothing about which program is being installed: the
transport (``_download``), the hold that ties a digest check to the process
created from the file (``_hold``), and the digest, staging and extraction
primitives (``_install``). What is being installed, where it is published,
which digest authorises it and what an operator is told about a failure
belong to the program's own runtime package.

Stdlib-only, and importable in an interpreter with no service configuration:
the release tooling installs its own pinned artifacts through these same
primitives.

Import each name from the module that defines it; this package exports
nothing itself.
"""

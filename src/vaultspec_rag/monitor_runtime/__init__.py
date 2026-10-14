"""Obtaining, trusting and locating the compiled monitor executable.

The monitor is a native executable built from this repository's own source
and shipped with the release that carries this package. It is not part of the
Python environment, so an installation has to obtain it, and it is a program
this package executes, so an installation has to be able to prove what it is
about to run.

Both answers come from digests the release pipeline generates into this
package: the archive's and the executable's, one pair per target triple
(``_pins``). Those digests are never fetched, never configured, and never
read from anywhere but inside the installed package, so what may run is
decided by the same artifact that does the deciding. ``_assets`` names the
archive and the executable a target's digests belong to, and the release
tooling reads those names from here rather than spelling them again.

Stdlib-only: the service client and the command line reach this without
loading the inference stack.

Import each name from the module that defines it; this package exports
nothing itself.
"""

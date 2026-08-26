---
tags:
  - '#adr'
  - '#mcp-read-only-mode'
date: '2026-08-26'
modified: '2026-08-26'
body_schema: 'body-v1'
body_hash: 'sha256:555c8b4de671f8487af5f5f3461a96a6884db072d24bb511f4ba25fd7e77e87f'
related:
  - "[[2026-08-26-mcp-read-only-mode-research]]"
---

# `mcp-read-only-mode` adr: `how the read-only tool surface is decided` | (**status:** `accepted`)

## Problem Statement

An autonomous agent that composes this MCP server is handed the schemas of six
tools it must never call: two destructive (`clean_all`, `clean_documents`) and
four expensive process management (the four `reindex_*`). All six act on the
machine-wide shared index. The consumer already allowlists what it permits, but
that does not change what the server advertises, and a destructive schema the
model can see is one bad inference from being called.

The surface must therefore be decided by the server at launch, and the tools
must be **absent from the listing** rather than present-and-refusing.

## Considerations

Registration is a side effect of importing `mcp/_tools.py`: each tool binds
through an `@mcp.tool()` decorator evaluated at import, against the single
shared server instance. Nothing consults a registry afterwards that a flag
could filter at call time. By the time any call arrives, the tool is already
advertised.

So the flag has to act on registration itself, and there are only two moments
available: before the decorators run, or after.

## Considered options

**Register conditionally.** Have the decorators consult the flag as they bind,
so a mutating tool is never registered under read-only. This requires the flag
to be readable at import time, which means module-level state established
before the import - process-global configuration that every importer inherits,
including test collection. It also splits the tool list across a condition,
so the served surface is no longer readable in one place.

**Register everything, then remove.** Let the decorators bind unconditionally
as they do now, and have the launch path remove the mutating tools before the
server serves. The server exposes `remove_tool`, and removal genuinely clears
the advertised listing.

**Refuse at call time.** Rejected against the requirement: the schema stays
visible, which is the specific failure the request exists to prevent.

## Constraints

- The omitted tools must not appear in `list_tools()`, not merely fail.
- Default launch behaviour must be unchanged; operator and CI use of
  `reindex_*` and `clean_*` is unaffected.
- The flag is an interface, not a version. Consumers assert the served surface
  at runtime rather than pinning a release, so its name and its served set are
  a stable contract.
- A newly added mutating tool must not silently appear under the flag.

## Implementation

Register everything, then remove - and derive which to remove rather than
listing them.

Every tool already declares its class through the annotations it is registered
with: a read-only hint that is true for the search and read tools, and false
for the refresh and clean ones. That declaration already partitions the surface
exactly as this decision requires, so the launch path removes each registered
tool whose read-only hint is not true, and names none of them.

The launch path parses the flag alongside the arguments the entry point already
handles, and performs that removal before the server serves.

The existing surface test is extended to assert the flag's listing, including
that no tool outside the read-only set survives it - which is what catches a
mutating tool added later without consideration.

## Rationale

Removal was verified against the real server rather than assumed: with the
tools module imported, twelve tools register; removing one yields eleven, the
removed tool is absent from `list_tools()`, and the search tools are
untouched. That is exactly the "absent, not refusing" requirement, demonstrated
rather than argued.

Conditional registration was rejected on testability. It needs the flag decided
before import, so exercising both surfaces in one interpreter is not possible -
the test would have to spawn a subprocess per surface, or mutate global state
before an import, and neither reads as evidence of what a launched server
actually serves. Removal leaves both surfaces constructible in-process from the
same registered set, so the guard can assert the real thing.

It also keeps one list of tools. A condition threaded through the decorators
would make the served surface a property of scattered branches, and the
constraint that a new mutating tool must not slip in is much harder to assert
against a surface nobody can read in one place.

A named read-only collection was the first shape considered here and was
rejected on inspection of what the tree already carries. Every tool is already
registered with an annotation declaring whether it is read-only, and that
existing declaration partitions the twelve registered tools into exactly the
six this request wants served and the six it wants omitted. A second list would
restate a classification the code already makes, and two statements of one fact
drift: a tool could be annotated read-only and omitted from the list, or the
reverse, and nothing would object. Deriving the surface from the annotation
leaves one place where a tool's class is declared.

## Consequences

The mutating tools are constructed and then discarded under the flag. That cost
is paid once at launch and buys the in-process testability above.

The read-only hint becomes load-bearing rather than advisory. A tool added
without one, or with the wrong one, is served or withheld accordingly - so the
annotation is now a security-relevant declaration and not just protocol
metadata. The surface test is what makes a mistake there a caught omission
rather than a silent one, so it must assert the whole set rather than a sample.

Because the flag is a contract rather than a version, renaming it or changing
what it serves is a breaking change for consumers that assert the surface at
runtime.

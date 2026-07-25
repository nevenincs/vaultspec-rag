"""Import-light service-client surface shared by the CLI and the MCP.

This package houses the production-proven HTTP wire client and the service
discovery helpers, factored out so both the CLI fast path and the MCP stdio
shell consume one surface without loading Torch, the models, or the store.
Importing it pulls only stdlib plus the lightweight filter validator; it is
the "CLI -> service is the only proven production path" client layer.

Import each name from the module that defines it - :mod:`._discovery` for
service discovery, :mod:`._transport` for the wire client. This package
exports nothing itself.
"""

"""The shared MCP server instance.

The release string is advertised so every result carries a meaningful
``serverInfo``; the protocol asks a server to identify itself on each
response, and an unset version leaves clients unable to tell which build
answered them. It resolves through the same accessor the daemon stamps into
what it publishes, so the MCP surface and the service can never report two
different versions for one install.
"""

from mcp.server.mcpserver import MCPServer

from ..serviceclient._compat import local_package_version

mcp = MCPServer("VaultSpec Search", version=local_package_version())

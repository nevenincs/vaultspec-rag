# vaultspec-rag documentation

vaultspec-rag is a command-line search tool for your project's documentation
and source code. Ask a question in plain English, get back the most relevant
files, ranked.

These docs are organized around what you want to do:

## Start here

- **[First search in five minutes](tutorial/first-search.md)** - A guided
  walkthrough. You install the tool, point it at a project, run your first
  search, and read the results. No prior knowledge assumed beyond a working
  command line.

## How-to guides

Recipes for specific tasks. Each guide assumes you have vaultspec-rag
installed and have a specific task in mind.

- [Install and configure](how-to/install-and-configure.md) - Hardware
  requirements, the install command, and the one-time setup choices.
- [Run as a background service](how-to/run-as-a-service.md) - Start the
  service so commands return instantly instead of loading models each time.
- [Use with Claude Desktop, Claude Code, and other MCP clients](how-to/use-with-mcp-clients.md) -
  Wire vaultspec-rag into AI assistants that speak the Model Context
  Protocol.
- [Script with `--json` output](how-to/script-with-json.md) - Run searches
  from shell scripts or CI and parse the results programmatically.
- [Narrow results with path filters and category preferences](how-to/narrow-results.md) -
  Use `--include-path`, `--exclude-path`, `--dedup-locales`, and `--prefer`
  to cut through noise.

## Reference

Look up exact behavior. Organized by command surface.

- [CLI commands](reference/cli.md) - Every command, every flag, every
  exit code.
- [Configuration](reference/configuration.md) - All environment variables
  and CLI overrides.
- [MCP tools](reference/mcp-tools.md) - The eight tools the MCP server
  exposes and the parameters each accepts.
- [JSON envelope](reference/json-envelope.md) - The shape every `--json`
  invocation emits.
- [Glossary](reference/glossary.md) - Plain-English definitions of every
  term used in these docs.

## Explanation

Understand the design choices behind the tool.

- [Why semantic search?](explanation/why-semantic-search.md) - Why this
  tool exists when you already have grep.
- [How it works](explanation/how-it-works.md) - The pieces that make a
  search query land on a ranked list of files.
- [Ad-hoc vs service mode](explanation/ad-hoc-vs-service.md) - Two ways
  to run the tool, and when to pick each.
- [Why a GPU is required](explanation/why-gpu.md) - The hardware
  prerequisite and the reasoning behind it.

## Support and help

- Report a bug or request a feature on
  [GitHub Issues](https://github.com/wgergely/vaultspec-rag/issues).
  Include your vaultspec-rag version, operating system, GPU name, the
  exact command you ran, and the full stderr output.
- Hit an unfamiliar term in any of these docs? Check the
  [Glossary](reference/glossary.md) first.

## What this tool isn't

vaultspec-rag is not a chat interface, not a code generator, not a
documentation writer. It indexes the files you already have and helps you
find the right ones. The output is a list of locations with short
excerpts; you read the actual files yourself.

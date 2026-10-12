# Search, ranking and availability: evidence group s1-0016

Read this part when working with: [scripts/render_readme_assets.py](../../../../scripts/render_readme_assets.py).

This is static evidence. Implementation observations, documentation claims, and test expectations remain distinct; no tests were run. An imported dependency uninspected within this evidence group may be covered in another capability reference. All listed full-file ranges are covered; report-local dependency boundaries are not inventory gaps.

[Search, ranking and availability](search-retrieval.md) provides module summaries, connections, and reconciled limitations.

## Capability summary

- [scripts/render_readme_assets.py](../../../../scripts/render_readme_assets.py) is a standalone README-asset generator. It runs three real `vaultspec-rag` CLI commands, captures their ANSI-colored stdout, and renders each capture into a framed terminal SVG (lines 2–16, 135–153, 234–260). Its documentation says this requires the managed search server to be running and the index to be current (lines 14–16).
- Rendering uses a fixed 112-column terminal, a custom Rich terminal theme, and an SVG frame template with a title bar, clipping, and configurable geometry (lines 33–132, 200–227). It trims trailing blank lines, optionally truncates to a per-capture line limit with a dim ellipsis, converts ANSI text through Rich, exports SVG, writes UTF-8 with LF newlines, and prints a write notice (lines 156–198).
- The script's only local module/file responsibility in the assigned range is [scripts/render_readme_assets.py](../../../../scripts/render_readme_assets.py); no other project modules are shown or inspected.

## Interfaces and data flow

- Entry point: direct script execution calls `main()` (lines 259–260). `main()` accepts an optional first positional argument as the output directory; it defaults to `assets` (lines 234–236). There is no visible argument parser or directory-creation step.
- `main()` calls `run_rag()` for a vault ADR search (`--max-results 2`), a code search (`--max-results 1`), and `server doctor`; it passes each command's stdout, output filename, and title to `render_svg()` (lines 230–256).
- `run_rag(args)` invokes `uv run --no-sync vaultspec-rag` plus the provided arguments, captures UTF-8 stdout/stderr, sets `FORCE_COLOR=1` and `COLUMNS=112`, removes `NO_COLOR`, and applies a 180-second timeout. A nonzero exit prints a warning and stderr, then the function returns stdout (lines 135–153).
- `render_svg(ansi, out_path, title, max_lines)` transforms captured text and writes an SVG to `out_path`; it does not return a value (lines 156–198). `svg_frame(rows, columns, left, right)` supplies Rich's `code_format` by substituting dimensions, colors, font, and escaped title-bar strings into `SVG_FRAME` (lines 200–227).
- The three output names are `term-search-vault.svg`, `term-search-code.svg`, and `term-doctor.svg` under the selected output directory (lines 237–255). No persistent state is written by the visible implementation other than those SVG files; the invoked CLI may use external state, which was not inspected.

## Boundaries and dependencies

- Local relationships visible in this file: `main()` composes `run_rag()`, `render_svg()`, and `svg_frame()`; no other local project file is referenced in the assigned source (lines 135–153, 156–227, 234–260).
- Direct external dependencies include Python standard-library modules (`io`, `os`, `re`, `subprocess`, `sys`, `html.escape`, `string.Template`) and Rich's `Console`, `TerminalTheme`, and `Text` (lines 21–31). Their behavior beyond calls shown here is uninspected.
- Runtime integrations are the `uv` command and `vaultspec-rag` CLI, plus the repository's managed search server/index described by the module docstring (lines 4–16, 140–147, 237–255). Their implementation and operational requirements are uninspected.

## Evidence

- | Claim | Project-relative file:line-range | Evidence type |
- | \--- | --- | --- |
- | The script is documented as regenerating README terminal renders and requiring a running managed server/current index. | [scripts/render_readme_assets.py:2-16](../../../../scripts/render_readme_assets.py#L2) | documentation claim |
- | `run_rag` configures color/width, invokes `uv run --no-sync vaultspec-rag`, captures output, warns on nonzero status, and returns stdout. | [scripts/render_readme_assets.py:135-153](../../../../scripts/render_readme_assets.py#L135) | implementation |
- | Rendering trims blank trailing lines, limits output if requested, appends an ellipsis on truncation, exports through Rich, and writes the SVG. | [scripts/render_readme_assets.py:156-198](../../../../scripts/render_readme_assets.py#L156) | implementation |
- | `main()` selects its output directory and assembles the two searches plus doctor capture with named SVG outputs and line limits. | [scripts/render_readme_assets.py:230-256](../../../../scripts/render_readme_assets.py#L230) | implementation |
- | Direct script invocation calls `main()`. | [scripts/render_readme_assets.py:259-260](../../../../scripts/render_readme_assets.py#L259) | implementation |
- | CLI results depend on the invoked command and repository search state. | [scripts/render_readme_assets.py:140-147, 237-255](../../../../scripts/render_readme_assets.py#L140) | inference from subprocess integration; command behavior not inspected |
- | No test modules or test expectations are present in the assigned file/range. | [scripts/render_readme_assets.py:1-260](../../../../scripts/render_readme_assets.py#L1) | test coverage unavailable in assigned source; no test claim made |

## Uncertainty and follow-up

- No gaps in the assigned range. To verify command semantics and the documented server/index prerequisites, inspect the `vaultspec-rag` CLI implementation and its server/search documentation in a separate task. To establish test expectations, inspect relevant tests separately. Those files were not assigned and were not read here.

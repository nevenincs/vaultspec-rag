set positional-arguments := false
set shell := ["bash", "-cu"]

default:
  @just --list

# ===========================================================================
#  prod  - pure 1:1 mirror of the vaultspec-rag Python CLI
#
#  just prod [args...]  →  uv run vaultspec-rag [args...]
#
#  Examples:
#    just prod index .
#    just prod search "query text"
#    just prod status
#    just prod server
# ===========================================================================

prod *args='':
  uv run vaultspec-rag {{args}}

# ===========================================================================
#  dev  - development toolchain (linters, formatters, tests, builds)
#
#  Nothing here exists in the shipped CLI.
#
#  Verbs:
#    deps      dependency management (sync, upgrade, lock)
#    lint      read-only static analysis (ruff, ty, taplo, markdownlint)
#    fix       auto-fix everything fixable (python, toml)
#    audit     supply-chain / security checks (pip-audit)
#    test      pytest
#    build     uv build
#    precommit pre-commit hook management (install, upgrade, run)
#
#  Examples:
#    just dev deps sync
#    just dev lint
#    just dev lint type
#    just dev fix
#    just dev fix python
#    just dev audit deps
#    just dev test python
#    just dev build python
# ===========================================================================

dev target *args='':
  case "{{target}}" in \
    deps) \
      just _dev-deps {{args}} ;; \
    lint) \
      just _dev-lint {{args}} ;; \
    fix) \
      just _dev-fix {{args}} ;; \
    audit) \
      just _dev-audit {{args}} ;; \
    test) \
      just _dev-test {{args}} ;; \
    build) \
      just _dev-build {{args}} ;; \
    precommit) \
      just _dev-precommit {{args}} ;; \
    *) \
      echo "unknown dev target: {{target}}" >&2; \
      echo "  targets: deps lint fix audit test build precommit" >&2; \
      exit 1 ;; \
  esac

# ===========================================================================
#  ci  - full pipeline: lint → vault check → test
# ===========================================================================

ci:
  just dev lint all && \
  just prod vault check all && \
  just dev test all

# ---------------------------------------------------------------------------
#  Internal recipes (prefixed with _ to hide from --list)
# ---------------------------------------------------------------------------

_dev-deps target='sync':
  case "{{target}}" in \
    sync) \
      uv sync --locked --group dev ;; \
    upgrade) \
      uv sync --upgrade --all-groups ;; \
    lock) \
      uv lock ;; \
    lock-upgrade) \
      uv lock --upgrade ;; \
    *) \
      echo "unknown dev deps target: {{target}}" >&2; \
      echo "  targets: sync upgrade lock lock-upgrade" >&2; \
      exit 1 ;; \
  esac

_dev-lint target='all':
  case "{{target}}" in \
    python) \
      uv run ruff check src ;; \
    format) \
      uv run ruff format --check src ;; \
    type) \
      uv run python -m ty check src/vaultspec_rag ;; \
    toml) \
      if command -v taplo >/dev/null 2>&1; then \
        taplo lint *.toml; \
      else \
        echo "taplo not found" >&2; \
        exit 127; \
      fi ;; \
    markdown) \
      if command -v npx >/dev/null 2>&1; then \
        npx --yes markdownlint-cli \
          --config .markdownlint.json \
          README.md .vault/; \
      else \
        echo "npx not found (install Node.js)" >&2; \
        exit 127; \
      fi ;; \
    all) \
      just _dev-lint python && \
      just _dev-lint format && \
      just _dev-lint type && \
      just _dev-lint toml && \
      just _dev-lint markdown ;; \
    *) \
      echo "unknown dev lint target: {{target}}" >&2; \
      echo "  targets: python format type toml markdown all" >&2; \
      exit 1 ;; \
  esac

_dev-fix target='all':
  case "{{target}}" in \
    python) \
      uv run ruff format src && \
      uv run ruff check --fix src ;; \
    toml) \
      if command -v taplo >/dev/null 2>&1; then \
        taplo fmt *.toml; \
      else \
        echo "taplo not found" >&2; \
        exit 127; \
      fi ;; \
    vault) \
      uv run vaultspec-core vault check all --fix ;; \
    all) \
      just _dev-fix python && \
      just _dev-fix toml && \
      just _dev-fix vault ;; \
    *) \
      echo "unknown dev fix target: {{target}}" >&2; \
      echo "  targets: python toml vault all" >&2; \
      exit 1 ;; \
  esac

_dev-audit target:
  case "{{target}}" in \
    deps) \
      tmp="${TMPDIR:-${TEMP:-/tmp}}/vaultspec-pip-audit-$$.txt"; \
      trap 'rm -f "$tmp"' EXIT; \
      uv export --frozen --group dev \
        --no-emit-project --output-file "$tmp"; \
      uv run pip-audit --strict -r "$tmp" ;; \
    *) \
      echo "unknown dev audit target: {{target}}" >&2; \
      echo "  targets: deps" >&2; \
      exit 1 ;; \
  esac

_dev-test target='all':
  case "{{target}}" in \
    python) \
      uv run pytest src/vaultspec_rag/tests/ \
        -x -q --tb=short -m unit ;; \
    all) \
      just _dev-test python ;; \
    *) \
      echo "unknown dev test target: {{target}}" >&2; \
      echo "  targets: python all" >&2; \
      exit 1 ;; \
  esac

_dev-build target:
  case "{{target}}" in \
    python) \
      uv build ;; \
    *) \
      echo "unknown dev build target: {{target}}" >&2; \
      echo "  targets: python" >&2; \
      exit 1 ;; \
  esac

_dev-precommit target='run':
  case "{{target}}" in \
    install) \
      uv run prek install ;; \
    upgrade) \
      uv run prek auto-update ;; \
    run) \
      uv run prek run --all-files ;; \
    *) \
      echo "unknown dev precommit target: {{target}}" >&2; \
      echo "  targets: install upgrade run" >&2; \
      exit 1 ;; \
  esac

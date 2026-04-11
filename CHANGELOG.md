# Changelog

## [0.2.0a0](https://github.com/wgergely/vaultspec-rag/compare/vaultspec-rag-v0.1.4...vaultspec-rag-v0.2.0a0) (2026-04-06)

First alpha release. This milestone collects all work since 0.1.1 into a single
pre-release suitable for early adopter testing.

### Service orchestration

- Service orchestration layer with multi-project routing ([#21](https://github.com/wgergely/vaultspec-rag/pull/21))
- Narrow GPU semaphore, shared CrossEncoder, per-root locks, multi-project watcher ([#30](https://github.com/wgergely/vaultspec-rag/pull/30))

### Dev tooling

- Full architecture alignment with vaultspec-core ([#26](https://github.com/wgergely/vaultspec-rag/pull/26))

### Documentation

- Documentation rewrite and MCP registration guide ([#27](https://github.com/wgergely/vaultspec-rag/pull/27))

### CLI polish

- pyproject metadata, `doctor` command, `--json` output, `__main__.py` entrypoint ([#29](https://github.com/wgergely/vaultspec-rag/pull/29))

### Test framework

- Test framework overhaul with centralized data paths and synthetic corpus ([#35](https://github.com/wgergely/vaultspec-rag/pull/35))

### .vaultragignore

- `.vaultragignore` support for codebase indexer ([#36](https://github.com/wgergely/vaultspec-rag/pull/36))

### Security hardening

- `project_root` validation and `/health` endpoint hardening ([#37](https://github.com/wgergely/vaultspec-rag/pull/37))

### Integration tests

- Service lifecycle integration tests with HTTP transport ([#38](https://github.com/wgergely/vaultspec-rag/pull/38))

______________________________________________________________________

## [0.1.4](https://github.com/wgergely/vaultspec-rag/compare/vaultspec-rag-v0.1.3...vaultspec-rag-v0.1.4) (2026-04-06)

### Features

- add .vaultragignore support for codebase indexer ([#31](https://github.com/wgergely/vaultspec-rag/issues/31)) ([a8f5e73](https://github.com/wgergely/vaultspec-rag/commit/a8f5e7344c2dd37cfcc7c0bb0dc8b807accc0544))
- centralize data paths under .vault/data/search-data/ + synthetic test corpus ([#32](https://github.com/wgergely/vaultspec-rag/issues/32), [#33](https://github.com/wgergely/vaultspec-rag/issues/33)) ([e9a90a6](https://github.com/wgergely/vaultspec-rag/commit/e9a90a624da92fdf2f09ddd65e022645b90ed2a9))
- implement SEC-001–SEC-004 security hardening ([118f90c](https://github.com/wgergely/vaultspec-rag/commit/118f90cec7dc5df6ad179cb28a1f85288233a0bb))
- narrow GPU semaphore + multi-project watcher ([#22](https://github.com/wgergely/vaultspec-rag/issues/22), [#23](https://github.com/wgergely/vaultspec-rag/issues/23)) ([47b1657](https://github.com/wgergely/vaultspec-rag/commit/47b1657d65678c838778bc278c727824a450b79d))

### Bug Fixes

- add related links to research doc (fixes vault dangling check) ([0fbfd99](https://github.com/wgergely/vaultspec-rag/commit/0fbfd995b34d33496ec6f4f7c9001130a6b6302a))
- address code review findings — watcher lifecycle, shutdown race, lock scope ([8ec521d](https://github.com/wgergely/vaultspec-rag/commit/8ec521d96fad644d8530e19852e0a01570e9f392))
- exclude .vaultspec/rules/skills/ from lychee link checker ([450c825](https://github.com/wgergely/vaultspec-rag/commit/450c8257c8b6567a7caf2c6c6d6185ec6c996430))
- MCP HTTP transport session manager never initialized ([b41f6f6](https://github.com/wgergely/vaultspec-rag/commit/b41f6f667389a1491ce629e06f7f7b59792e2a54))
- narrow GPU lock in indexers — hold only during encode, not full_index ([bdf9249](https://github.com/wgergely/vaultspec-rag/commit/bdf924953151a46fe2e6a88e62bf73f97b382196))
- regenerate uv.lock with UV_NO_SOURCES=1 for CI compatibility ([5b67abb](https://github.com/wgergely/vaultspec-rag/commit/5b67abb891f5818cdc23390685e6feb833bfedd0))
- remove .vault/\*.index.md from git (generated artifacts) ([effa0d8](https://github.com/wgergely/vaultspec-rag/commit/effa0d8f85c5341604a477af769a77cdd2ac0c6f))
- remove \[[wiki-links]\] from HTML comments in vault docs ([52c3624](https://github.com/wgergely/vaultspec-rag/commit/52c36244cc66cffc47f9c5fb2f4991e2e205ea91))
- resolve all vault audit errors for CI ([3ad9506](https://github.com/wgergely/vaultspec-rag/commit/3ad950646e539631eda15cd500e92cc93c06a07f))
- resolve CI failures — ty windll error and vault dangling links ([c2217d5](https://github.com/wgergely/vaultspec-rag/commit/c2217d5870591fde17f9f2a40d39baad6428b629))
- warmup tests need GPU (mark integration), pip-audit --frozen→--locked ([69d26fe](https://github.com/wgergely/vaultspec-rag/commit/69d26fee8c77dfbed8ec4d4189ecc22036794fda))

## [0.1.3](https://github.com/wgergely/vaultspec-rag/compare/vaultspec-rag-v0.1.2...vaultspec-rag-v0.1.3) (2026-04-03)

### Features

- complete architecture alignment with vaultspec-core ([80919f6](https://github.com/wgergely/vaultspec-rag/commit/80919f6f24fd2ba33838bf1cf54afd3a1d710a7d))

### Bug Fixes

- complete markdown pipeline alignment with core ([bb28d2a](https://github.com/wgergely/vaultspec-rag/commit/bb28d2a595a563b3a3da067edc667cbe6af243df))
- gitignore cleanup and vault-audit CI bug ([85c79ce](https://github.com/wgergely/vaultspec-rag/commit/85c79cecdda31ca406a8fae7d081e5f43de9e010))

## [0.1.2](https://github.com/wgergely/vaultspec-rag/compare/vaultspec-rag-v0.1.1...vaultspec-rag-v0.1.2) (2026-04-03)

### Features

- add service orchestration ADR, research, plan, and roadmap ([f1378dd](https://github.com/wgergely/vaultspec-rag/commit/f1378dd3e90f8146e243b37fd601fb44a5bc6a66))
- add ServiceRegistry for multi-project state management ([#18](https://github.com/wgergely/vaultspec-rag/issues/18)) ([ad151b4](https://github.com/wgergely/vaultspec-rag/commit/ad151b40d9cb7d1c4faccbe52816553906381f7f))
- FastMCP lifespan, Starlette /health, ServiceRegistry integration ([#19](https://github.com/wgergely/vaultspec-rag/issues/19)) ([d3d0905](https://github.com/wgergely/vaultspec-rag/commit/d3d09054d6baeeddd391bab4d7c2faa5d42a8a50))
- migrate legacy docs/ to .vault/ and remove docs/ ([af1ed87](https://github.com/wgergely/vaultspec-rag/commit/af1ed87fe36d07c46617da2dc9081adb5633ccfb))
- service daemon commands and model prefetch ([#16](https://github.com/wgergely/vaultspec-rag/issues/16), [#20](https://github.com/wgergely/vaultspec-rag/issues/20)) ([a052433](https://github.com/wgergely/vaultspec-rag/commit/a052433565b5fc130bf5863d45c9b5a7ccb80d8c))
- unify graph cache with lock+TTL and dependency injection ([#14](https://github.com/wgergely/vaultspec-rag/issues/14)) ([22db751](https://github.com/wgergely/vaultspec-rag/commit/22db751f9ade8b71468d6959c53b4b0fdfb33501))

### Bug Fixes

- resolve 1 CRITICAL + 10 HIGH audit findings ([4c16af5](https://github.com/wgergely/vaultspec-rag/commit/4c16af5b4ed085fd117f00ef1e15d6b6c6bce1f8))
- resolve MEDIUM audit findings — thread safety, error handling, tests ([a171637](https://github.com/wgergely/vaultspec-rag/commit/a171637b22207f2f3c18fb7f541d478ea574f9aa))
- resolve remaining LOW audit findings ([599b8fa](https://github.com/wgergely/vaultspec-rag/commit/599b8fad845d15c02e4a57dfe524383e84bf75ef))
- resolve remaining OPEN audit findings (batch 2) ([27dc976](https://github.com/wgergely/vaultspec-rag/commit/27dc9766b9496c5cf7fc7b66dfb14ce58ccbd035))

## [0.1.1](https://github.com/wgergely/vaultspec-rag/compare/vaultspec-rag-v0.1.0...vaultspec-rag-v0.1.1) (2026-04-01)

### Features

- add CI/CD pipeline and fix all 76 ty type errors ([1569a7f](https://github.com/wgergely/vaultspec-rag/commit/1569a7f1ebb9995022b7aedfd154d9cdba518bc0))
- add GPU CrossEncoder reranker as post-RRF step ([ff0569f](https://github.com/wgergely/vaultspec-rag/commit/ff0569f1c6591452cc8b81abf729f6622d553a85))
- add watcher support and expand RAG coverage ([df01b63](https://github.com/wgergely/vaultspec-rag/commit/df01b630c35aca3a0c004a9697cd173900883dc9))
- CI/CD pipeline and release automation ([9729abb](https://github.com/wgergely/vaultspec-rag/commit/9729abbd659487ad9d32016595e0b9efde0261ce))
- GPU-only RAG pipeline (Qwen3-Embedding-0.6B + SPLADE v3 + Qdrant) ([908e619](https://github.com/wgergely/vaultspec-rag/commit/908e6192d160a8704f25a0abfaa6e5e627c4440b))

### Bug Fixes

- add UV_NO_SOURCES to release and publish workflows ([7da1ded](https://github.com/wgergely/vaultspec-rag/commit/7da1ded68a505f2c369b496f493efa499583d4d6))
- add UV_NO_SOURCES to release-please and publish workflows ([0ef25ea](https://github.com/wgergely/vaultspec-rag/commit/0ef25ea0bf38411f0fffd0da3a07bc4242933201))
- CI uses UV_NO_SOURCES to bypass local dev overrides ([fdf1c9b](https://github.com/wgergely/vaultspec-rag/commit/fdf1c9bbe87d518c31fe1a0d1a5ef48e27ffd080))
- run CrossEncoder rerank before graph boost in search_vault() ([2e0952d](https://github.com/wgergely/vaultspec-rag/commit/2e0952dbdbdf204731f16f16ba4cd8b71a94d634))

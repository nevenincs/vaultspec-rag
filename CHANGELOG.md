# Changelog

## [0.1.2](https://github.com/wgergely/vaultspec-rag/compare/vaultspec-rag-v0.1.1...vaultspec-rag-v0.1.2) (2026-04-03)


### Features

* add service orchestration ADR, research, plan, and roadmap ([f1378dd](https://github.com/wgergely/vaultspec-rag/commit/f1378dd3e90f8146e243b37fd601fb44a5bc6a66))
* add ServiceRegistry for multi-project state management ([#18](https://github.com/wgergely/vaultspec-rag/issues/18)) ([ad151b4](https://github.com/wgergely/vaultspec-rag/commit/ad151b40d9cb7d1c4faccbe52816553906381f7f))
* FastMCP lifespan, Starlette /health, ServiceRegistry integration ([#19](https://github.com/wgergely/vaultspec-rag/issues/19)) ([d3d0905](https://github.com/wgergely/vaultspec-rag/commit/d3d09054d6baeeddd391bab4d7c2faa5d42a8a50))
* migrate legacy docs/ to .vault/ and remove docs/ ([af1ed87](https://github.com/wgergely/vaultspec-rag/commit/af1ed87fe36d07c46617da2dc9081adb5633ccfb))
* service daemon commands and model prefetch ([#16](https://github.com/wgergely/vaultspec-rag/issues/16), [#20](https://github.com/wgergely/vaultspec-rag/issues/20)) ([a052433](https://github.com/wgergely/vaultspec-rag/commit/a052433565b5fc130bf5863d45c9b5a7ccb80d8c))
* unify graph cache with lock+TTL and dependency injection ([#14](https://github.com/wgergely/vaultspec-rag/issues/14)) ([22db751](https://github.com/wgergely/vaultspec-rag/commit/22db751f9ade8b71468d6959c53b4b0fdfb33501))


### Bug Fixes

* resolve 1 CRITICAL + 10 HIGH audit findings ([4c16af5](https://github.com/wgergely/vaultspec-rag/commit/4c16af5b4ed085fd117f00ef1e15d6b6c6bce1f8))
* resolve MEDIUM audit findings — thread safety, error handling, tests ([a171637](https://github.com/wgergely/vaultspec-rag/commit/a171637b22207f2f3c18fb7f541d478ea574f9aa))
* resolve remaining LOW audit findings ([599b8fa](https://github.com/wgergely/vaultspec-rag/commit/599b8fad845d15c02e4a57dfe524383e84bf75ef))
* resolve remaining OPEN audit findings (batch 2) ([27dc976](https://github.com/wgergely/vaultspec-rag/commit/27dc9766b9496c5cf7fc7b66dfb14ce58ccbd035))

## [0.1.1](https://github.com/wgergely/vaultspec-rag/compare/vaultspec-rag-v0.1.0...vaultspec-rag-v0.1.1) (2026-04-01)


### Features

* add CI/CD pipeline and fix all 76 ty type errors ([1569a7f](https://github.com/wgergely/vaultspec-rag/commit/1569a7f1ebb9995022b7aedfd154d9cdba518bc0))
* add GPU CrossEncoder reranker as post-RRF step ([ff0569f](https://github.com/wgergely/vaultspec-rag/commit/ff0569f1c6591452cc8b81abf729f6622d553a85))
* add watcher support and expand RAG coverage ([df01b63](https://github.com/wgergely/vaultspec-rag/commit/df01b630c35aca3a0c004a9697cd173900883dc9))
* CI/CD pipeline and release automation ([9729abb](https://github.com/wgergely/vaultspec-rag/commit/9729abbd659487ad9d32016595e0b9efde0261ce))
* GPU-only RAG pipeline (Qwen3-Embedding-0.6B + SPLADE v3 + Qdrant) ([908e619](https://github.com/wgergely/vaultspec-rag/commit/908e6192d160a8704f25a0abfaa6e5e627c4440b))


### Bug Fixes

* add UV_NO_SOURCES to release and publish workflows ([7da1ded](https://github.com/wgergely/vaultspec-rag/commit/7da1ded68a505f2c369b496f493efa499583d4d6))
* add UV_NO_SOURCES to release-please and publish workflows ([0ef25ea](https://github.com/wgergely/vaultspec-rag/commit/0ef25ea0bf38411f0fffd0da3a07bc4242933201))
* CI uses UV_NO_SOURCES to bypass local dev overrides ([fdf1c9b](https://github.com/wgergely/vaultspec-rag/commit/fdf1c9bbe87d518c31fe1a0d1a5ef48e27ffd080))
* run CrossEncoder rerank before graph boost in search_vault() ([2e0952d](https://github.com/wgergely/vaultspec-rag/commit/2e0952dbdbdf204731f16f16ba4cd8b71a94d634))

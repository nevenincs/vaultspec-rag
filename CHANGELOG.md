# Changelog

## [0.2.7](https://github.com/wgergely/vaultspec-rag/compare/vaultspec-rag-v0.2.6...vaultspec-rag-v0.2.7) (2026-05-03)


### Bug Fixes

* **cli:** split rebuild from index clean ([af86b08](https://github.com/wgergely/vaultspec-rag/commit/af86b081e822f637f6988dd48dc91329baeb5160))
* **index:** keep vault docs out of code search ([1fffa8a](https://github.com/wgergely/vaultspec-rag/commit/1fffa8a389188d05e42354cee715e7576601f168))
* **install:** add direct torch dependency ([7ee10a3](https://github.com/wgergely/vaultspec-rag/commit/7ee10a34df4a476a513af903036d46ad35f7ec88))
* **install:** surface missing hf auth ([357fe88](https://github.com/wgergely/vaultspec-rag/commit/357fe881e01a58afb1d8212f62b9d7203efd4545))
* **runtime:** address embedding review findings ([931ba06](https://github.com/wgergely/vaultspec-rag/commit/931ba06f8f6af780eb83461fdd957719ac7bf31d))
* **runtime:** silence noisy local model warnings ([0de6346](https://github.com/wgergely/vaultspec-rag/commit/0de63461567d84ff003f62d970798a74c9392e50))

## [0.2.6](https://github.com/wgergely/vaultspec-rag/compare/vaultspec-rag-v0.2.5...vaultspec-rag-v0.2.6) (2026-04-28)

### Bug Fixes

- **deps:** bump vaultspec-core 0.1.14 → 0.1.16 (raises floor to `>=0.1.16`) to pick up the upstream fix for [vaultspec-core#85](https://github.com/wgergely/vaultspec-core/issues/85), which moves `yaml.add_representer(_LiteralStr, ...)` out of module top level into a lazy, lock-guarded `_ensure_literal_representer()`. Importing `vaultspec_core` (and therefore `vaultspec_rag`) no longer hard-crashes when PyYAML is partially broken — e.g. a venv with `yaml/__init__.py` deleted. Verified locally with the full unit suite (477 passed) and the actual fragility probe (CLI `--version` survives a deleted `yaml/__init__.py`) ([d5617a3](https://github.com/wgergely/vaultspec-rag/commit/d5617a3))

### Documentation

- **changelog:** drop the stale `## Unreleased` section that linked to a nonexistent PR #45; the work it described actually shipped in 0.2.1 via PRs #18 / #19 / #71 and was already credited there by release-please ([bb90689](https://github.com/wgergely/vaultspec-rag/commit/bb90689))

## [0.2.5](https://github.com/wgergely/vaultspec-rag/compare/vaultspec-rag-v0.2.4...vaultspec-rag-v0.2.5) (2026-04-27)

### Miscellaneous

- **uv:** drop the `pip-audit` dev dependency and route the CVE audit through the native `uv audit --locked --preview-features audit` command; CI job, justfile recipe, and pyproject pin comment updated accordingly ([5d69868](https://github.com/wgergely/vaultspec-rag/commit/5d69868))
- **uv:** replace every `uv pip install` recovery hint and post-publish smoke check with `uv sync` / `uvx --prerelease=allow` flows; rephrase fourteen vault-doc prose mentions to drop the legacy installer name ([476e510](https://github.com/wgergely/vaultspec-rag/commit/476e510))
- **vaultspec:** adopt the vaultspec-core 0.1.14 `providers.json` manifest format and add the `vaultspec-projectmanager` skill plus its agent persona and core MCP rule ([5c9c07f](https://github.com/wgergely/vaultspec-rag/commit/5c9c07f))

## [0.2.4](https://github.com/wgergely/vaultspec-rag/compare/vaultspec-rag-v0.2.3...vaultspec-rag-v0.2.4) (2026-04-25)

### Bug Fixes

- **deps:** pin tree-sitter-language-pack \<1.6.2 and drop project board workflow ([#85](https://github.com/wgergely/vaultspec-rag/issues/85)) ([e4f8229](https://github.com/wgergely/vaultspec-rag/commit/e4f8229aa13b0178dbdac170dd9563d93d432e25))
- **install:** close all PR-[#86](https://github.com/wgergely/vaultspec-rag/issues/86) deferred audit findings ([#89](https://github.com/wgergely/vaultspec-rag/issues/89)) ([#90](https://github.com/wgergely/vaultspec-rag/issues/90)) ([72c6196](https://github.com/wgergely/vaultspec-rag/commit/72c61962e1b2b220e473d18974d38f60d607c25d))
- **install:** handle scattered [tool.\*] pyprojects, real-world TOML edge cases, exit codes ([#83](https://github.com/wgergely/vaultspec-rag/issues/83), [#84](https://github.com/wgergely/vaultspec-rag/issues/84)) ([#86](https://github.com/wgergely/vaultspec-rag/issues/86)) ([0ca2aaf](https://github.com/wgergely/vaultspec-rag/commit/0ca2aafcf05ca6af554979c85b903d4afdee8329))

## [0.2.3](https://github.com/wgergely/vaultspec-rag/compare/vaultspec-rag-v0.2.2...vaultspec-rag-v0.2.3) (2026-04-22)

### Features

- **install:** configure cu130 torch and actionable CPU-torch errors ([#81](https://github.com/wgergely/vaultspec-rag/issues/81)) ([6e090f4](https://github.com/wgergely/vaultspec-rag/commit/6e090f474094ef272ebcd8a0748533cd5f9cce13))
- **install:** configure cu130 torch index and actionable CPU-torch errors ([971b75c](https://github.com/wgergely/vaultspec-rag/commit/971b75cd22dc2ac1aa3ec0e01b3e8dd41c1a7120))

### Bug Fixes

- **#68:** vault indexer memory + wall-clock — failure-safe streaming rebuild ([e3b6d84](https://github.com/wgergely/vaultspec-rag/commit/e3b6d848dd44fe7480a195b052bc4fddde4cbb27))
- **indexer:** iteration 10 polish — dead branch, type hints, docstrings ([7739f46](https://github.com/wgergely/vaultspec-rag/commit/7739f4608f4054feabe539ff920a3ddd99a2719a))
- **memory:** iteration 6 audit — concurrent reindex lock + observability ([1036085](https://github.com/wgergely/vaultspec-rag/commit/1036085f53825299f5e6fd9a2daaad76801278fc))
- **perf:** iteration 9 — env overrides, clean=True schema reset, broader except ([debeb02](https://github.com/wgergely/vaultspec-rag/commit/debeb02a505154d2b87a8a6f981784e9c9c577ce))
- **perf:** wall-clock — sort by length, smaller encode batch, max_seq cap ([0a7f22e](https://github.com/wgergely/vaultspec-rag/commit/0a7f22e033f682af0f82032c3a5cdafcc8f5b767))

## [0.2.2](https://github.com/wgergely/vaultspec-rag/compare/vaultspec-rag-v0.2.1...vaultspec-rag-v0.2.2) (2026-04-12)

### Bug Fixes

- **service:** roll back acquired ref_count if \_acquire raises mid-flight ([#77](https://github.com/wgergely/vaultspec-rag/issues/77)) ([8c83e37](https://github.com/wgergely/vaultspec-rag/commit/8c83e371554a16ea776427d0c39f3792cf864490))

## [0.2.1](https://github.com/wgergely/vaultspec-rag/compare/vaultspec-rag-v0.2.0...vaultspec-rag-v0.2.1) (2026-04-12)

### Features

- add .vaultragignore support for codebase indexer ([#31](https://github.com/wgergely/vaultspec-rag/issues/31)) ([a8f5e73](https://github.com/wgergely/vaultspec-rag/commit/a8f5e7344c2dd37cfcc7c0bb0dc8b807accc0544))
- add CI/CD pipeline and fix all 76 ty type errors ([1569a7f](https://github.com/wgergely/vaultspec-rag/commit/1569a7f1ebb9995022b7aedfd154d9cdba518bc0))
- add GPU CrossEncoder reranker as post-RRF step ([ff0569f](https://github.com/wgergely/vaultspec-rag/commit/ff0569f1c6591452cc8b81abf729f6622d553a85))
- add service orchestration ADR, research, plan, and roadmap ([f1378dd](https://github.com/wgergely/vaultspec-rag/commit/f1378dd3e90f8146e243b37fd601fb44a5bc6a66))
- add ServiceRegistry for multi-project state management ([#18](https://github.com/wgergely/vaultspec-rag/issues/18)) ([ad151b4](https://github.com/wgergely/vaultspec-rag/commit/ad151b40d9cb7d1c4faccbe52816553906381f7f))
- add vaultspec-rag.builtin.md rule + gitattributes eol=lf ([#54](https://github.com/wgergely/vaultspec-rag/issues/54), [#47](https://github.com/wgergely/vaultspec-rag/issues/47)) ([4d17df5](https://github.com/wgergely/vaultspec-rag/commit/4d17df51a2cc2bc4d2fd1503ad5e69615a9527fe))
- add watcher support and expand RAG coverage ([df01b63](https://github.com/wgergely/vaultspec-rag/commit/df01b630c35aca3a0c004a9697cd173900883dc9))
- align dev tooling with vaultspec-core conventions ([#9](https://github.com/wgergely/vaultspec-rag/issues/9), [#13](https://github.com/wgergely/vaultspec-rag/issues/13)) ([2334787](https://github.com/wgergely/vaultspec-rag/commit/23347871626a4164eb0f87cab5000c53dce44f9a))
- centralize data paths under .vault/data/search-data/ + synthetic test corpus ([#32](https://github.com/wgergely/vaultspec-rag/issues/32), [#33](https://github.com/wgergely/vaultspec-rag/issues/33)) ([e9a90a6](https://github.com/wgergely/vaultspec-rag/commit/e9a90a624da92fdf2f09ddd65e022645b90ed2a9))
- CI/CD pipeline and release automation ([9729abb](https://github.com/wgergely/vaultspec-rag/commit/9729abbd659487ad9d32016595e0b9efde0261ce))
- complete architecture alignment with vaultspec-core ([80919f6](https://github.com/wgergely/vaultspec-rag/commit/80919f6f24fd2ba33838bf1cf54afd3a1d710a7d))
- FastMCP lifespan, Starlette /health, ServiceRegistry integration ([#19](https://github.com/wgergely/vaultspec-rag/issues/19)) ([d3d0905](https://github.com/wgergely/vaultspec-rag/commit/d3d09054d6baeeddd391bab4d7c2faa5d42a8a50))
- GPU-only RAG pipeline (Qwen3-Embedding-0.6B + SPLADE v3 + Qdrant) ([908e619](https://github.com/wgergely/vaultspec-rag/commit/908e6192d160a8704f25a0abfaa6e5e627c4440b))
- granular per-document progress reporting for index command ([f86174c](https://github.com/wgergely/vaultspec-rag/commit/f86174cd91b66cd3b42e36b5d0ac9cd0d434f3c9))
- granular per-document progress reporting for index command ([f8e70dd](https://github.com/wgergely/vaultspec-rag/commit/f8e70dda4b35a5668bcba0392cfb5cba8bcfa28f)), closes [#62](https://github.com/wgergely/vaultspec-rag/issues/62)
- implement SEC-001–SEC-004 security hardening ([118f90c](https://github.com/wgergely/vaultspec-rag/commit/118f90cec7dc5df6ad179cb28a1f85288233a0bb))
- migrate legacy docs/ to .vault/ and remove docs/ ([af1ed87](https://github.com/wgergely/vaultspec-rag/commit/af1ed87fe36d07c46617da2dc9081adb5633ccfb))
- migrate pre-commit hooks + register MCP server ([#48](https://github.com/wgergely/vaultspec-rag/issues/48), [#55](https://github.com/wgergely/vaultspec-rag/issues/55)) ([570f715](https://github.com/wgergely/vaultspec-rag/commit/570f71562e50601c5b54d89ba15e7f647d2cfb63))
- narrow GPU semaphore + multi-project watcher ([#22](https://github.com/wgergely/vaultspec-rag/issues/22), [#23](https://github.com/wgergely/vaultspec-rag/issues/23)) ([47b1657](https://github.com/wgergely/vaultspec-rag/commit/47b1657d65678c838778bc278c727824a450b79d))
- service daemon commands and model prefetch ([#16](https://github.com/wgergely/vaultspec-rag/issues/16), [#20](https://github.com/wgergely/vaultspec-rag/issues/20)) ([a052433](https://github.com/wgergely/vaultspec-rag/commit/a052433565b5fc130bf5863d45c9b5a7ccb80d8c))
- store eviction (TTL + LRU) and log rotation for the RAG service ([#71](https://github.com/wgergely/vaultspec-rag/issues/71)) ([0eaf67f](https://github.com/wgergely/vaultspec-rag/commit/0eaf67ff17f563ca4c0cc28739821405af51061a))
- switch to Python-native markdown tooling, add lychee and actionlint ([595ee9f](https://github.com/wgergely/vaultspec-rag/commit/595ee9f333380cd66629a51c1bb5a901037c269d))
- unify graph cache with lock+TTL and dependency injection ([#14](https://github.com/wgergely/vaultspec-rag/issues/14)) ([22db751](https://github.com/wgergely/vaultspec-rag/commit/22db751f9ade8b71468d6959c53b4b0fdfb33501))
- vaultspec-rag install/uninstall — companion enrollment via core sync ([d215b40](https://github.com/wgergely/vaultspec-rag/commit/d215b40d8554599a9eafcf61142ab9b1248ecec0))
- vaultspec-rag install/uninstall — companion enrollment via core sync ([2aa1364](https://github.com/wgergely/vaultspec-rag/commit/2aa136447b2ca7fdee3290f0a4d0634d48c9ede2))

### Bug Fixes

- actionable error when another process holds the Qdrant lock ([d8d5c30](https://github.com/wgergely/vaultspec-rag/commit/d8d5c30d0bac21a243cb18bb641f60e1239c9e7e))
- add check-provider-artifacts hook + deep audit + plan update ([db8cb21](https://github.com/wgergely/vaultspec-rag/commit/db8cb2193d636825d01554b75b786e4814da5123))
- add related links to research doc (fixes vault dangling check) ([0fbfd99](https://github.com/wgergely/vaultspec-rag/commit/0fbfd995b34d33496ec6f4f7c9001130a6b6302a))
- add UV_NO_SOURCES to release and publish workflows ([7da1ded](https://github.com/wgergely/vaultspec-rag/commit/7da1ded68a505f2c369b496f493efa499583d4d6))
- add UV_NO_SOURCES to release-please and publish workflows ([0ef25ea](https://github.com/wgergely/vaultspec-rag/commit/0ef25ea0bf38411f0fffd0da3a07bc4242933201))
- address code review findings — watcher lifecycle, shutdown race, lock scope ([8ec521d](https://github.com/wgergely/vaultspec-rag/commit/8ec521d96fad644d8530e19852e0a01570e9f392))
- address code review findings for transport mode deconflation ([9943081](https://github.com/wgergely/vaultspec-rag/commit/99430812e6cc0e05396d15b412a76bef9e6e0244))
- address gemini review findings on progress reporter and indexer ([77a931e](https://github.com/wgergely/vaultspec-rag/commit/77a931e49c168a76c67b79e534f957ae92f7ac8a)), closes [#67](https://github.com/wgergely/vaultspec-rag/issues/67)
- align dev tooling with core after audit review ([b546d1b](https://github.com/wgergely/vaultspec-rag/commit/b546d1b73aae5483c11dd9e028f1bfeb2e35ef73))
- **build:** mirror companion-owned files into sdist force-include ([2d15305](https://github.com/wgergely/vaultspec-rag/commit/2d1530541af42e5a083b28c5801687114aac19f8))
- CI uses UV_NO_SOURCES to bypass local dev overrides ([fdf1c9b](https://github.com/wgergely/vaultspec-rag/commit/fdf1c9bbe87d518c31fe1a0d1a5ef48e27ffd080))
- complete markdown pipeline alignment with core ([bb28d2a](https://github.com/wgergely/vaultspec-rag/commit/bb28d2a595a563b3a3da067edc667cbe6af243df))
- correct builtin rule accuracy + review audit ([#54](https://github.com/wgergely/vaultspec-rag/issues/54)) ([7c76cb6](https://github.com/wgergely/vaultspec-rag/commit/7c76cb612760f02ed4172d86f2186538d1f4b840))
- deconflate MCP transport modes — make project_root required in HTTP service mode ([dd07edc](https://github.com/wgergely/vaultspec-rag/commit/dd07edcc51178f6ba075f10fc052cfe3a190c3b1))
- exclude .vaultspec/rules/skills/ from lychee link checker ([450c825](https://github.com/wgergely/vaultspec-rag/commit/450c8257c8b6567a7caf2c6c6d6185ec6c996430))
- exclude torch and vaultspec-core from pip-audit export ([e2a699b](https://github.com/wgergely/vaultspec-rag/commit/e2a699bceb33c38d729968befbaaa1344f9f71d8))
- exhaustive audit — watcher lifecycle, shutdown races, prompt/CLI fixes ([6a7e7ef](https://github.com/wgergely/vaultspec-rag/commit/6a7e7efa061371f4114ede07a8b68ed0b44bc894))
- gitignore cleanup and vault-audit CI bug ([85c79ce](https://github.com/wgergely/vaultspec-rag/commit/85c79cecdda31ca406a8fae7d081e5f43de9e010))
- harden transport mode deconflation ([992800b](https://github.com/wgergely/vaultspec-rag/commit/992800bba627947dc64c4385b44a8ec2bda7104f))
- **install:** security hardening — symlink rejection, partial-seed rollback, path containment ([feea637](https://github.com/wgergely/vaultspec-rag/commit/feea637e0aab1009d5196a500f22010723ee1f74))
- **install:** six review findings — global --target, uninstall self-bootstrap, partial-seed, onexc, ADR ([da2be36](https://github.com/wgergely/vaultspec-rag/commit/da2be36ba0fb5e308cfd48ce5017dab538626572))
- **install:** use core's atomic_write per ADR; drop redundant skip subtraction ([ff7361c](https://github.com/wgergely/vaultspec-rag/commit/ff7361c1db887bf0f0d81d258c3630a6eefa7618))
- make project_root required in HTTP service mode ([#56](https://github.com/wgergely/vaultspec-rag/issues/56)) ([945edbc](https://github.com/wgergely/vaultspec-rag/commit/945edbc9cea9315b8c9df7c182db56efde8961fd))
- MCP HTTP transport session manager never initialized ([b41f6f6](https://github.com/wgergely/vaultspec-rag/commit/b41f6f667389a1491ce629e06f7f7b59792e2a54))
- **mcp-server:** parse argv in main() so --help does not require a GPU ([3ccb066](https://github.com/wgergely/vaultspec-rag/commit/3ccb066bb6438e7f93ceaee3059df93044ea3902))
- narrow GPU lock in indexers — hold only during encode, not full_index ([bdf9249](https://github.com/wgergely/vaultspec-rag/commit/bdf924953151a46fe2e6a88e62bf73f97b382196))
- pass --no-hashes to uv export for pip-audit ([94d74ac](https://github.com/wgergely/vaultspec-rag/commit/94d74acd86f82c8f715e3118584b3f6c9a3b1ca8))
- publish vaultspec-rag to PyPI — fix release pipeline trigger and version manifest ([f6da869](https://github.com/wgergely/vaultspec-rag/commit/f6da869a6071ffee66efa44948ff1b6e9a134a5b))
- publish vaultspec-rag to PyPI — fix release pipeline trigger and version manifest ([19267a4](https://github.com/wgergely/vaultspec-rag/commit/19267a40eba4e32a7ab50f71c438766ba312ce1e)), closes [#65](https://github.com/wgergely/vaultspec-rag/issues/65)
- **rag:** address gemini round-2 review findings ([#73](https://github.com/wgergely/vaultspec-rag/issues/73)) ([80f9aa8](https://github.com/wgergely/vaultspec-rag/commit/80f9aa8d91e954dc1db34f8df82f11afd793ed40))
- **rag:** address gemini round-3 review findings ([#74](https://github.com/wgergely/vaultspec-rag/issues/74)) ([0f15ae4](https://github.com/wgergely/vaultspec-rag/commit/0f15ae42b122729c8221ba8557e8b5a07673cee6))
- regenerate uv.lock with UV_NO_SOURCES=1 for CI compatibility ([5b67abb](https://github.com/wgergely/vaultspec-rag/commit/5b67abb891f5818cdc23390685e6feb833bfedd0))
- remove .vault/\*.index.md from git (generated artifacts) ([effa0d8](https://github.com/wgergely/vaultspec-rag/commit/effa0d8f85c5341604a477af769a77cdd2ac0c6f))
- remove \[[wiki-links]\] from HTML comments in vault docs ([52c3624](https://github.com/wgergely/vaultspec-rag/commit/52c36244cc66cffc47f9c5fb2f4991e2e205ea91))
- remove editable vaultspec-core path from pyproject.toml + regenerate lock ([ca044c0](https://github.com/wgergely/vaultspec-rag/commit/ca044c0d16ea831cf9ec4a7f68a2334ab54ee0fe))
- resolve 1 CRITICAL + 10 HIGH audit findings ([4c16af5](https://github.com/wgergely/vaultspec-rag/commit/4c16af5b4ed085fd117f00ef1e15d6b6c6bce1f8))
- resolve all deferred audit items — zero remaining ([9214cdf](https://github.com/wgergely/vaultspec-rag/commit/9214cdf7c2dc87efeb0a6aece7311b84cb071207))
- resolve all vault audit errors for CI ([3ad9506](https://github.com/wgergely/vaultspec-rag/commit/3ad950646e539631eda15cd500e92cc93c06a07f))
- resolve CI failures — ty windll error and vault dangling links ([c2217d5](https://github.com/wgergely/vaultspec-rag/commit/c2217d5870591fde17f9f2a40d39baad6428b629))
- resolve MEDIUM audit findings — thread safety, error handling, tests ([a171637](https://github.com/wgergely/vaultspec-rag/commit/a171637b22207f2f3c18fb7f541d478ea574f9aa))
- resolve remaining LOW audit findings ([599b8fa](https://github.com/wgergely/vaultspec-rag/commit/599b8fad845d15c02e4a57dfe524383e84bf75ef))
- resolve remaining OPEN audit findings (batch 2) ([27dc976](https://github.com/wgergely/vaultspec-rag/commit/27dc9766b9496c5cf7fc7b66dfb14ce58ccbd035))
- resolve vaultspec-core from GitHub, remove UV_NO_SOURCES hack ([dd819f5](https://github.com/wgergely/vaultspec-rag/commit/dd819f564985b63705715787b4e83b5044f8949e))
- run CrossEncoder rerank before graph boost in search_vault() ([2e0952d](https://github.com/wgergely/vaultspec-rag/commit/2e0952dbdbdf204731f16f16ba4cd8b71a94d634))
- **service:** tear down popped victims if \_acquire raises mid-flight ([#75](https://github.com/wgergely/vaultspec-rag/issues/75)) ([9c87aed](https://github.com/wgergely/vaultspec-rag/commit/9c87aed027028c4f45296f6051f7560d23a363c5))
- **tests:** accept threading.RLock in ServiceRegistry lock regression ([#76](https://github.com/wgergely/vaultspec-rag/issues/76)) ([825d1c6](https://github.com/wgergely/vaultspec-rag/commit/825d1c65fad84b72e24e508db3a90bf6ef806756))
- warmup tests need GPU (mark integration), pip-audit --frozen→--locked ([69d26fe](https://github.com/wgergely/vaultspec-rag/commit/69d26fee8c77dfbed8ec4d4189ecc22036794fda))

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

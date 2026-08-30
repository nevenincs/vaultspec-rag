# Changelog

## [0.4.19](https://github.com/nevenincs/vaultspec-rag/compare/vaultspec-rag-v0.4.18...vaultspec-rag-v0.4.19) (2026-08-30)


### Features

* **binaries:** build linux-aarch64 in the pinned image, dropping its floor to 2.28 ([#431](https://github.com/nevenincs/vaultspec-rag/issues/431)) ([4061041](https://github.com/nevenincs/vaultspec-rag/commit/4061041f699ac4239fd14140add6ec34e0b1a5d2))

## [0.4.18](https://github.com/nevenincs/vaultspec-rag/compare/vaultspec-rag-v0.4.17...vaultspec-rag-v0.4.18) (2026-08-30)


### Bug Fixes

* **binaries:** derive the preflight selectors, and correct two misleading claims ([#427](https://github.com/nevenincs/vaultspec-rag/issues/427)) ([52a4c5e](https://github.com/nevenincs/vaultspec-rag/commit/52a4c5eeb0583cdd2221500e506a126c655c2c04))

## [0.4.17](https://github.com/nevenincs/vaultspec-rag/compare/vaultspec-rag-v0.4.16...vaultspec-rag-v0.4.17) (2026-08-30)


### Features

* **acquisition:** run the published binary somewhere older than the build host ([#429](https://github.com/nevenincs/vaultspec-rag/issues/429)) ([46cd2c6](https://github.com/nevenincs/vaultspec-rag/commit/46cd2c6559c8bf9cb7c0dd765fa435ee4584649f))


### Bug Fixes

* **binaries:** host the release guard, and give it the file it reads ([#424](https://github.com/nevenincs/vaultspec-rag/issues/424)) ([684367d](https://github.com/nevenincs/vaultspec-rag/commit/684367dd000a988154a9afd3a15fb106ef722470))
* **channels:** one channel root, a guard that watches it, and docs that name it ([#425](https://github.com/nevenincs/vaultspec-rag/issues/425)) ([7567a9e](https://github.com/nevenincs/vaultspec-rag/commit/7567a9e8d4c32623e179fa9ddff7b50cb0e3111f))

## [0.4.16](https://github.com/nevenincs/vaultspec-rag/compare/vaultspec-rag-v0.4.15...vaultspec-rag-v0.4.16) (2026-08-30)


### Bug Fixes

* **binaries:** return the containerised workspace to the runner's user ([#423](https://github.com/nevenincs/vaultspec-rag/issues/423)) ([2f8d02a](https://github.com/nevenincs/vaultspec-rag/commit/2f8d02ae2ec3ca356b30e78d3dfbec443229ad0f))
* **binaries:** the ARM64 runner cannot host a container; declare its real floor ([#420](https://github.com/nevenincs/vaultspec-rag/issues/420)) ([b0c0c00](https://github.com/nevenincs/vaultspec-rag/commit/b0c0c00243ffcd0df0add5319a9fde9d58741713))
* **binaries:** the guard must require every declared target, not any asset ([#422](https://github.com/nevenincs/vaultspec-rag/issues/422)) ([107ed2b](https://github.com/nevenincs/vaultspec-rag/commit/107ed2b53d628f93addb855deb27840c0a9a439b))

## [0.4.15](https://github.com/nevenincs/vaultspec-rag/compare/vaultspec-rag-v0.4.14...vaultspec-rag-v0.4.15) (2026-08-30)


### Bug Fixes

* **binaries:** build Linux in a pinned image, and refuse a floor violation ([#418](https://github.com/nevenincs/vaultspec-rag/issues/418)) ([a990c2a](https://github.com/nevenincs/vaultspec-rag/commit/a990c2a580475152b15533a61ae5ff4b697e151e))

## [0.4.14](https://github.com/nevenincs/vaultspec-rag/compare/vaultspec-rag-v0.4.13...vaultspec-rag-v0.4.14) (2026-08-30)


### Bug Fixes

* **release:** dispatch the binaries build, not only Publish ([#416](https://github.com/nevenincs/vaultspec-rag/issues/416)) ([a822684](https://github.com/nevenincs/vaultspec-rag/commit/a8226849e76829abbbf1c1a75f007c2675caaa8f))

## [0.4.13](https://github.com/nevenincs/vaultspec-rag/compare/vaultspec-rag-v0.4.12...vaultspec-rag-v0.4.13) (2026-08-30)


### Bug Fixes

* **binaries:** build on the tag, not only on a dispatch nobody remembers ([#414](https://github.com/nevenincs/vaultspec-rag/issues/414)) ([1fef476](https://github.com/nevenincs/vaultspec-rag/commit/1fef476b1da53ebf768f091955a1c6aa72523f19))

## [0.4.12](https://github.com/nevenincs/vaultspec-rag/compare/vaultspec-rag-v0.4.11...vaultspec-rag-v0.4.12) (2026-08-29)


### Features

* **binaries:** refuse to let an artifact-less release serve as latest ([#408](https://github.com/nevenincs/vaultspec-rag/issues/408)) ([f347f59](https://github.com/nevenincs/vaultspec-rag/commit/f347f59fe93fa19257ed7bd6678af4e8935fb441))
* **release:** publish channel pointers to the org distribution repo ([#405](https://github.com/nevenincs/vaultspec-rag/issues/405)) ([e698bfc](https://github.com/nevenincs/vaultspec-rag/commit/e698bfc052bbfa8efc9bbb89105a21b40f5dfb4f))


### Bug Fixes

* **release:** merge SHA256SUMS instead of clobbering it ([#410](https://github.com/nevenincs/vaultspec-rag/issues/410)) ([c83d584](https://github.com/nevenincs/vaultspec-rag/commit/c83d584f3d691be938f7c97e63d35afe5c1f98bb))

## [0.4.11](https://github.com/nevenincs/vaultspec-rag/compare/vaultspec-rag-v0.4.10...vaultspec-rag-v0.4.11) (2026-08-29)


### Features

* **binaries:** restore the linux-arm64 target now its host is available ([#402](https://github.com/nevenincs/vaultspec-rag/issues/402)) ([49fc86e](https://github.com/nevenincs/vaultspec-rag/commit/49fc86e25112cb2273bfb9b094d49a6f68f3ee15))

## [0.4.10](https://github.com/nevenincs/vaultspec-rag/compare/vaultspec-rag-v0.4.9...vaultspec-rag-v0.4.10) (2026-08-28)


### Bug Fixes

* **binaries:** stop gating every release on a laptop runner ([923fe9b](https://github.com/nevenincs/vaultspec-rag/commit/923fe9b17a7ebd0156874b2894084b7b72bf6295))
* **binaries:** stop gating every release on a laptop runner ([5a0153d](https://github.com/nevenincs/vaultspec-rag/commit/5a0153dbaeb4a3bba8b8ee479038a9c43fc3f852))

## [0.4.9](https://github.com/nevenincs/vaultspec-rag/compare/vaultspec-rag-v0.4.8...vaultspec-rag-v0.4.9) (2026-08-28)


### Features

* **binaries:** actually enable the linux-arm64 leg ([255965b](https://github.com/nevenincs/vaultspec-rag/commit/255965b42a556e52dfccf43cb8c69f2b08f1fb15))
* **binaries:** actually enable the linux-arm64 leg ([b951219](https://github.com/nevenincs/vaultspec-rag/commit/b951219815ecdaf734f6233619ed7b595b27d7d2))
* **binaries:** enable the linux-arm64 leg on a registered runner ([43c1644](https://github.com/nevenincs/vaultspec-rag/commit/43c1644702a4d7546af34e978ac5c6a6ef8fb021))


### Bug Fixes

* **binaries:** stage the channel pointers before asking if they changed ([053c825](https://github.com/nevenincs/vaultspec-rag/commit/053c8252d13cd07697e2d0c9010ee09ad34243e5))
* **binaries:** stage the channel pointers before asking if they changed ([df95832](https://github.com/nevenincs/vaultspec-rag/commit/df958329185550b9200a6b989eb5cc7568a560cd))
* **ci:** scope the bot identity to the commit instead of the checkout ([f12ad55](https://github.com/nevenincs/vaultspec-rag/commit/f12ad55a9d323bf04130eb7b3427d06649f626af))
* **ci:** scope the bot identity to the commit instead of the checkout ([534cbc7](https://github.com/nevenincs/vaultspec-rag/commit/534cbc74ca032bb3c59fbd890535e137b94d0d0e))

## [0.4.8](https://github.com/nevenincs/vaultspec-rag/compare/vaultspec-rag-v0.4.7...vaultspec-rag-v0.4.8) (2026-08-27)


### Bug Fixes

* **binaries:** invoke the builder as a module so it can find its package ([29512e7](https://github.com/nevenincs/vaultspec-rag/commit/29512e7dd8dbc8f166e5a06c6d2b02fb65df31ee))
* **binaries:** invoke the builder as a module so it can find its package ([f0d8345](https://github.com/nevenincs/vaultspec-rag/commit/f0d83455019fefde0da8d5580abf95bc17425d58))

## [0.4.7](https://github.com/nevenincs/vaultspec-rag/compare/vaultspec-rag-v0.4.6...vaultspec-rag-v0.4.7) (2026-08-27)


### Features

* **delivery:** add binary, scoop, and homebrew channels ([fb5a609](https://github.com/nevenincs/vaultspec-rag/commit/fb5a609494abe49bf33072bc6ab70917c29308aa))
* **delivery:** add binary, scoop, and homebrew channels ([fb833cf](https://github.com/nevenincs/vaultspec-rag/commit/fb833cf182896cc954c66cad284ef6f2e00ac348))


### Bug Fixes

* **delivery:** bootstrap the GPU torch build, and stop building macOS ([0a8105c](https://github.com/nevenincs/vaultspec-rag/commit/0a8105c29a7756efb2de6247d89b2c77382be1f1))
* **packaging:** point the product default at the product that exists ([b00a78e](https://github.com/nevenincs/vaultspec-rag/commit/b00a78e1875128354f24e82bffa2fd91047a99a2))

## [0.4.6](https://github.com/nevenincs/vaultspec-rag/compare/vaultspec-rag-v0.4.5...vaultspec-rag-v0.4.6) (2026-08-26)


### Bug Fixes

* **mcp:** list tools through the public API instead of the private manager ([f87d52b](https://github.com/nevenincs/vaultspec-rag/commit/f87d52b1f3c496cc7d2810795fc328e1f8d06f78))

## [0.4.5](https://github.com/nevenincs/vaultspec-rag/compare/vaultspec-rag-v0.4.4...vaultspec-rag-v0.4.5) (2026-08-26)


### Bug Fixes

* **service:** record a traceback when the daemon dies without unwinding ([d7b1c34](https://github.com/nevenincs/vaultspec-rag/commit/d7b1c3423030975c97a17d9054137a33ec45ccaa))
* **service:** record a traceback when the daemon dies without unwinding ([a775d78](https://github.com/nevenincs/vaultspec-rag/commit/a775d78cd27cf7e0df3552ce436145bbffd130a1))

## [0.4.4](https://github.com/nevenincs/vaultspec-rag/compare/vaultspec-rag-v0.4.3...vaultspec-rag-v0.4.4) (2026-08-26)


### Features

* **mcp:** serve only the read tools under a read-only launch flag ([10c4138](https://github.com/nevenincs/vaultspec-rag/commit/10c4138b4cfe8e643f0c60f6163a9e0dacefabec))
* **mcp:** serve only the read tools under a read-only launch flag ([80e9303](https://github.com/nevenincs/vaultspec-rag/commit/80e93034ac3e45c067dbdc6700db2345d8f35661))


### Bug Fixes

* **cli:** decode a search snippet's source with replacement ([aa04ea0](https://github.com/nevenincs/vaultspec-rag/commit/aa04ea0dd223fbd3e722845dd43ad2a2fd5b24cd))
* **cli:** decode a search snippet's source with replacement ([c3847a5](https://github.com/nevenincs/vaultspec-rag/commit/c3847a5d027e43f6d1140784027ffa1161176bdf))

## [0.4.3](https://github.com/nevenincs/vaultspec-rag/compare/vaultspec-rag-v0.4.2...vaultspec-rag-v0.4.3) (2026-08-25)


### Features

* **storage:** expose archive restore as an operator verb ([d6d98fc](https://github.com/nevenincs/vaultspec-rag/commit/d6d98fc13f4db6be117ced34b4e5a0ad86423f7a))


### Bug Fixes

* **gpu:** name the unreadable refusal where the loader's contract is stated ([6d0f898](https://github.com/nevenincs/vaultspec-rag/commit/6d0f8987197fe38505cb4e52919e013742518c23))
* **gpu:** refuse a device that is present but persistently unreadable ([e35a16f](https://github.com/nevenincs/vaultspec-rag/commit/e35a16fd517caa09f625c3da31d981578cd623c6))
* **indexer:** converge a deleted source instead of ending the run ([2555276](https://github.com/nevenincs/vaultspec-rag/commit/25552760a3697fe7b5432e262414c1c9d6021b2d))
* **indexer:** converge a deleted source instead of ending the run ([e2f0f33](https://github.com/nevenincs/vaultspec-rag/commit/e2f0f338f7a8531fe39dad4fda4e904287d78e03))
* **indexer:** keep separator runs whole so a chunk stays findable ([45c272f](https://github.com/nevenincs/vaultspec-rag/commit/45c272f187d1cf5cfc98b9708d0a654429c46fa4))
* **indexer:** keep separator runs whole so a chunk stays findable ([c831569](https://github.com/nevenincs/vaultspec-rag/commit/c831569d85929c58b6b871b49fe2786e56ccdf88))

## [0.4.2](https://github.com/nevenincs/vaultspec-rag/compare/vaultspec-rag-v0.4.1...vaultspec-rag-v0.4.2) (2026-08-14)


### Features

* **qdrant:** move the server pin to 1.19.0 and let the lock lead ([0d1bdda](https://github.com/nevenincs/vaultspec-rag/commit/0d1bdda6fe063c7ca49109cd27c651c6211e5592))


### Bug Fixes

* **anchor:** publish the owner witness without an unreadable window ([#343](https://github.com/nevenincs/vaultspec-rag/issues/343)) ([4cdae90](https://github.com/nevenincs/vaultspec-rag/commit/4cdae90ff4c4b0d8e64bab7349d0b1456ec0b017))
* **borrow:** read health identity on the evidence bound, not the poll bound ([1b686fa](https://github.com/nevenincs/vaultspec-rag/commit/1b686fa29d5ca04c7ced14d6e9ea96c01892b294))
* **cli,tests:** stop hardcoding the qdrant pin, and say why a borrow was refused ([c066f5d](https://github.com/nevenincs/vaultspec-rag/commit/c066f5d7a5e2ac11f2c8e13d737d5565ee52f396))
* **cli:** name a build mismatch instead of blaming borrower quiesce ([ea12a05](https://github.com/nevenincs/vaultspec-rag/commit/ea12a0578727f2669aa2383609fc6ecaf63de7a6))
* **deps:** cap qdrant-client to the pinned server's minor line ([a0120c6](https://github.com/nevenincs/vaultspec-rag/commit/a0120c6e0ab83086b848503ee54c549193bb383c))
* **indexer:** honour ledger contention where retries are actually decided ([4c1213b](https://github.com/nevenincs/vaultspec-rag/commit/4c1213ba095ece8845361be65ac3700a866a8ac5))
* **indexer:** make the shared run ledger safe under concurrent access ([48cabd1](https://github.com/nevenincs/vaultspec-rag/commit/48cabd156844abffc74a0b74eb98fdd36677c221))
* **indexer:** make the shared run ledger safe under concurrent access ([12e1db0](https://github.com/nevenincs/vaultspec-rag/commit/12e1db0a2928b29b4e727acecf7c956d940e3c77))
* **install:** translate provider paths against the resolved projection root ([#345](https://github.com/nevenincs/vaultspec-rag/issues/345)) ([39a3f2c](https://github.com/nevenincs/vaultspec-rag/commit/39a3f2c5e2b75144061062c0dadb55c236ca28d7))
* **jobs:** accept quiesce-parked work on reload ([c9f3e48](https://github.com/nevenincs/vaultspec-rag/commit/c9f3e4879aa65460a7d983d45c7e0dc6b94c87ec))
* **jobs:** give run telemetry a value space it can round-trip ([81c6646](https://github.com/nevenincs/vaultspec-rag/commit/81c6646842249d84d61a0c960f2d908c817c7fac))
* **jobs:** give unapplied-write ingest failures their remedy instead of 'other' ([586e356](https://github.com/nevenincs/vaultspec-rag/commit/586e3568c82595342085d62863fbc3b02a61c187))
* **jobs:** keep a backwards clock step from unreadable job state ([4780134](https://github.com/nevenincs/vaultspec-rag/commit/4780134a8066a5fbb652407171c134eff6ffd81f))
* **jobs:** keep a retained job's replay binding when restore exceeds the bound ([c99bfb8](https://github.com/nevenincs/vaultspec-rag/commit/c99bfb855f1ba28987b2f188e940346abda7c4a0))
* **jobs:** let a capacity cut cost admission, never the daemon's start ([96c2768](https://github.com/nevenincs/vaultspec-rag/commit/96c27686aa3ddbf99fe6a41c6c01d5898885effd))
* **jobs:** let paused work persist running intent ([2becb0f](https://github.com/nevenincs/vaultspec-rag/commit/2becb0f0609256ddc874d6ce94131d9a2feed016))
* **jobs:** quarantine an invalid state file instead of bricking startup ([8bbb6a3](https://github.com/nevenincs/vaultspec-rag/commit/8bbb6a377c8a224772417563e8bb87449b4ed7de))
* **jobs:** stop leaking state temporaries and widen the version contract ([e084f06](https://github.com/nevenincs/vaultspec-rag/commit/e084f06b9cefa7ffce9f714f680279ecaa201bde))
* **jobs:** stop reporting a newer build state file as corrupt ([e46da1e](https://github.com/nevenincs/vaultspec-rag/commit/e46da1e2c085d83f29acb185e97e3a0714956065))
* **jobs:** stop the daemon writing job state its own loader refuses ([3829a77](https://github.com/nevenincs/vaultspec-rag/commit/3829a772477534023ab286838824af22b6c59705))
* **jobs:** validate persisted job state where it is produced ([1687031](https://github.com/nevenincs/vaultspec-rag/commit/168703125e88f3a05fc81fd44453dd70143ed4e3))
* **quiesce:** let a borrower own only the pause it actually caused ([d29e260](https://github.com/nevenincs/vaultspec-rag/commit/d29e260294c04462f096b63d2549a672837e7a33))
* **quiesce:** read the ownership witness off the registry lock ([90d7cc0](https://github.com/nevenincs/vaultspec-rag/commit/90d7cc03605ae6de4cbcc9ad145e964a04fae22e))
* **serviceclient:** report a timed-out health probe as its own verdict ([#342](https://github.com/nevenincs/vaultspec-rag/issues/342)) ([2277a1b](https://github.com/nevenincs/vaultspec-rag/commit/2277a1b29ce1458b9a2ce7a796254aa9080784c3))
* **service:** give the pause drain a budget longer than one encode slice ([ab0a5b5](https://github.com/nevenincs/vaultspec-rag/commit/ab0a5b52e882b69e10862b9f4661da33a52bcdbc))
* **service:** say that a refused transition stopped the service serving ([7f29fc4](https://github.com/nevenincs/vaultspec-rag/commit/7f29fc4e387c036e514072614fd24625b9ee5537))
* **status:** report a held service as held, and stop dropping what it published ([a0711dc](https://github.com/nevenincs/vaultspec-rag/commit/a0711dc63718904501a030ff420154d0e9c0c813))
* **tests:** declare the refused-envelope literal the quiesce guards read ([309ce5b](https://github.com/nevenincs/vaultspec-rag/commit/309ce5be17601f4b827d81c23ed0720030a4c20f))
* **tests:** derive the published qdrant version from the pin ([299674e](https://github.com/nevenincs/vaultspec-rag/commit/299674ec61981d19d3746a624e5ffabb0edc35e8))
* **tests:** latch the rollover observation instead of re-reading it ([#344](https://github.com/nevenincs/vaultspec-rag/issues/344)) ([230d58c](https://github.com/nevenincs/vaultspec-rag/commit/230d58cd06c26e3b188d56828b2b187790b22e92))
* **tests:** let each watch suite declare its own tier, and clear the strict gate ([90a9e0a](https://github.com/nevenincs/vaultspec-rag/commit/90a9e0ad58f00846acc5a99da3793937030de07d))
* **tests:** read a stamp through the owned reader, not a fresh narrowing ([22c7371](https://github.com/nevenincs/vaultspec-rag/commit/22c7371be2d517d3e2c45ed96539072c7208adc9))
* **tests:** refuse a selection that holds both device tiers ([08e61cc](https://github.com/nevenincs/vaultspec-rag/commit/08e61cc7924b53e5d42612a6f66e7677d69d67e3))
* **tests:** repair the harness defects keeping the platform legs red ([#341](https://github.com/nevenincs/vaultspec-rag/issues/341)) ([b83b892](https://github.com/nevenincs/vaultspec-rag/commit/b83b8926c4844fa5861f6c1d371516edecdd2dd6))
* **tests:** stop co-scheduling subprocess-GPU tests with a resident-model tier ([391a201](https://github.com/nevenincs/vaultspec-rag/commit/391a20146dbbbf776c8791bbb92466f6c414ae40))
* **tests:** stop two job-state guards asserting timing they never owned ([#340](https://github.com/nevenincs/vaultspec-rag/issues/340)) ([34467d8](https://github.com/nevenincs/vaultspec-rag/commit/34467d8991ef4a812db2ca426944d6f71702139c))
* **vault:** format two records and bind the triage plan to its decisions ([#336](https://github.com/nevenincs/vaultspec-rag/issues/336)) ([6261c16](https://github.com/nevenincs/vaultspec-rag/commit/6261c16aef126af8455c66b53121f7e3fee9c481))
* **vault:** format two records to the markdown gate ([#348](https://github.com/nevenincs/vaultspec-rag/issues/348)) ([172b679](https://github.com/nevenincs/vaultspec-rag/commit/172b679bdeddb025264fa447466591c26d836f10))
* **vault:** restore Wave heading levels in the boundary plan ([7ae90bc](https://github.com/nevenincs/vaultspec-rag/commit/7ae90bc3cab271432bc3b4e182fb64f0b210cb04))

## [0.4.1](https://github.com/nevenincs/vaultspec-rag/compare/vaultspec-rag-v0.4.0...vaultspec-rag-v0.4.1) (2026-07-31)


### Bug Fixes

* interpreter pin, non-finite formatters, wheel contents, and the single-file collapse signal ([5b9f353](https://github.com/nevenincs/vaultspec-rag/commit/5b9f353f816e56e68d2aad3a8fbcb4e342934034))

## [0.4.0](https://github.com/nevenincs/vaultspec-rag/compare/vaultspec-rag-v0.3.14...vaultspec-rag-v0.4.0) (2026-07-31)


### ⚠ BREAKING CHANGES

* three environment variables are renamed, and the former spelling is no longer read at all - a stale name sets nothing and its ceiling silently falls back to the default rather than failing loudly. Rename these wherever they are set:

### Features

* add encode token-budget and chars-per-token calibration settings ([25118c8](https://github.com/nevenincs/vaultspec-rag/commit/25118c887e6b1bab01c97c3fdd45602b539e8792))
* add token-estimate bucket planner for encode batching ([f3cc83a](https://github.com/nevenincs/vaultspec-rag/commit/f3cc83ae4feb017456b8bcb3bd95a7c1ee4c890f))
* adopt token-budget buckets and shared token ceiling on the sparse encode path ([f75743f](https://github.com/nevenincs/vaultspec-rag/commit/f75743ff1cc47fe43fb2d768b9801e6dbb223e38))
* carry encode budget state and a run throughput baseline on job records ([9e6cced](https://github.com/nevenincs/vaultspec-rag/commit/9e6ccedd694d8f6e6fdae677ff74bb035e481e97))
* **cli:** require explicit GPU borrower lease for indexing ([06ca5b2](https://github.com/nevenincs/vaultspec-rag/commit/06ca5b2fce23c44df20f5e4059553819d1e2cf03))
* encode dense slices per token-budget bucket with bucket-scoped OOM retry ([0f346bd](https://github.com/nevenincs/vaultspec-rag/commit/0f346bd1369308b8f05bc6ab6ae0c783ca58e225))
* expose the encode bucket knobs through env-var overrides ([8e0a497](https://github.com/nevenincs/vaultspec-rag/commit/8e0a4973a9ab42a56b7289186ee8f984b7b0f45b))
* **gpu:** refuse model loads and test runs on a contended device ([2c7cd1d](https://github.com/nevenincs/vaultspec-rag/commit/2c7cd1d42f66bcf3bcb40c3469ea1294955e2582))
* **indexer:** publish a vault run memory high-water without a ceiling ([52c1940](https://github.com/nevenincs/vaultspec-rag/commit/52c194082ef438535bcacbf69c9293fc1ca28293))
* name the encode budget and rate collapse in degradation evidence ([aa5f1ae](https://github.com/nevenincs/vaultspec-rag/commit/aa5f1aedd8f38d3123a0b280ca3938810cba1bdd))
* publish encode budget and a rate-versus-run-median baseline on /jobs ([8d1be9d](https://github.com/nevenincs/vaultspec-rag/commit/8d1be9d70e96a3a03da1f674acd7229885802422))
* publish encode progress and budget state per bucket ([711fe4f](https://github.com/nevenincs/vaultspec-rag/commit/711fe4f74faf1b4cca1e6a1482a9b64b1692b77d))
* render the encode budget and throughput collapse on the jobs surface ([dff41f2](https://github.com/nevenincs/vaultspec-rag/commit/dff41f258de8b38cc7e2922aea4cdccd03d13ba7))
* report a collapsed run rate as degraded, not healthy ([c4874d4](https://github.com/nevenincs/vaultspec-rag/commit/c4874d4b1a902ceb63e132c87be5439ba8febb04))
* **server:** add dual-lane watch observability ([ce97796](https://github.com/nevenincs/vaultspec-rag/commit/ce97796e8702c2c70464f7e4bf21ed334ac5048a))
* **server:** add dual-lane watch observability ([20203a8](https://github.com/nevenincs/vaultspec-rag/commit/20203a8be4c9282929466a30f2e2bd5ead398524))
* **server:** add dual-lane watch observability ([fe541fd](https://github.com/nevenincs/vaultspec-rag/commit/fe541fd26ba2f65ed130661a7d35f217468c8c19))
* **service:** bind preflight to discovered identity ([d08edec](https://github.com/nevenincs/vaultspec-rag/commit/d08edec693aa5ff3e78c28cc2ba4aefd3978c445))
* **service:** enforce GPU borrower leases ([cb37d33](https://github.com/nevenincs/vaultspec-rag/commit/cb37d33d9bd26f70255944bd334e0e39dc81b29f))
* **service:** implement acknowledged resource quiescence ([8c49a3b](https://github.com/nevenincs/vaultspec-rag/commit/8c49a3b8f9b761abb6ebdc872153701bcca84b40))
* **service:** make preflight observation-only ([4196ce0](https://github.com/nevenincs/vaultspec-rag/commit/4196ce04e21428789cbebbb8ae42cb64fae57af7))
* **service:** route quiesce through resource controller ([3120b32](https://github.com/nevenincs/vaultspec-rag/commit/3120b326807ea7356dd9b695727b33419b285935))
* **tools:** fail on the scanning machine's own identity, anywhere ([6a0ec79](https://github.com/nevenincs/vaultspec-rag/commit/6a0ec790a1bd6f6928728de8eb0ccea202d6ddd8))


### Bug Fixes

* align the encode calibration divisor with the conservative chunking stance ([44f8e3f](https://github.com/nevenincs/vaultspec-rag/commit/44f8e3f6606de5c4f98f8d03dc7f76d0d5c5168d))
* **api:** project quiesce lifecycle state ([0466047](https://github.com/nevenincs/vaultspec-rag/commit/04660476eb81f8a1c2d370dfe26d71b548013964))
* **api:** route cleanup through maintenance lease ([85fa25f](https://github.com/nevenincs/vaultspec-rag/commit/85fa25f24fc50daf39f43dd4a757d442380bf142))
* **audit:** close a kernel32 restype gap in _win32.py, fix a false terminal-phase claim ([cdeb3ba](https://github.com/nevenincs/vaultspec-rag/commit/cdeb3ba758506d7b910d70cbcb3a2d84ab3c488b))
* **benchmarks:** narrow Any leakage in the benchmark harnesses ([71e3437](https://github.com/nevenincs/vaultspec-rag/commit/71e34379a8c760e42761e6eedeb7d2cd7aab05cb))
* clear every red gate on the branch ([c400b9f](https://github.com/nevenincs/vaultspec-rag/commit/c400b9f1b38c121c2db945966cc4e8851872db63))
* clear the complexity and strict-type gates ([c78873e](https://github.com/nevenincs/vaultspec-rag/commit/c78873eda086b85538ec15f2bbe2c6426c9926ce))
* clear the failing markdown gate and the platform-specific admission test ([516e380](https://github.com/nevenincs/vaultspec-rag/commit/516e380144117ccb584eaece891deb298636bcd6))
* **cli,search:** remove redundant cast() calls, fix two unguarded int() conversions ([b7e1ae8](https://github.com/nevenincs/vaultspec-rag/commit/b7e1ae8984243d911e7ac4ecae8ea8cd63bd1074))
* **cli,server:** stop restating the local-store lock refusal as foreign ([fcf961f](https://github.com/nevenincs/vaultspec-rag/commit/fcf961fc575e0c12b605a3ab07e2f6f4f30a76bc))
* **cli:** finish adoption of operator-command and status-render helpers ([abc5859](https://github.com/nevenincs/vaultspec-rag/commit/abc5859c7636731435a79e11c88caf277f635d60))
* **cli:** give each watch verb the help text for the screen it opens ([9a0503d](https://github.com/nevenincs/vaultspec-rag/commit/9a0503dcdbc1c27bf664669e6f59ad3dbcb204e6))
* **cli:** merge the two search reading renderers behind one implementation ([e258e92](https://github.com/nevenincs/vaultspec-rag/commit/e258e92e1f646874df2d2d75945cc415cb756b29))
* **cli:** merge the two search reading renderers behind one implementation ([aed9d5c](https://github.com/nevenincs/vaultspec-rag/commit/aed9d5cfa427e48982253b3895fc968256c8061b))
* **cli:** preserve quiesce service outcomes ([f7fd4bd](https://github.com/nevenincs/vaultspec-rag/commit/f7fd4bd5a22f046367e069d537c8e97c3dbd5a4c))
* **cli:** refuse delegated index fallback ([4e9ef7e](https://github.com/nevenincs/vaultspec-rag/commit/4e9ef7ef5df0ebc71f4db3c89761944765d75c87))
* **cli:** verify quiesce transition state ([0e7cce8](https://github.com/nevenincs/vaultspec-rag/commit/0e7cce899219ceb612569c4998615bea64273e3e))
* **config:** give every RAG setting a declared read type ([fe82405](https://github.com/nevenincs/vaultspec-rag/commit/fe82405e52023f675948428d8011f51ea0186a8d))
* derive controllable-filter truthy check from the shared query vocabulary ([d5a7a79](https://github.com/nevenincs/vaultspec-rag/commit/d5a7a790e6d23ea110fc8471060219cdaaed5976))
* derive INDEX_SOURCES from the IndexSource literal, not a parallel enum walk ([e69789a](https://github.com/nevenincs/vaultspec-rag/commit/e69789a8f0745457d8e2ae90feb1e8492cf922cf))
* derive the tool-repair wheel from the live environment ([3485013](https://github.com/nevenincs/vaultspec-rag/commit/3485013eb27e9e5ba80d88c66db56c3921b73ff4))
* earn the degradation verdict from the evidence published beside it ([78aa1ba](https://github.com/nevenincs/vaultspec-rag/commit/78aa1ba0eed56df17cf284848c969458a1589127))
* escalate a document incremental the ledger cannot parent ([59d39ed](https://github.com/nevenincs/vaultspec-rag/commit/59d39ed0f8f870e6c8563844ffb9d54f00bff152))
* escalate a document incremental the ledger cannot parent ([1078cec](https://github.com/nevenincs/vaultspec-rag/commit/1078cecb65e8e74b11731a620794b36b169feb99))
* give the forward window one meaning for its item count ([badbe6e](https://github.com/nevenincs/vaultspec-rag/commit/badbe6ed761755c23607838ba4b1e5830f7c95dd))
* GPU admission gate, sparse OOM telemetry, and the encode-review backlog ([0bac111](https://github.com/nevenincs/vaultspec-rag/commit/0bac11176e1ae72b1d4feda6efc61d4ee012e5cd))
* **gpu:** bind captured borrower authority to machine witness ([8584c65](https://github.com/nevenincs/vaultspec-rag/commit/8584c656e4afb3d060ec2ee3470561b2d3912aaa))
* **gpu:** bind captured borrower target ([6fd2aa3](https://github.com/nevenincs/vaultspec-rag/commit/6fd2aa3567176a93304ea32fec7d120412220010))
* **gpu:** credit the process's own residency in the admission verdict ([bc744ba](https://github.com/nevenincs/vaultspec-rag/commit/bc744ba2055db34ca72db94c44812fd7af9e4b1d))
* **gpu:** derive the admission floor, and stop latching an unevaluated verdict ([b07cc02](https://github.com/nevenincs/vaultspec-rag/commit/b07cc0281e84f1773e79a73e037ed75a2f99db10))
* harden and disambiguate the operator formatter family ([4f23f9b](https://github.com/nevenincs/vaultspec-rag/commit/4f23f9baaa5ae08fef3edf18569bfc5ab1a63dcb))
* **index:** a cancelled writer shutdown must not outlive the process ([3101b54](https://github.com/nevenincs/vaultspec-rag/commit/3101b54ac77ead61f04d2cbc40c14279da225a31))
* **indexer:** bound the producer's queue wait by the no-progress authority ([02c19f6](https://github.com/nevenincs/vaultspec-rag/commit/02c19f6350be75ed5b32746ccf72c41bc6127485))
* **indexer:** fingerprint vault bytes as stored, and census the points before a payload write ([9589b5f](https://github.com/nevenincs/vaultspec-rag/commit/9589b5f568a455bf8ad465e9852ea612c50245fa))
* **indexer:** keep evidence-cited generations through run-ledger compaction ([325700c](https://github.com/nevenincs/vaultspec-rag/commit/325700ce300688f1127fcf36e7a74413c3cdd346))
* **indexer:** refuse compacting a keep older than the newest publication ([badbf2e](https://github.com/nevenincs/vaultspec-rag/commit/badbf2e4eeabc7e2fb3a9b7b8820f4a065500ef0))
* **indexer:** refuse compacting a keep older than the newest publication ([e48a45c](https://github.com/nevenincs/vaultspec-rag/commit/e48a45cc5d0ff83dee4f9c7463cd127a0af6f4eb))
* **indexer:** stop carry-forward at a manifest with dangling evidence ([d0bb650](https://github.com/nevenincs/vaultspec-rag/commit/d0bb65046ffa53c5ae79645ac0f92258baca51a9))
* **indexer:** stop carry-forward at a manifest with dangling evidence ([9e6fb62](https://github.com/nevenincs/vaultspec-rag/commit/9e6fb6228570a275a6a5f05d739d968682d36595))
* **indexer:** take a fresh walk when a preflight is asked for one ([3c3bb58](https://github.com/nevenincs/vaultspec-rag/commit/3c3bb58e99936dbf0ac9a3275f4b2dcce9f00909))
* **install:** route both rollback failures through record_mcp_failure ([1bfeb6c](https://github.com/nevenincs/vaultspec-rag/commit/1bfeb6cf3dfa45f81ddbf89458b574f7d0095461))
* **job-manager:** declare the composed manager's real attribute types on two mixins ([316c6fe](https://github.com/nevenincs/vaultspec-rag/commit/316c6fe7b790fdc6463344ac584f0f4bc810101b))
* **jobs:** declare the adopted loop as optional where it is read ([aad7be0](https://github.com/nevenincs/vaultspec-rag/commit/aad7be08733011a4ea96a4d908455ff1609e6b40))
* **jobs:** dispatch work admitted off the loop onto the loop that owns it ([9c75309](https://github.com/nevenincs/vaultspec-rag/commit/9c75309a6cd4e055f0fbcf564b689827fca60cf4))
* **jobs:** dispatch work admitted off the loop onto the loop that owns it ([f40bbe9](https://github.com/nevenincs/vaultspec-rag/commit/f40bbe914931c4ebe6aab26dd61b0ac82eae3221))
* **jobs:** drop the registry-cached manager when job state resets ([fb40d5c](https://github.com/nevenincs/vaultspec-rag/commit/fb40d5cb2f3759e04717e7ec2e19c207719802a6))
* **jobs:** refuse a job source that has no admitted index domain ([46dab2d](https://github.com/nevenincs/vaultspec-rag/commit/46dab2dcf9f8016c5c5e387342740ef04de1739a))
* **jobs:** release a compute ticket wherever the runtime owner is replaced ([693a352](https://github.com/nevenincs/vaultspec-rag/commit/693a352804c2febf7bad42cd276e746ddf9d21fa))
* keep evidence-cited generations through run-ledger compaction ([6cb8a61](https://github.com/nevenincs/vaultspec-rag/commit/6cb8a61313bb9bc46f7b96ba953bc541ad7b7973))
* **logging:** enrol every producer in the one logging backend ([a3be21e](https://github.com/nevenincs/vaultspec-rag/commit/a3be21ebcac06e98852cea633b98f16ec2c07fd5))
* **logging:** enrol every producer in the one logging backend ([#316](https://github.com/nevenincs/vaultspec-rag/issues/316)) ([a9f62ee](https://github.com/nevenincs/vaultspec-rag/commit/a9f62ee3a4c7af7c5ceba816d6d1c1fa3958aeac))
* **mcp:** preserve authoritative service state ([866f399](https://github.com/nevenincs/vaultspec-rag/commit/866f399c6e2bce88a1bb067b46b014ff42f1067c))
* **mcp:** preserve quiesce service state ([8ed4fb7](https://github.com/nevenincs/vaultspec-rag/commit/8ed4fb71b7122424ac14b80f869c05d81d8f147e))
* narrow Any leakage in the run ledger, store runtime, and HTTP transport ([e358627](https://github.com/nevenincs/vaultspec-rag/commit/e358627cc6e41838cbbc71ef103f678d3cd57a71))
* pin --python in the durable tool-install remediation command ([25848b6](https://github.com/nevenincs/vaultspec-rag/commit/25848b6207ca7c7b37b8d2bfdd9e343478265f37))
* **quiesce:** check the terminal failure vocabulary instead of assuming it ([2fc781e](https://github.com/nevenincs/vaultspec-rag/commit/2fc781e1fb32556d0548291af25681f4e3feae76))
* **quiesce:** dispatch recovery through manager ([b0d28a3](https://github.com/nevenincs/vaultspec-rag/commit/b0d28a30e3bf378f3322081469d8aead153d33b1))
* read a published measurement as a non-negative finite quantity ([97b996c](https://github.com/nevenincs/vaultspec-rag/commit/97b996caace4c1b285b1451a82d9354b48888dd0))
* read every published job value through the canonical readers ([ebd7434](https://github.com/nevenincs/vaultspec-rag/commit/ebd7434b0afccb587b87eec0df849ede385872c1))
* read the encode evidence counts through the counting reader ([b06c5b5](https://github.com/nevenincs/vaultspec-rag/commit/b06c5b5dbca4c150f10b465374d08e955519469e))
* **registry:** one home for the published project bounds ([51c7d0f](https://github.com/nevenincs/vaultspec-rag/commit/51c7d0f978e754e4f0c44b9380e3bbca8d998020))
* **routes:** expose jobs quiesce state ([9fc8582](https://github.com/nevenincs/vaultspec-rag/commit/9fc858287342162e26aa7f6a52eaf21f2ad27eac))
* scrub real machine identity from tracked files ([cdea72f](https://github.com/nevenincs/vaultspec-rag/commit/cdea72f2c3dbef271a9f98150bfd76efb0363931))
* **server:** cover ledger retention and drop its constant count fields ([aae14cd](https://github.com/nevenincs/vaultspec-rag/commit/aae14cd85130cdb0473cfb1d57e01ff4b568ac3a))
* **server:** preserve runtime registry in service state ([5df4ad8](https://github.com/nevenincs/vaultspec-rag/commit/5df4ad89be50b5af1745d827a569c0e9d0e2245b))
* **server:** reject closed watcher registries before warming ([908d73c](https://github.com/nevenincs/vaultspec-rag/commit/908d73c29e551909e4e82ff25b41a0287f70286e))
* **server:** report a refused search as a failure over the wire ([b28506b](https://github.com/nevenincs/vaultspec-rag/commit/b28506b8fa5c0d0669a5159513f7ec08d26eb704))
* **server:** retain runtime registry through search ([87d5555](https://github.com/nevenincs/vaultspec-rag/commit/87d5555a4f6231e35f1565fa79c91693f5acffb8))
* **server:** stop typing a combined search as a single index source ([d42b2a3](https://github.com/nevenincs/vaultspec-rag/commit/d42b2a370dc60577178f6e5736dc774d9c60a967))
* **service:** build a project runtime outside the registry lock ([5ad8f23](https://github.com/nevenincs/vaultspec-rag/commit/5ad8f23102237b1a66603fc89bd6225cc087b296))
* **service:** checkpoint W02 quiesce remediation ([06fe714](https://github.com/nevenincs/vaultspec-rag/commit/06fe714abc71e075f9963f6145fa6a62df87e6d4))
* **service:** checkpoint W02 resume recovery remediation ([1350888](https://github.com/nevenincs/vaultspec-rag/commit/135088867fc8a356857b8ed0675e7dbc0edb4b13))
* **serviceclient:** correct false single-owner claim on the health probe docstring ([bd432d7](https://github.com/nevenincs/vaultspec-rag/commit/bd432d7458369c9ecfd046d9b27fcfc8cad3abf1))
* **serviceclient:** reject a non-object response body at the transport ([0477efb](https://github.com/nevenincs/vaultspec-rag/commit/0477efb27be30d5f7331d27e2b609df73aa77bf9))
* **service:** fail closed on borrower lease faults ([2c7a44f](https://github.com/nevenincs/vaultspec-rag/commit/2c7a44f5b6398f9544e86d62a1097081c5a165cb))
* **service:** hold a root store guard across eviction, not just admission ([2d8e67f](https://github.com/nevenincs/vaultspec-rag/commit/2d8e67fa19cf3a59e7ffe6ddbdb21c838485fc51))
* **service:** let resume recover a pause that never finished, and always answer ([a969e9f](https://github.com/nevenincs/vaultspec-rag/commit/a969e9f99cb99f439fab9d786214a67dd177263b))
* **service:** mark refused quiesce transitions retryable ([0df85c2](https://github.com/nevenincs/vaultspec-rag/commit/0df85c2c1c67925453418e8f5272565b45da9c5c))
* **service:** project the whole quiesce snapshot, and write each invariant once ([0441d82](https://github.com/nevenincs/vaultspec-rag/commit/0441d82a2296b65199852c229e68208b44b183aa))
* **service:** serialise a root's store admission for the whole lease ([c28ddc5](https://github.com/nevenincs/vaultspec-rag/commit/c28ddc526fcdd580fd1acf9bbbd08f9ce5b0887b))
* **service:** serialize capped project admission ([cf9a0b1](https://github.com/nevenincs/vaultspec-rag/commit/cf9a0b1e244f9ebd898e6b60639ed3a6a9e7c32c))
* **store:** let a count report an absent collection instead of creating one ([0694179](https://github.com/nevenincs/vaultspec-rag/commit/0694179fdcbbf7bb33cb4a5576142888efcf4820))
* **store:** let a read answer for an absent collection without creating it ([33a900b](https://github.com/nevenincs/vaultspec-rag/commit/33a900be84ed1709b3d546b8215f4fe68c27baf3))
* **tests:** audit the 5 test-suite type: ignore directives and narrow Any ([eee034d](https://github.com/nevenincs/vaultspec-rag/commit/eee034d2fd137466e0bb972ac62c0fa98630a27d))
* **tests:** count the dots a relative import actually climbs ([9525f42](https://github.com/nevenincs/vaultspec-rag/commit/9525f4239c8684c332506f95eef116ad097f1146))
* **tests:** narrow Any in tests/integration and tests/benchmarks ([851b7ac](https://github.com/nevenincs/vaultspec-rag/commit/851b7ac460dcf31a29b049aeaa0e7dcacbb167e2))
* **tests:** narrow Any leakage from VaultSpecConfigWrapper reads in test_config.py ([cfb4df6](https://github.com/nevenincs/vaultspec-rag/commit/cfb4df63c616e22fc382e5189fe150a302dd8eb9))
* **tests:** narrow Any leakage in test-side JSON/RPC helpers ([9817764](https://github.com/nevenincs/vaultspec-rag/commit/981776451f6d23d375d2e70e347570c4c85cfe9c))
* **tests:** narrow Any leakage in top-ranked test/benchmark files ([93ee1e9](https://github.com/nevenincs/vaultspec-rag/commit/93ee1e9c39e2b7fd948c762a21edb02a50dbfb43))
* **tests:** remove dead pyright suppressions in the test suite ([f58cfd6](https://github.com/nevenincs/vaultspec-rag/commit/f58cfd69f0fb306922b08f926a35f32ae076e733))
* **tests:** state the key type the merged projection assertions read ([974e487](https://github.com/nevenincs/vaultspec-rag/commit/974e487c55158381c6193570fe8e67543a50bce4))
* **tests:** state the key type the merged quiesce assertions read ([02f380a](https://github.com/nevenincs/vaultspec-rag/commit/02f380a8bcaf59fded10848bfbb6b8d89a3a5440))
* **tests:** stop naming a real person in the identity-leak fixture ([7ce2f57](https://github.com/nevenincs/vaultspec-rag/commit/7ce2f57a406e992d7e7fbada5b2e4d7a5d25305e))
* **tests:** type the CLI stub-server producers instead of Any at each use site ([42a4f30](https://github.com/nevenincs/vaultspec-rag/commit/42a4f309913c4de8ee4541b34a171e371c83ee4a))
* **tools:** scan every surface for identity, exempting none ([cade1c5](https://github.com/nevenincs/vaultspec-rag/commit/cade1c52bea7872b28ce7658fc434163f362b079))
* **tui:** let the quiesce cell speak only when the controller has news ([43da936](https://github.com/nevenincs/vaultspec-rag/commit/43da936e2c4a6126b94b9b3965fc5159f1c3ac6a))
* **tui:** own the jobs beats on the screen they paint ([fe8bfd8](https://github.com/nevenincs/vaultspec-rag/commit/fe8bfd89ab06de47edac6e585c5e9cbc163b7047))
* **tui:** show service quiesce evidence ([5428441](https://github.com/nevenincs/vaultspec-rag/commit/54284415e03995b09c3e671210628f9b00f3c35d))
* **types:** clear the strict type gate without suppressions ([2046bc7](https://github.com/nevenincs/vaultspec-rag/commit/2046bc76415a7222760645633e50bd7eeee3015f))
* **types:** narrow Any at click/qdrant/sqlite producer boundaries ([5d58e95](https://github.com/nevenincs/vaultspec-rag/commit/5d58e9500ddc372df5f456b7ba074d5bf74e7edc))
* **types:** narrow Any in parameter, field, and type-argument positions ([917f529](https://github.com/nevenincs/vaultspec-rag/commit/917f5296d9c1d62faa8e58a77a2160ee6dfd4f80))
* **types:** narrow Any leakage at sqlite-row and JSON-descriptor producers ([3883b9d](https://github.com/nevenincs/vaultspec-rag/commit/3883b9da8684639d170ca8d438905e0a8bccedd0))
* **types:** narrow Any leakage in citation-gate and indexer unit tests ([e10e0ba](https://github.com/nevenincs/vaultspec-rag/commit/e10e0ba08e920cf1163e07b354b95e158c4f0521))
* **types:** narrow Any leakage in install-render and status/topology tests ([108d6f3](https://github.com/nevenincs/vaultspec-rag/commit/108d6f3a4cb8377dd5392c1de89b380d77d74c39))
* **types:** narrow Any leakage in memory_probe, cli install, and benchmarks ([31448fd](https://github.com/nevenincs/vaultspec-rag/commit/31448fdcf83db8f95518233a68920ed406b13659))
* **types:** narrow reachable Any leakage in CLI/qdrant_runtime producers ([e6ba739](https://github.com/nevenincs/vaultspec-rag/commit/e6ba739b04b48e86dd21bb2875107ed9ebdab298))
* **types:** refuse a drifted source vocabulary even when optimised ([493a277](https://github.com/nevenincs/vaultspec-rag/commit/493a277d3e652486c80d0282bd7311964ba114f2))
* **types:** remove dead reportMissingTypeStubs suppressions ([2c49ad1](https://github.com/nevenincs/vaultspec-rag/commit/2c49ad184a100d16094a4a2f587c367337d24099))
* **types:** replace dict[str, Any]/Mapping[str, Any] payload holes with precise types ([2761825](https://github.com/nevenincs/vaultspec-rag/commit/27618257ded1e577a5c9c1a9bdb90c1bae6c7225))
* **typing:** remove unjustified casts in job_manager and indexer ([7cf04f6](https://github.com/nevenincs/vaultspec-rag/commit/7cf04f621ca47fcacc78ec3f689aa9c03ae855f1))
* **typing:** remove unjustified casts in root-level modules, document justified ones ([955986e](https://github.com/nevenincs/vaultspec-rag/commit/955986ecf25c8a8dd32efd404a7306e478255224))
* validate stored vector and point-id entries, not just their shape ([c0f8e0d](https://github.com/nevenincs/vaultspec-rag/commit/c0f8e0d6f8bf7241241f4c527513419120e57c0b))
* **watch:** degrade to redaction, name the bound, cap the read ([07c98c0](https://github.com/nevenincs/vaultspec-rag/commit/07c98c09ca5b2c8f492c8e1545b226fec3a963e0))
* **watcher:** report a superseded reindex as its own outcome, not a failure ([4e6ddf0](https://github.com/nevenincs/vaultspec-rag/commit/4e6ddf0ea0a4ecf05894328c5b135c705304074a))
* **watch:** the console marks every outcome the service calls a failure ([b25a6df](https://github.com/nevenincs/vaultspec-rag/commit/b25a6df0c5e3a52aa5c03e99d9a5e3b17d366772))


### Performance

* **indexer:** plan encode batches by token budget; make a throughput collapse visible ([6927ac3](https://github.com/nevenincs/vaultspec-rag/commit/6927ac3ba15eb36778738d8e9ab88cf7da44f099))
* **indexer:** publish sparse encode OOMs through the one bucket seam ([08b8ee4](https://github.com/nevenincs/vaultspec-rag/commit/08b8ee4ef38673c11690c330224e6c21f301f9dd)), closes [#314](https://github.com/nevenincs/vaultspec-rag/issues/314)
* **indexer:** split the vault fingerprint so metadata churn skips the GPU ([f3e0b34](https://github.com/nevenincs/vaultspec-rag/commit/f3e0b34393f4125299811f5fdae1af99456f8658))


### Code Refactoring

* standardize every mebibyte name on the _mib suffix ([a52b23b](https://github.com/nevenincs/vaultspec-rag/commit/a52b23b08a1deda7387c77caa6c678019b30a8b7))

## [0.3.14](https://github.com/nevenincs/vaultspec-rag/compare/vaultspec-rag-v0.3.13...vaultspec-rag-v0.3.14) (2026-07-28)


### Features

* **runtime:** support CPython 3.14 ([b4bb5f7](https://github.com/nevenincs/vaultspec-rag/commit/b4bb5f7cdf45851bae103d1556234d1ad60191db))
* **runtime:** support CPython 3.14 ([84677d0](https://github.com/nevenincs/vaultspec-rag/commit/84677d0d2bcb37377e902d31044a9cd583968d41))


### Bug Fixes

* **cli:** name the free-threaded ABI in the torch repair command ([f19f062](https://github.com/nevenincs/vaultspec-rag/commit/f19f0623dbd7edcd2325de77a866f9bb72102933))
* **cli:** name the free-threaded ABI in the torch repair command ([912e464](https://github.com/nevenincs/vaultspec-rag/commit/912e464870d0fb60f0e47654e8db4708ada078ba))
* **cli:** render superseded jobs as resolved history ([12ec8e0](https://github.com/nevenincs/vaultspec-rag/commit/12ec8e01bcc4902747e421e467e9ce775c04216b))
* **jobs:** log control rejections and resolve retried parents ([bdbb095](https://github.com/nevenincs/vaultspec-rag/commit/bdbb095b13e64252295d53498625da7321226e03))
* **jobs:** log control rejections and resolve retried parents ([7b5644d](https://github.com/nevenincs/vaultspec-rag/commit/7b5644df62e5f5348affddaffde0969e9f32de10))
* **jobs:** make progress, degradation evidence, and retry lineage tell the truth ([3b38a97](https://github.com/nevenincs/vaultspec-rag/commit/3b38a978e88b1c6014ac819bf074116829d73ca5))
* **jobs:** make progress, degradation evidence, and retry lineage tell the truth ([910cef7](https://github.com/nevenincs/vaultspec-rag/commit/910cef7e6fc31998348d0552922ebc74e7990db5))


### Performance

* **indexer:** pin retained-point join order; make OOM batch ceiling sticky ([bad146c](https://github.com/nevenincs/vaultspec-rag/commit/bad146c6117f0c03a68767e9090fd0d69fba8b10))
* **indexer:** pin retained-point join order; make OOM batch ceiling sticky ([232a055](https://github.com/nevenincs/vaultspec-rag/commit/232a055a93382c13fd14f91aed130d2778b95f0e))

## [0.3.13](https://github.com/nevenincs/vaultspec-rag/compare/vaultspec-rag-v0.3.12...vaultspec-rag-v0.3.13) (2026-07-28)


### Features

* **cli:** open the jobs interface from `server --watch` ([3c06c20](https://github.com/nevenincs/vaultspec-rag/commit/3c06c2069d5e9aeec19a2f4a4912c8258e690493))
* **indexer:** publish the vault index's breadth so truncation is detectable ([fca2376](https://github.com/nevenincs/vaultspec-rag/commit/fca23760f0368cc7e3757fea2b576cd3e3b7e4b6))
* **integrity:** reconcile served breadth against the published claim on every search ([3bc96eb](https://github.com/nevenincs/vaultspec-rag/commit/3bc96eb843aefc10adb36fb2d30d7b9ec2b9330a))
* **jobs:** render the remaining-time estimate everywhere operators look ([96a55d7](https://github.com/nevenincs/vaultspec-rag/commit/96a55d7edb1e97eb6355581a6833bc41ff6c2875))
* **mcp:** move onto the mcp 2.x server surface and lift the version cap ([a7e312b](https://github.com/nevenincs/vaultspec-rag/commit/a7e312b97c28745273ffa5ac1ed72f258733f572))
* **observability:** give long encode phases a verdict, a cause, and an honest error channel ([bdbe9d6](https://github.com/nevenincs/vaultspec-rag/commit/bdbe9d6b17e99d6b257d0e5d1b6fe479b2f7daf6))
* **service:** surface a machine pressure tier over the telemetry already sampled ([d4d8cc5](https://github.com/nevenincs/vaultspec-rag/commit/d4d8cc52aed008ee442cc9a09f44d2f55a919530))
* **tui:** one verbatim design-token palette, and the daemon names itself ([a7b8a7b](https://github.com/nevenincs/vaultspec-rag/commit/a7b8a7b3f7a501e23a70156b3f812ac0cc318e40))
* **tui:** pill header with service condition and always-on GPU pressure ([28e56d7](https://github.com/nevenincs/vaultspec-rag/commit/28e56d704f7daad322aab93a9856fe5326ef070b))
* **tui:** rounded filled pills inside a unified rounded header ([79276ec](https://github.com/nevenincs/vaultspec-rag/commit/79276ecdb98753c2a5804cb56afe4b81c0b0d99d))
* **tui:** structured, sanitized, navigable log pane with focus-lit panes ([4cd54c3](https://github.com/nevenincs/vaultspec-rag/commit/4cd54c3b8a20d002ce0d666be8e11aa2484540d9))
* **tui:** uniform pill header on shipped Nord and Solarized palettes ([9e5348a](https://github.com/nevenincs/vaultspec-rag/commit/9e5348a8082c5573b6e02f65bd90d5d08a2f28a0))


### Bug Fixes

* **ci:** call the recipes the justfile actually defines ([816dd55](https://github.com/nevenincs/vaultspec-rag/commit/816dd55e9c06636d9596f0aef1fbdc21839380f9))
* **citation-gate:** see the assert message, the last construct hiding citations ([0dde3bc](https://github.com/nevenincs/vaultspec-rag/commit/0dde3bc75ef40044ee1ed34607d1d9e849b5a48f))
* **deps:** cap mcp below 2 until the fastmcp surface is migrated ([2be2389](https://github.com/nevenincs/vaultspec-rag/commit/2be2389da6f2ef9c6774c1eeae5699f06320f53c))
* **indexer:** discover donors that have published a rebuild ([9641755](https://github.com/nevenincs/vaultspec-rag/commit/9641755a42dd5fbad93577b2bd94f53d1919ba67))
* **index:** never publish a code claim over a collection that is not there ([09d859c](https://github.com/nevenincs/vaultspec-rag/commit/09d859c917b9ecdd4549cddd3a8ddfb952ce0931))
* **index:** rebuilds never destroy what they serve, and a shrink heals itself ([fabd2c6](https://github.com/nevenincs/vaultspec-rag/commit/fabd2c67d8d7078fc18a033fbcf086d2367da339))
* **mcp:** address a nested document stem, and advertise the release ([f9cab2d](https://github.com/nevenincs/vaultspec-rag/commit/f9cab2d82041454dad46fda5cab3427e9ca31d52))
* **mcp:** resolve the worktree build without a platform-specific path ([48e3046](https://github.com/nevenincs/vaultspec-rag/commit/48e3046e72f53dfe019fd9037c0ec242ed350988))
* name the cross-module helpers what they are, and repair two driver scripts ([cd98312](https://github.com/nevenincs/vaultspec-rag/commit/cd983122739973b56ed4f886506d4e7a7a4a0320))
* **server:** re-arm the stdio watchdog rather than disarm on a lost anchor ([393753b](https://github.com/nevenincs/vaultspec-rag/commit/393753b213276a8fa0f8ff55fa19047e3539fbea)), closes [#288](https://github.com/nevenincs/vaultspec-rag/issues/288)
* **service:** fail the pressure verdict open, and let dead jobs speak for the store ([7f52d9b](https://github.com/nevenincs/vaultspec-rag/commit/7f52d9be35e357418aff3fa080ca223c8c425cd6))
* **service:** re-establish the resident CUDA baseline when a registry closes ([f7f1729](https://github.com/nevenincs/vaultspec-rag/commit/f7f1729a26a1d1674a467cee1608f08359375bc9))
* **tests:** base the cuda ceiling guard on the enforced baseline ([6a80892](https://github.com/nevenincs/vaultspec-rag/commit/6a808920e858543c933fb660e7b4b970c1023783))
* **tests:** clear the two gates the dead CI step was hiding ([5e406dc](https://github.com/nevenincs/vaultspec-rag/commit/5e406dc58239dcdbe381fe3fdecf1eb682e6c07d))
* **tests:** follow the spawn call path in the daemon-anchor guard ([7ccf6f6](https://github.com/nevenincs/vaultspec-rag/commit/7ccf6f6fcc42e88a738b4931aa704510eb63d767))
* **tests:** hold the jobs watch interrupt to the interface contract ([96e0819](https://github.com/nevenincs/vaultspec-rag/commit/96e0819985b2a76e700231b109e914247a664db2))
* **tests:** measure collection size through the guarded production walk ([3822943](https://github.com/nevenincs/vaultspec-rag/commit/3822943bfbee905b8906d810042729cf8a4cb225))
* **tests:** seed the clean-resume guard where a rebuild actually builds ([d857a24](https://github.com/nevenincs/vaultspec-rag/commit/d857a24c35bee47fb604c22c63bc5d7dd546f66b))
* **tests:** stop funding a teardown courtesy Windows cannot use ([1d01ec4](https://github.com/nevenincs/vaultspec-rag/commit/1d01ec42917e4c27655116d80c8a74a59e5a3c73))
* **tests:** stop the jobs since-filter guard racing its own timestamp ([79a06fa](https://github.com/nevenincs/vaultspec-rag/commit/79a06fa6a712808a45baf0a4db0d7e0dc8e39305))
* **tests:** stop the watcher fixture stranding drains and slots ([a2f46c2](https://github.com/nevenincs/vaultspec-rag/commit/a2f46c20774260dcd230065fddd7fb71bb8c19e0))
* **tests:** stop two checks reading state they do not control ([77d14ab](https://github.com/nevenincs/vaultspec-rag/commit/77d14ab52271f0951ae60838b976d165d48cce1d))
* **tests:** teach the counting reporter the forward-boundary protocol ([04c398b](https://github.com/nevenincs/vaultspec-rag/commit/04c398be620f3913112e08f353762741bfaa4812))
* **tooling:** make the health report read its thresholds instead of restating them ([dc87ddf](https://github.com/nevenincs/vaultspec-rag/commit/dc87ddf99ffc85c8df588152b6e455bb7f689c5a))
* **types:** return both type gates to zero findings ([578d3cc](https://github.com/nevenincs/vaultspec-rag/commit/578d3ccca4c5e4aa3c2b2e15dc8a57fb9e8caae7))


### Performance

* **embeddings:** load SPLADE only when sparse vectors are enabled ([555a5df](https://github.com/nevenincs/vaultspec-rag/commit/555a5df003831638debcbb52589abf346d4a49bc))
* **index:** answer unchanged files from stat evidence and keep live interruptions scoped ([1bcde19](https://github.com/nevenincs/vaultspec-rag/commit/1bcde1986c28ae75ff49da4e142ca887e20f2c3a))
* **indexer:** amortize per-file overhead out of the hashing loops ([8b46410](https://github.com/nevenincs/vaultspec-rag/commit/8b464109249e701d328d861830cd8ef83ff94695))
* **jobs:** coalesce progress durability so a loop publish stops paying an fsync ([8c264a6](https://github.com/nevenincs/vaultspec-rag/commit/8c264a66d0570f8bcc0208eae5b413e655e0bfca))
* **tests:** share one live daemon across the modules that only read it ([04cc613](https://github.com/nevenincs/vaultspec-rag/commit/04cc613ddef64ebd9d8cc401f8b4d5fa67623a5e))
* **tests:** share one qdrant server across the storage-ops module ([989803f](https://github.com/nevenincs/vaultspec-rag/commit/989803f6927427cc9bf262dca552612f39a236e6))

## [0.3.12](https://github.com/nevenincs/vaultspec-rag/compare/vaultspec-rag-v0.3.11...vaultspec-rag-v0.3.12) (2026-07-27)


### Features

* **cli:** split service jobs CLI into collection, control, presentation, query, watch with route/CLI/MCP tests ([dcbca59](https://github.com/nevenincs/vaultspec-rag/commit/dcbca5912baf3c0971ea606a5c253e42de914dd0))
* **config:** split config module into paths, schema, settings, types ([5c8d0b7](https://github.com/nevenincs/vaultspec-rag/commit/5c8d0b7b30a2913cd95e0c9bd3ea2d7563c7c540))
* **indexer:** split run ledger into commits, files, finalization, models, runtime ([332466d](https://github.com/nevenincs/vaultspec-rag/commit/332466d4a2b5f1d04d07b4a34b482be960063f34))
* **job-manager:** add job manager module with admission, degradation, and quiesce tests ([fce591d](https://github.com/nevenincs/vaultspec-rag/commit/fce591d491ba912c1aba922b946738959d71825f))
* **storage:** add storage restore/survey and store collections/donors/ingest/runtime modules ([c7f3f42](https://github.com/nevenincs/vaultspec-rag/commit/c7f3f42971153e80d074df9cc768f9a3d92a9da0))
* **watcher:** split watcher into intake, policy, execution, retry settlement, durability, runtime ([8d59820](https://github.com/nevenincs/vaultspec-rag/commit/8d59820cde17a2ecc1e5a619c0d5ade7d19fd871))


### Bug Fixes

* **backoff:** one capped exponential, and a streak that no longer overflows ([41e0669](https://github.com/nevenincs/vaultspec-rag/commit/41e06693931b0e0eae69d982397f1efaada7e129))
* **cli:** complete status render lint remediation ([d6bbcf4](https://github.com/nevenincs/vaultspec-rag/commit/d6bbcf43aba074696b6ae9cb3ad3115d228d26cf))
* **cli:** drop the elevation advice; name the command that ends the process ([92c44e1](https://github.com/nevenincs/vaultspec-rag/commit/92c44e1bda667fc24edff95221c748322708967e))
* **cli:** honour VAULTSPEC_RAG_ROOT instead of discarding it ([fcfae17](https://github.com/nevenincs/vaultspec-rag/commit/fcfae1736ced9d70d15ae06c0b0d9f6bc29d1ba2))
* **cli:** one index command, and a rebuild list that cannot go stale ([20dd95d](https://github.com/nevenincs/vaultspec-rag/commit/20dd95db47c0d2f049cf16cbeed6e7fcdc61da5b))
* **cli:** resolve root application lint defaults ([88512dd](https://github.com/nevenincs/vaultspec-rag/commit/88512ddc491e63f0619dd9fc45e90e9b6b98f28c))
* **cli:** say when a refused stop targets a process we cannot even see ([6fd3fd7](https://github.com/nevenincs/vaultspec-rag/commit/6fd3fd7c78957666913095b09d776cfbdfa7d727))
* **cli:** start and stop reach the watcher through one call path ([84b5e00](https://github.com/nevenincs/vaultspec-rag/commit/84b5e006266ca9eb3e06848871423a26436db9e5))
* **cli:** stop offering the originating console as a stop remedy ([5376c2f](https://github.com/nevenincs/vaultspec-rag/commit/5376c2f297f85c055514ecf1edc62a6f94e85f7e))
* complete upstream complexity default restoration ([1dda3bf](https://github.com/nevenincs/vaultspec-rag/commit/1dda3bfba7f25275abc6f85e758bf29d3632eb40))
* **config:** one boolean vocabulary for every environment switch ([d7abd92](https://github.com/nevenincs/vaultspec-rag/commit/d7abd9212d89718b920136f3e7bb727917662354))
* **deps:** declare huggingface-hub, numpy, anyio, starlette, uvicorn as direct deps ([dfc3e5b](https://github.com/nevenincs/vaultspec-rag/commit/dfc3e5bf14e320399283abd02e776e8c82b1782a))
* **embeddings:** restore dense peak capture import ([154f130](https://github.com/nevenincs/vaultspec-rag/commit/154f1302a351fa14d91608ca13480253ca7b1aa6))
* give every cross-module literal twin one owner ([a44705a](https://github.com/nevenincs/vaultspec-rag/commit/a44705a9bf855749162af4bb48e2e4abaa9a605e))
* hash an unreachable root instead of raising ([c083318](https://github.com/nevenincs/vaultspec-rag/commit/c0833184b9d0942b1583770f62e8fe0bfede6177))
* **indexer:** give the vault sidecar keys the home the code keys already had ([72bb14f](https://github.com/nevenincs/vaultspec-rag/commit/72bb14f23a48b3dfd8c590b65b704b3db6197cdd))
* **indexer:** one resolver for the sparse width, one rule for the emitted cap ([deee1e9](https://github.com/nevenincs/vaultspec-rag/commit/deee1e98bcba743f81b7e585affdaa2abed4115a))
* **indexer:** refuse at admission when the ceiling admits no forward ([3129f0f](https://github.com/nevenincs/vaultspec-rag/commit/3129f0fdcb60283dc30a372002b1b2e3a2d020b3))
* **indexer:** restore type-only threading import ([2ac31f1](https://github.com/nevenincs/vaultspec-rag/commit/2ac31f1d79a63628d1704eb5d1d294fd2b65e632))
* **indexer:** satisfy lint defaults in chunking paths ([493f85b](https://github.com/nevenincs/vaultspec-rag/commit/493f85ba473758891d8741928e83d1d5a53004e0))
* **jobs:** a failed replace is not a published one, on any platform ([844246b](https://github.com/nevenincs/vaultspec-rag/commit/844246b5b23b97395de9ac07ecd041eb3fdf92b5))
* **jobs:** a failed Windows replace rolls the intent back ([e5da69f](https://github.com/nevenincs/vaultspec-rag/commit/e5da69f2556b90abafd63747428c826c77d2db84))
* **jobs:** make delete reach every registry that retains a job ([1b1f710](https://github.com/nevenincs/vaultspec-rag/commit/1b1f7102c16fda58e081c08133caaca8f66ac524))
* **jobs:** name the enum groupings the call sites were enumerating ([7ce087e](https://github.com/nevenincs/vaultspec-rag/commit/7ce087ea1c44650e8d78a583e8747f58bd9aa64f))
* **jobs:** one indexing attempt runner for code and document ([ce9e76e](https://github.com/nevenincs/vaultspec-rag/commit/ce9e76e008d756243e167829481710777a54f0a5))
* **jobs:** the desired-state vocabulary is stated by its enum, not five times ([856b9b4](https://github.com/nevenincs/vaultspec-rag/commit/856b9b4f46b9c94ab5fb1156bc1085570219b930))
* **jobs:** the job vocabularies are stated by their enums ([6b1f804](https://github.com/nevenincs/vaultspec-rag/commit/6b1f8049e73c85a85bf924dbc08e521b69d8fddd))
* keep the workspace-layout constants off the env-var namespace ([f24834f](https://github.com/nevenincs/vaultspec-rag/commit/f24834f599ad2d4fb023a5ba9b85352a1421f191))
* merge the last repeated statement runs, and wire the scan in as a guard ([4a7c933](https://github.com/nevenincs/vaultspec-rag/commit/4a7c93389f3a232f5799aa07ec6220e05073a49b))
* one atomic file replace, and every publisher gets the Windows retry ([ab52686](https://github.com/nevenincs/vaultspec-rag/commit/ab52686657164e313602ef19a5ade2e799ff63d1))
* one atomic JSON publish, and twelve writers stop leaking their temp file ([e9ce323](https://github.com/nevenincs/vaultspec-rag/commit/e9ce32367dd7acd3ece6f4df961d255c94bae0d8))
* one canonical job source for supersession comparison ([470666d](https://github.com/nevenincs/vaultspec-rag/commit/470666d3d1361fbbdfc887e78a30ceeca3235b19))
* one disk-space probe, not a copy in storage_reconciliation ([6d70871](https://github.com/nevenincs/vaultspec-rag/commit/6d70871816f1cb2a3e26bbc04a054e9ba42a29a1))
* one embedding-input format, one direct-dep write-and-report ([2935058](https://github.com/nevenincs/vaultspec-rag/commit/293505836b4a82c403f91a510fee936246a576ec))
* one envelope for a rejected source type, built by the error itself ([bbe1827](https://github.com/nevenincs/vaultspec-rag/commit/bbe1827cb0a22f94b2a1d168aeeb34e42c42b34b))
* one job-source vocabulary, and a guard that __all__ was hiding from ([695b383](https://github.com/nevenincs/vaultspec-rag/commit/695b3838a31d88dabe82576d9b4a9dfe1b75818e))
* one model list and one resource question ([bb002c6](https://github.com/nevenincs/vaultspec-rag/commit/bb002c625dbbdb34c1feba12e22463c22ab6ee3d))
* one provisioning vocabulary, and delete the identity map between its twins ([84a3113](https://github.com/nevenincs/vaultspec-rag/commit/84a311373e86020507446a6aa40caec3b8a3add9))
* one reader for a stored timestamp, one policy for a link ([82e1bbe](https://github.com/nevenincs/vaultspec-rag/commit/82e1bbeefbe339fe4eef3b4b356ebffe798cf535))
* one vocabulary for "the disk is full" ([ad170f2](https://github.com/nevenincs/vaultspec-rag/commit/ad170f216087b23519e1a0c5094654c026dbf8f3))
* **qdrant:** name each pinned release asset once, and declare the pin that is unreachable ([ad0a5e3](https://github.com/nevenincs/vaultspec-rag/commit/ad0a5e39dd9e2b456dfc1422ade32abc3c94fc58))
* repair 17 failing test modules and three shipped defects ([f98ab2a](https://github.com/nevenincs/vaultspec-rag/commit/f98ab2a791811e207783fade35f0944f8cf2257e))
* repair the status-dir regression, and finish the atomic JSON publish ([c430fe1](https://github.com/nevenincs/vaultspec-rag/commit/c430fe16c75a6157c6df3efe7a4749641667a289))
* resolve config defaults in config, not at the point of use ([32712e9](https://github.com/nevenincs/vaultspec-rag/commit/32712e9b4ef5af0b7b24612d33af6e793d1de3d9))
* **search:** name the phase keys the first pass missed, and widen the guard ([437f8b2](https://github.com/nevenincs/vaultspec-rag/commit/437f8b22112e1264081b02b2bb11e755a85d91d6))
* **search:** name the timings phase keys instead of spelling them ([628f595](https://github.com/nevenincs/vaultspec-rag/commit/628f595d780875850e32633f583e1bffada800cb))
* **search:** one filter vocabulary, declared beside the indexes that back it ([8443d5d](https://github.com/nevenincs/vaultspec-rag/commit/8443d5db470a04123c6b9ae73fc28b7efd078cdc))
* **search:** one wording for a short index, and the summary names both kinds ([008cbe3](https://github.com/nevenincs/vaultspec-rag/commit/008cbe3fb474f8c7abd32141ef3adb94501c9722))
* share the manifest admission gate and the feedback refusal ([dd5c763](https://github.com/nevenincs/vaultspec-rag/commit/dd5c763e158ab093e39792c5aba6bc8b48308a79))
* state a rejection rule once instead of once per caller ([7fd4003](https://github.com/nevenincs/vaultspec-rag/commit/7fd40032a06fbedd51e6823f9c697d926d6bcaa1))
* **status:** drop a branch that returned what its fallback already returned ([b5fa9bb](https://github.com/nevenincs/vaultspec-rag/commit/b5fa9bb6e20e89be065178f84d184bf74bbf511d))
* **store:** write a point's vectors under the names the collection was created with ([77b58fa](https://github.com/nevenincs/vaultspec-rag/commit/77b58fa15f92c2e7e58709f7472d7cacd7cea55f))
* take the document filter's keys from the schema that declares them ([28152ec](https://github.com/nevenincs/vaultspec-rag/commit/28152ec2e442f3669965a67979bbee46b2ced830))
* **tests:** drop workstation paths from jobs interface fixtures ([6d39d2a](https://github.com/nevenincs/vaultspec-rag/commit/6d39d2a226f33c45cadf4f7bb53cca7b1c31f741))
* **tests:** green the two platform-blind tests and the markdown gate ([544f9b6](https://github.com/nevenincs/vaultspec-rag/commit/544f9b69b7a03f0e24f8a19f0a7a1cadb54025bb))
* **tests:** identify the stub daemon by its token, not by the runner's argv ([be440f8](https://github.com/nevenincs/vaultspec-rag/commit/be440f83ab141d578c0ce274dbec07bcaa17c8b1))
* **tests:** restore the orphan-reap timeout headroom ([122b2a9](https://github.com/nevenincs/vaultspec-rag/commit/122b2a92919eadaaa422b3e26233cd7fa1fde28f))
* **tests:** size the pinned integration CUDA ceiling as an absolute figure ([f31e6e1](https://github.com/nevenincs/vaultspec-rag/commit/f31e6e1b7e1371d97135205dc2e28ae3a00b4d8e))
* **tests:** sort the import block that turned main red ([883e473](https://github.com/nevenincs/vaultspec-rag/commit/883e473e64bdc7b58dabac915f544f48ddf572c3))
* **tests:** stop a hard-killed pytest run from stranding its daemon ([835bc97](https://github.com/nevenincs/vaultspec-rag/commit/835bc976493b15c70bfe1c6417759c27fa11c1af))
* **tests:** use concurrent search context port ([e9ec517](https://github.com/nevenincs/vaultspec-rag/commit/e9ec517906e6ae664fd85b4270222b0e0f09b637))
* **tooling:** stop suppressing a dead-code finding that was correct ([4295740](https://github.com/nevenincs/vaultspec-rag/commit/4295740fa2a24a7e674f6e04c49992e41a066c71))
* **torch-config:** apply and remove share the writer that already existed ([5688cb0](https://github.com/nevenincs/vaultspec-rag/commit/5688cb0309b2f6420ee49fac987bac9709ff4d9a))


### Performance

* **client:** bound the loopback connect so a dead service reads as down fast ([9a949fe](https://github.com/nevenincs/vaultspec-rag/commit/9a949fe721da8a4a2d3ee7d2cb6d12f3eaef1fb0))
* **test:** count identifiers once instead of once per symbol ([571976d](https://github.com/nevenincs/vaultspec-rag/commit/571976d6d5bf8882b2d8c91abba89640860f8cbc))
* **test:** run the fast tier in parallel ([718740c](https://github.com/nevenincs/vaultspec-rag/commit/718740c08ae40427a03cced9d8ea68864fb81869))
* **tests:** cap health-poll backoff at 1s to bound readiness overshoot ([6816301](https://github.com/nevenincs/vaultspec-rag/commit/681630197e6c2bb0ee33bbe1072a5e858c1e2938))
* **tests:** keep the subprocess-GPU lane out of the in-process GPU lane ([18f8f42](https://github.com/nevenincs/vaultspec-rag/commit/18f8f42bccb9a29513bfa5039ffd0cabce9e44d8))
* **tests:** probe loser-daemon ports concurrently ([2b213ba](https://github.com/nevenincs/vaultspec-rag/commit/2b213ba373a5996119a9fae0ed15b3c376c04e15))
* **tests:** stop the jobs interface tests paying for waits nothing is doing ([ba298cc](https://github.com/nevenincs/vaultspec-rag/commit/ba298cc5bcaedef2da3af6fffdc4e19385fccf9d))

## [0.3.11](https://github.com/nevenincs/vaultspec-rag/compare/vaultspec-rag-v0.3.10...vaultspec-rag-v0.3.11) (2026-07-26)


### Bug Fixes

* **cli:** drop the sys re-export kept only for a test rebind ([57232be](https://github.com/nevenincs/vaultspec-rag/commit/57232be1b9cca726b99e41f57075976ac2313526))
* **client:** say so when a request bound falls back to its default ([d5dee89](https://github.com/nevenincs/vaultspec-rag/commit/d5dee896f32cc77be1ea9b765eac83ed7858c707))
* **cli:** fail a stop that could not stop the service ([14a4369](https://github.com/nevenincs/vaultspec-rag/commit/14a43691ddf702aa3749bf70a925d72979013c15))
* **config:** reject a bad setting at startup instead of ignoring or crashing ([9f97f85](https://github.com/nevenincs/vaultspec-rag/commit/9f97f85d386576084810d2559eb84985e5b25b0c))
* **index:** report no progress on the JSON path ([269ce2a](https://github.com/nevenincs/vaultspec-rag/commit/269ce2a28c77ee143c05cc7af5af313311b0bdf1))
* **logging:** a mistyped level must not make the service noisier ([4d2ec35](https://github.com/nevenincs/vaultspec-rag/commit/4d2ec35ee7d940dde5036df29084f1df397ab980))
* **service:** clear the degraded verdict once a later run succeeds ([63cfc84](https://github.com/nevenincs/vaultspec-rag/commit/63cfc84c4a6c133f28149490adec03ffc7f912cd))
* **service:** read a live higher-privilege daemon as alive, not dead ([045497d](https://github.com/nevenincs/vaultspec-rag/commit/045497dbbe15a60c9bac11b87b7e5c1bc7aead47))
* **service:** report the real watcher state from updates start ([0c97a80](https://github.com/nevenincs/vaultspec-rag/commit/0c97a80f076023ef08831b8eba0d12896bf9904e))
* **watcher:** stop reporting a running job as a failed one ([1cec6dd](https://github.com/nevenincs/vaultspec-rag/commit/1cec6dd44ca5d836baecfdcbadc858f99559fc58))

## [0.3.10](https://github.com/nevenincs/vaultspec-rag/compare/vaultspec-rag-v0.3.9...vaultspec-rag-v0.3.10) (2026-07-26)


### Features

* **config:** give every setting a canonical home and an env override ([236d7da](https://github.com/nevenincs/vaultspec-rag/commit/236d7dae80ff34b2901e747f64a191ad6afad087))
* **indexer:** build a rebuild into its generation, then move the pointer ([42b057c](https://github.com/nevenincs/vaultspec-rag/commit/42b057c7b3e26360d054411eba41546a869ae23c))
* **indexer:** charge a generation build for the duplicate it holds ([974de5b](https://github.com/nevenincs/vaultspec-rag/commit/974de5b0d548a5305f1b59c95ebfbeb7a4fcc00d))
* **indexer:** compare published file breadth, not just point breadth ([1e86c35](https://github.com/nevenincs/vaultspec-rag/commit/1e86c3594946049c3e04a3b78fcf370ccf5b632b))
* **indexer:** give the indexed-path upsert collision its own type ([786d686](https://github.com/nevenincs/vaultspec-rag/commit/786d686d25239646b27c42962a6610dfb75726a8))
* **indexer:** report drift volume the circuit breaker cannot see ([536ea25](https://github.com/nevenincs/vaultspec-rag/commit/536ea2593cce8c6ca9158f3f901b604df591c31c))
* **indexer:** stamp covered file breadth on the incremental path too ([f82f3ea](https://github.com/nevenincs/vaultspec-rag/commit/f82f3ea2317234e46de42a479dcabb539b84cb08))
* **qdrant:** report a store carried across a server version change ([b264258](https://github.com/nevenincs/vaultspec-rag/commit/b2642588febd129cdf7908205399836b21ec60f5))
* **search:** report an index that is serving two encoding regimes ([069328d](https://github.com/nevenincs/vaultspec-rag/commit/069328def647da49ae2235c77d826e65bffe242b))
* **search:** warn when a code search answers over a truncated index ([cfbff06](https://github.com/nevenincs/vaultspec-rag/commit/cfbff066d74133aa2b5641749745a0c9f04e7801))
* **search:** warn when a publication covered fewer files than it names ([c928307](https://github.com/nevenincs/vaultspec-rag/commit/c928307357abb348f51df7043c2f6231bcae5fe3))
* **service:** gate a client on the release of the daemon it drives ([c6a9e09](https://github.com/nevenincs/vaultspec-rag/commit/c6a9e09d3e4f97d50a83eee6d8329b1e040088f4))
* **service:** say when an index was built by a different model ([18a6831](https://github.com/nevenincs/vaultspec-rag/commit/18a6831a432a10d248ed2eb74ca5584ff94aec9b))
* **storage:** carry a namespace's provenance across a copy, and into its archive ([1b62a0f](https://github.com/nevenincs/vaultspec-rag/commit/1b62a0f0b59d0e848dd1d986087c6e58b0b65807))
* **storage:** reclaim superseded code generations behind every gate ([f411886](https://github.com/nevenincs/vaultspec-rag/commit/f4118867ef4dda8c90f84941201090fa47a2b4a0))
* **storage:** record what produced a collection, and stop the manifest ([00b60be](https://github.com/nevenincs/vaultspec-rag/commit/00b60bee7de9a05e42a7ba160b739d3c0f1bca1c))
* **storage:** report generation debt in the survey response ([ad22698](https://github.com/nevenincs/vaultspec-rag/commit/ad22698301267d4b3bd8f4e0c7e6143319f083c9))
* **storage:** report superseded code generations in the survey payload ([aa3d382](https://github.com/nevenincs/vaultspec-rag/commit/aa3d3827808ab86b2299beba1f929714deedc57b))
* **storage:** run the generation reclaim from the scheduled cycle ([1de9f23](https://github.com/nevenincs/vaultspec-rag/commit/1de9f232ea5da6d36d9eaf32c07e618c90a14dd2))
* **store:** decide whether a root can afford a generation build ([331a178](https://github.com/nevenincs/vaultspec-rag/commit/331a178469e35625c27a7d4897e8e0b53095be03))
* **store:** decide which superseded generations are reclaimable ([9f0cce5](https://github.com/nevenincs/vaultspec-rag/commit/9f0cce567439fd9bc07c8d4b945075f44a03e549))
* **store:** judge a collection before trusting it, on the path every ([e43ea88](https://github.com/nevenincs/vaultspec-rag/commit/e43ea88a0d98b5b1b1c02d0df260c3bbecd3f5f0))
* **store:** keep an unreadable served pointer apart from an absent one ([15bcbe7](https://github.com/nevenincs/vaultspec-rag/commit/15bcbe7ad021cdc35886975c85a1b4d699415b78))
* **store:** let a code operation target a generation collection ([8fcef8b](https://github.com/nevenincs/vaultspec-rag/commit/8fcef8b9634d352f79bde2c605004f14ecff298c))
* **store:** name each rebuild generation so a name is never reused ([65e536a](https://github.com/nevenincs/vaultspec-rag/commit/65e536ada836053ff080b9444b6ce7fd3bcb9a1e))
* **store:** record a generation's breadth before it becomes the served one ([2d70f2b](https://github.com/nevenincs/vaultspec-rag/commit/2d70f2b419df0ea1ae8b560b0924541605675c2a))
* **store:** resolve code reads through a per-root served pointer ([d39be00](https://github.com/nevenincs/vaultspec-rag/commit/d39be00cdebe60b947516126be554a897b1a5632))
* **survey:** decide when a superseded generation may be dropped ([72dd25c](https://github.com/nevenincs/vaultspec-rag/commit/72dd25c4e248a1808657f1ecc2639efb4ac1e51b))
* **survey:** report each root's served collection and generation debt ([4b00e85](https://github.com/nevenincs/vaultspec-rag/commit/4b00e85ae0c272fdcc56c812099d0a6298b06656))
* **tools:** make the module-length gate fail, and record what it still owes ([8e75062](https://github.com/nevenincs/vaultspec-rag/commit/8e750623848aacf50e5e4d2fcf9abd16d424f580))


### Bug Fixes

* **cli:** collapse the duplicated store-format degradation finding ([b451762](https://github.com/nevenincs/vaultspec-rag/commit/b4517626d42897ce5633e17538eb83fd80d6e54c))
* **cli:** export run_cli so the merged entry point resolves ([48eb2c9](https://github.com/nevenincs/vaultspec-rag/commit/48eb2c93fdd6bccfdb2483eebadfd4492340e8a1))
* **cli:** repoint the start path's qdrant imports, and share one success envelope ([b26b7b9](https://github.com/nevenincs/vaultspec-rag/commit/b26b7b9663efe183d19da2e07c6b3f0e61a046bb))
* **commands:** repoint callers at the modules that define the names ([5893f42](https://github.com/nevenincs/vaultspec-rag/commit/5893f42c24171094a1881e0d731dc090e3f14d71))
* finish repointing callers off the emptied package surfaces ([34b5a5a](https://github.com/nevenincs/vaultspec-rag/commit/34b5a5a9a09b2eb97ab86a6401f1958d57ae390c))
* **indexer:** compare live breadth against the count a publication claimed ([00ab3ef](https://github.com/nevenincs/vaultspec-rag/commit/00ab3ef39aa45912a967e11a1580194ea471f47d))
* **indexer:** give document runs the activity clock and index events ([097e04f](https://github.com/nevenincs/vaultspec-rag/commit/097e04fd0193271ebf6e8c7aa92b95e5b8eff01c)), closes [#267](https://github.com/nevenincs/vaultspec-rag/issues/267)
* **indexer:** stop an unattended run destroying the index it serves ([f96913a](https://github.com/nevenincs/vaultspec-rag/commit/f96913aebdf1ed703dba0edf2490651a60c6cc68))
* **indexer:** stop the escalation log naming only the absent-collection case ([1f24c3a](https://github.com/nevenincs/vaultspec-rag/commit/1f24c3af435b70680a3136c597b5beab14306669))
* **indexer:** supersede a racing path instead of failing the whole run ([0102d7b](https://github.com/nevenincs/vaultspec-rag/commit/0102d7b93c67d017b21e586e791032634dc1e077))
* **mcp:** resolve the project root the tool schema promises is optional ([e7a827d](https://github.com/nevenincs/vaultspec-rag/commit/e7a827def72e13c28861eefe2eaa79417e5daa50))
* **merge:** drop branch-side callers of implementations that did not land ([8a7d934](https://github.com/nevenincs/vaultspec-rag/commit/8a7d934be804f26b77d8c884c2706d6d4fe754bf))
* **merge:** keep main's storage reclaim and mcp root contract ([583e706](https://github.com/nevenincs/vaultspec-rag/commit/583e7068b74c9575ece6c0b91605c2e842d38ac4))
* **merge:** restore the two files a bad pipe mangled ([c6fd625](https://github.com/nevenincs/vaultspec-rag/commit/c6fd625895a8cc235b54fe5be41842bdf358d561))
* **qdrant:** refuse an incompatible store instead of quarantining into it ([a839cfc](https://github.com/nevenincs/vaultspec-rag/commit/a839cfcd2b2c7c6a8ba7606fdb96f52441d4a549))
* resolve code collections through the pointer, not by derivation ([11147c4](https://github.com/nevenincs/vaultspec-rag/commit/11147c4a1745d555d23f9c56bf9d13ac4a37c43c))
* **search:** give the breadth shortfall one projection and one voice ([29dece4](https://github.com/nevenincs/vaultspec-rag/commit/29dece498817efe2b98bb287ff940221d71062f3))
* **search:** make a path filter narrow by location instead of exact identity ([a63ba4f](https://github.com/nevenincs/vaultspec-rag/commit/a63ba4fd52beb85d2e70a5f8368aea60be8a40a3))
* **search:** make the filter builder static and pass the notes sink ([0cebf5b](https://github.com/nevenincs/vaultspec-rag/commit/0cebf5bbf46685094e5db6518e7e9e466c5b79ac))
* **search:** report a busy local index instead of failing silently ([2504e8f](https://github.com/nevenincs/vaultspec-rag/commit/2504e8f5435477e2a54bcca14f124dd37daa0a91))
* **service:** gate the CLI data plane on the release, not only the MCP ([edc4b04](https://github.com/nevenincs/vaultspec-rag/commit/edc4b047ea10a8c090332a3b631b894d15e2f169))
* state the no-swallow constraint instead of pointing at it ([44f0ed4](https://github.com/nevenincs/vaultspec-rag/commit/44f0ed44030ea8834addcb3bb8f0130d52c81d8a))
* **storage:** never reclaim a namespace a live indexing run is writing ([d727098](https://github.com/nevenincs/vaultspec-rag/commit/d72709852fb83844e33d6b9f2ed860a949931d02)), closes [#271](https://github.com/nevenincs/vaultspec-rag/issues/271)
* **tests:** clear the strict-type errors on the reindex contract helper ([ea4a660](https://github.com/nevenincs/vaultspec-rag/commit/ea4a660e1c337e387f5a463a1548e34f39dbd9b1))
* **tests:** import the install reports from the module defining them ([d79927e](https://github.com/nevenincs/vaultspec-rag/commit/d79927e410e4814536a1752c4d90358bb4400fc9))
* **tests:** restore the CLI data-plane tests after the release gate landed ([a3949c4](https://github.com/nevenincs/vaultspec-rag/commit/a3949c4f49d39ee6fd62dae8fa5b1fcc6583347b))
* **tests:** restore the reclaim tests a bad merge resolution dropped ([8e096b9](https://github.com/nevenincs/vaultspec-rag/commit/8e096b9b6368b285004a830abf28a3180ee1c5a6))
* **tools:** make the citation gate see the shapes it reported clean on ([493741d](https://github.com/nevenincs/vaultspec-rag/commit/493741d4cf32836b664e81059a410b6a986a19f4))
* **tools:** make the citation gate see the shapes it was reporting clean on ([80d0f43](https://github.com/nevenincs/vaultspec-rag/commit/80d0f43f2fcd89100ecbdff671665e17e10a9696))
* **tools:** match prose per block, and catch a rule citation by position ([cd5243c](https://github.com/nevenincs/vaultspec-rag/commit/cd5243c48b84da7fcac3279bc7e07e1a71cac4bf))
* **types:** clear the strict-type errors on the data-plane gate and sidecar reads ([d1587e0](https://github.com/nevenincs/vaultspec-rag/commit/d1587e0a8c766477e53ce91ef2cb320645bc350e))
* **vault:** quote bare date fields so the plan parser can read them ([87d03f6](https://github.com/nevenincs/vaultspec-rag/commit/87d03f60544048c1d1026fd860087d34f3d6345d))

## [0.3.9](https://github.com/nevenincs/vaultspec-rag/compare/vaultspec-rag-v0.3.8...vaultspec-rag-v0.3.9) (2026-07-25)


### Bug Fixes

* **cli:** answer an interrupt taken before the command exists ([ad1ac7d](https://github.com/nevenincs/vaultspec-rag/commit/ad1ac7db56660768fe1ee9a7543613f063acda4a))


### Performance

* **package:** resolve __version__ on first access instead of at import ([88d891f](https://github.com/nevenincs/vaultspec-rag/commit/88d891f701c6324f9887ddf718819534e9176a84))

## [0.3.8](https://github.com/nevenincs/vaultspec-rag/compare/vaultspec-rag-v0.3.7...vaultspec-rag-v0.3.8) (2026-07-24)


### Features

* **cli:** make a degraded server status explain itself ([a86a84e](https://github.com/nevenincs/vaultspec-rag/commit/a86a84e4e5b83c0600b417425d48eee83f54ffd4))


### Bug Fixes

* **cli:** distinguish a queued admission wait from work in progress ([e0dde70](https://github.com/nevenincs/vaultspec-rag/commit/e0dde70bce4934966f21a4c72dabbe6ae37c0411))
* **cli:** never report a satisfied outcome the command could not establish ([c5887c5](https://github.com/nevenincs/vaultspec-rag/commit/c5887c57e0e23ea9695789199444d20264d1000c))
* **cli:** refuse to reap a live port holder, and let the safety guards run ([9ca53d5](https://github.com/nevenincs/vaultspec-rag/commit/9ca53d5e4121ce32d2e8f8ad6fa211c5c2491661))
* **cli:** report what long-running commands are doing, and stop misreporting outcomes ([5644582](https://github.com/nevenincs/vaultspec-rag/commit/56445827220e5251d180da667300f727d331da7a))
* **index:** admit jobs under one derived ceiling, and back vault's payload indexes ([b11abac](https://github.com/nevenincs/vaultspec-rag/commit/b11abac799edbcad8ab6f460c631139dcdae5ef0))
* **index:** check each write target's volume as its own condition ([5cc40f1](https://github.com/nevenincs/vaultspec-rag/commit/5cc40f1e2faf6b1ebfebb21d3ba1fefcadad5773))
* **index:** measure the store's volume, in units, once ([80ab740](https://github.com/nevenincs/vaultspec-rag/commit/80ab740d50da57c89d749e6910e9c2613669a065))
* **index:** restore the disk-floor ladder and pin its ordering ([f2d409a](https://github.com/nevenincs/vaultspec-rag/commit/f2d409a2b353811924d02e7bed5a588c9f0657ed))
* **index:** size the disk floor to the host, not to the run ([1b79350](https://github.com/nevenincs/vaultspec-rag/commit/1b7935058a2b8bad1db9da07a5ebe3512afda64c))
* **server:** promote the two search timing phases that a reshape left behind ([1ef5d03](https://github.com/nevenincs/vaultspec-rag/commit/1ef5d03052ebc9da3fc191ab1d6cf35cc912ae03))
* **service:** bind the CLI serving verdict to the service's own, and stop a bool suppressing a degradation ([c17b2ca](https://github.com/nevenincs/vaultspec-rag/commit/c17b2cafbdfaf6a19a8f69a44281a276e198b431))

## [0.3.7](https://github.com/nevenincs/vaultspec-rag/compare/vaultspec-rag-v0.3.6...vaultspec-rag-v0.3.7) (2026-07-24)


### Features

* **indexer:** charge each index job its own forward peak, net of the resident baseline (P03) ([c212a8e](https://github.com/nevenincs/vaultspec-rag/commit/c212a8e890f423c7d0f5874c6c35e52921163efe))
* **indexer:** derive the CUDA ceiling from device capacity (P02) ([4a52c6c](https://github.com/nevenincs/vaultspec-rag/commit/4a52c6c3319ee50680a1b3efc361b2e4f7648254))
* **indexer:** encode-seam donor vector reuse by point id ([820c4b7](https://github.com/nevenincs/vaultspec-rag/commit/820c4b782f70193590327dbf2a8648bdf5d39995))
* **indexer:** give documents a dedicated encode sub-batch (P01) ([2889f78](https://github.com/nevenincs/vaultspec-rag/commit/2889f78feffc8cba1f92a9a067d1325beafb1e31))
* **indexer:** overlap document upserts with encode through the slice writer ([8789003](https://github.com/nevenincs/vaultspec-rag/commit/8789003093a745b5ba9ce6a7d3a0e24886df7bf5))
* **indexer:** overlap vault encode with storage via a single writer thread ([25f73a6](https://github.com/nevenincs/vaultspec-rag/commit/25f73a6e180a39fa49cb78a145890963bf12f0dd))
* **index:** per-job GPU-lock-wait telemetry and conservative flush cadences ([c89b7b5](https://github.com/nevenincs/vaultspec-rag/commit/c89b7b50220e008086af784758af4e0397d06244))
* **jobs:** single machine-wide admission slot for encode-bearing index jobs ([91a843e](https://github.com/nevenincs/vaultspec-rag/commit/91a843ed13069956ec4e042f4a6340c7e7fcaa6c))
* **service-quiesce:** pause/resume localhost routes (P03.S07) ([bf439cd](https://github.com/nevenincs/vaultspec-rag/commit/bf439cd7393d8abca1a794d931e4c87cc4a84532))
* **service-quiesce:** server pause/resume CLI verbs and guard tests (P03.S08-S09) ([74d3e03](https://github.com/nevenincs/vaultspec-rag/commit/74d3e0317d82369e73b2c52c70616a25b97aee14))
* **service-quiesce:** torch-free QuiesceGate + protected-aware token hold (P01) ([9addcf5](https://github.com/nevenincs/vaultspec-rag/commit/9addcf5e7a34d7b00f0ff031c2f545e6e1fc89fe))
* **service-quiesce:** wire process-global gate into service, jobs, search (P02) ([b2209c5](https://github.com/nevenincs/vaultspec-rag/commit/b2209c51e2b4e4c83498ce9a2ef00205e9963870))
* **store:** explicit rebuild-path ingest wait policy with an applied-points barrier ([11a6ee5](https://github.com/nevenincs/vaultspec-rag/commit/11a6ee57dd4df2f39060bdeaa95ba63957e654d1))


### Bug Fixes

* **gates:** clear type and format drift inherited from origin ([3313acc](https://github.com/nevenincs/vaultspec-rag/commit/3313acce511d7cf9d736a50cc5ce7f37f6e64d09))
* **index:** derive CUDA ceiling from free memory; drop corpus cuda rejection ([58d6eb6](https://github.com/nevenincs/vaultspec-rag/commit/58d6eb6527001b03b92a32cbb22c8cb999d28007))
* **indexer:** incremental runs stop trusting carried evidence for a vanished collection ([63e93d5](https://github.com/nevenincs/vaultspec-rag/commit/63e93d5b2917c7991765ff5170d9bc7b93ee2f2b))

## [0.3.6](https://github.com/nevenincs/vaultspec-rag/compare/vaultspec-rag-v0.3.5...vaultspec-rag-v0.3.6) (2026-07-24)


### Bug Fixes

* **cli:** count a POSIX zombie as reaped so --orphans works on Linux ([3d91843](https://github.com/nevenincs/vaultspec-rag/commit/3d91843c90dbc1a54d2382de85fa87ab5bf35080))
* **reap:** match qdrant image, not the whole cmdline, on POSIX ([9caecf7](https://github.com/nevenincs/vaultspec-rag/commit/9caecf75acdbcc07928482ed79d3854507001b2d))
* **tests:** derive the reap witness count from the platform ([c6ff1d2](https://github.com/nevenincs/vaultspec-rag/commit/c6ff1d2605a3b16f3ca00dcdb116da1ffae567fa))

## [0.3.5](https://github.com/nevenincs/vaultspec-rag/compare/vaultspec-rag-v0.3.4...vaultspec-rag-v0.3.5) (2026-07-23)


### Features

* **cli:** add opt-in `server stop --orphans` reap of race-loser daemons ([eb669da](https://github.com/nevenincs/vaultspec-rag/commit/eb669da3ecf0129ed25e4b5b54014380091e229b))
* **indexer:** bound document units end to end and epoch the bound ([2b44d24](https://github.com/nevenincs/vaultspec-rag/commit/2b44d249d2461916216580e2c02d7162013b3ccd))
* **server:** carry a determinate model-load count in startup progress ([d2758f9](https://github.com/nevenincs/vaultspec-rag/commit/d2758f9a787b3b4e47e601c7351cc2cb6c897f3b))
* **server:** show the cold-start stage in the start spinner ([034a0dd](https://github.com/nevenincs/vaultspec-rag/commit/034a0dd40c77fbcb7f837b14a01b4b1b8e7994d1))


### Bug Fixes

* **cli:** close the reap's cross-config port-holder gap (P04 HIGH) ([98ad444](https://github.com/nevenincs/vaultspec-rag/commit/98ad44417dacc3450a4f0c0625e49551ba3213b2))
* **cli:** land the console-safe pair-aware orphan reap (release-critical) ([c07ad19](https://github.com/nevenincs/vaultspec-rag/commit/c07ad191aec6a7a86000fea791840fe62ad025d1))
* **cli:** make the orphan reap pair-aware and console-safe; prove its safety ([2b40ae7](https://github.com/nevenincs/vaultspec-rag/commit/2b40ae7176c9d6bfb97a2c9b9f2fcfc7d0d443ba))
* **indexer:** bound hook-emitted units and enforce the CUDA ceiling on demand ([2916870](https://github.com/nevenincs/vaultspec-rag/commit/29168706b189b03f5a7886055df24675c7295669))
* **indexer:** make chunk identifiers unique by construction ([5ec437c](https://github.com/nevenincs/vaultspec-rag/commit/5ec437c948527b479f1d5406a5edd82db35f1fa5))
* **server:** advance the startup model-load count to its terminal value ([91e7ebd](https://github.com/nevenincs/vaultspec-rag/commit/91e7ebdf17b1bc9034c11b6bc2fc3e0bb687f175))
* **server:** guarantee daemon self-exit on a failed singleton claim ([57bdee8](https://github.com/nevenincs/vaultspec-rag/commit/57bdee8fdda0c4e003061ba22c5430be7750a885))
* **store:** bound retried operations by wall clock and bind the guard to call sites ([e9d9d9d](https://github.com/nevenincs/vaultspec-rag/commit/e9d9d9d06370e2d518ae21ed46c59f998b62a620))
* **store:** let a store failure outrank a cancel, and cut retry complexity ([202635e](https://github.com/nevenincs/vaultspec-rag/commit/202635eef0ec4c30ab973e0e88b8668860b029b7))
* **store:** retry every replay-safe store operation, not just the upsert ([e7a7cc7](https://github.com/nevenincs/vaultspec-rag/commit/e7a7cc7ebf2ed916cf412794d72770f45a0e704d))
* **tests:** accept the console-group kwarg in the shutdown-log stubs ([17c341b](https://github.com/nevenincs/vaultspec-rag/commit/17c341be5c9061f0d4eb0dfa38568001418a4036))
* **tests:** mark subprocess-script absolute imports as gate-exempt ([70871df](https://github.com/nevenincs/vaultspec-rag/commit/70871df7eec95e5dc1dad4a2de3dc6ebf5d1fd53))
* **tests:** resolve absolute-imports gate violations for real ([555de15](https://github.com/nevenincs/vaultspec-rag/commit/555de1508d253d7c222a6b71611a7a9855c63465))
* **tests:** restore the absolute-imports fix I reverted in 11c0eb2b ([2a90561](https://github.com/nevenincs/vaultspec-rag/commit/2a90561f0423e3b6d68452380d8acb97a5aa8ba1))
* **tests:** satisfy ty's None-narrowing on machine-discovery reads ([e14d49d](https://github.com/nevenincs/vaultspec-rag/commit/e14d49df0a7a3d495a223ee9b3ad87b7076f3d07))
* **tests:** use the console-group kwarg in the shutdown-log stubs ([b41ec8f](https://github.com/nevenincs/vaultspec-rag/commit/b41ec8fafcefd82bdda2bb8bad4fe6e816c149dc))
* **tests:** wrap the subprocess-script imports under 88 cols ([0a9e292](https://github.com/nevenincs/vaultspec-rag/commit/0a9e2928940ed7334e958a28b04b0e924204823d))
* **vault:** drop the code-span-internal space triggering MD038 ([8bdb709](https://github.com/nevenincs/vaultspec-rag/commit/8bdb709dba8d08b4fe2cc9d56b0f82cf43f610d5))

## [0.3.4](https://github.com/nevenincs/vaultspec-rag/compare/vaultspec-rag-v0.3.3...vaultspec-rag-v0.3.4) (2026-07-23)


### Features

* **adapters:** expose document and combined domains ([f5c04db](https://github.com/nevenincs/vaultspec-rag/commit/f5c04db8371f8ee3da5486ff9f7f48831d477ba7))
* **api:** add closed public source parser ([d37ac2e](https://github.com/nevenincs/vaultspec-rag/commit/d37ac2e1ca15d82ed0ac7d93d6c637ebceb6af8d))
* **api:** add document and combined search facades ([26fe016](https://github.com/nevenincs/vaultspec-rag/commit/26fe016925792dd57516442f39de68cd973c81a2))
* **api:** add model-free document scan ([17cc0cb](https://github.com/nevenincs/vaultspec-rag/commit/17cc0cb0bc6acf9e2dc8de96e30b0355df633cd4))
* **api:** export document and combined facades ([eda3e3e](https://github.com/nevenincs/vaultspec-rag/commit/eda3e3e8c3a8fd351d7852c06891f756ef4df075))
* **api:** expose document and combined search ([52ae58d](https://github.com/nevenincs/vaultspec-rag/commit/52ae58de85f39812f30bd9ed0740cc6bb43f0917))
* **cli:** add exact job lifecycle controls ([771a626](https://github.com/nevenincs/vaultspec-rag/commit/771a626ec1e07758bf9148818932c10d5d8c364d))
* **client:** add typed job control transport ([33a39e2](https://github.com/nevenincs/vaultspec-rag/commit/33a39e20de3bb93ad9d81635b8897d6792666db1))
* **client:** carry managed log source ([e18ef43](https://github.com/nevenincs/vaultspec-rag/commit/e18ef433ba647bbcdaf2c8831d60498a70fc637c))
* **client:** fail service calls with the discovery evidence ([26b9e3a](https://github.com/nevenincs/vaultspec-rag/commit/26b9e3ab000ad760caa5a24fc11969ea587fa0cf))
* **cli:** register singular job command group ([a6829d3](https://github.com/nevenincs/vaultspec-rag/commit/a6829d3853889555f970ac3f2f90e5c96fed5f96))
* **cli:** unify live and offline logs ([8e62806](https://github.com/nevenincs/vaultspec-rag/commit/8e628064ca8fc4a9bcddb51c69e4d25a861558de))
* **config:** bound managed job lifecycle ([720d3c0](https://github.com/nevenincs/vaultspec-rag/commit/720d3c079f8fbb6f055a6d5465140e3c8f19fc2a))
* **config:** define bounded index policy ([ec148f6](https://github.com/nevenincs/vaultspec-rag/commit/ec148f6b504849a0a67cf836f963f9afdf92ce73))
* **config:** define managed log policy ([75487ba](https://github.com/nevenincs/vaultspec-rag/commit/75487ba93f7fba6a7fb0bfbd01ae99781634f487))
* **discovery:** authenticate pointer mutation ([559b411](https://github.com/nevenincs/vaultspec-rag/commit/559b41111721d3bf8b0fed273bc064af921d4d7e))
* **discovery:** build self-healing owner snapshots ([e8dc94c](https://github.com/nevenincs/vaultspec-rag/commit/e8dc94c619c616f2df2c4e330eeda3f3b171b4a2))
* **discovery:** resolve the singleton into a typed verdict ([8caee83](https://github.com/nevenincs/vaultspec-rag/commit/8caee836fda4cf8e6ae926d090a866ff77119970))
* **document:** clean document storage independently ([02a2027](https://github.com/nevenincs/vaultspec-rag/commit/02a20272716f4f64b58d7f16d55e08d3b8bbebef))
* **document:** define native content models ([91cc2b1](https://github.com/nevenincs/vaultspec-rag/commit/91cc2b1d4b036e3e788cbdf24ab98828bca56d65))
* **document:** derive stable point identities ([8cc7383](https://github.com/nevenincs/vaultspec-rag/commit/8cc73831169a3bea969f92180f48107f836aeacf))
* **document:** publish independent metadata ([fda8564](https://github.com/nevenincs/vaultspec-rag/commit/fda8564fc072e3fd2755bd06ea8fa0c05947e7a6))
* **index:** add durable run liveness policy ([51c3594](https://github.com/nevenincs/vaultspec-rag/commit/51c3594dd2865cab95fb69a5d7d69be3db059ac7))
* **index:** add transactional run ledger ([34fb194](https://github.com/nevenincs/vaultspec-rag/commit/34fb19416c2bb4b12fd3c666b60572152279ed47))
* **index:** apply memory ceilings and peak reporting to every index job ([958f7a4](https://github.com/nevenincs/vaultspec-rag/commit/958f7a46bf49c0dc144b9cb5d38a05381a36c566))
* **index:** apply the memory-budget checkpoint to document indexing ([c43189a](https://github.com/nevenincs/vaultspec-rag/commit/c43189ad27df2f56b728b1bc479a911c19d268b5))
* **index:** bound interruptible preprocessing workers ([5b4f20f](https://github.com/nevenincs/vaultspec-rag/commit/5b4f20fcbb2b683011e0e5c9016103a64efe0c8b))
* **index:** bound sparse CUDA output lifetime ([ed8a53d](https://github.com/nevenincs/vaultspec-rag/commit/ed8a53d2b878296f718691158c2b0e4634dcb688))
* **index:** bridge segments to run checkpoints ([7f0b6ca](https://github.com/nevenincs/vaultspec-rag/commit/7f0b6ca14b35fa5a32bf22a9ef4d4a79965b0df0))
* **index:** checkpoint document generations ([8dda142](https://github.com/nevenincs/vaultspec-rag/commit/8dda142e446100c9a2645f7c7ff2cbc0ce5ed269))
* **index:** checkpoint full code segments ([4f29f22](https://github.com/nevenincs/vaultspec-rag/commit/4f29f22571673b553e843f130526d520c5b75872))
* **index:** classify content ownership deterministically ([b4145fc](https://github.com/nevenincs/vaultspec-rag/commit/b4145fc60b8028e13ddb2227d17ae718dd926c8d))
* **index:** close checkpoint compatibility contract ([8452a3e](https://github.com/nevenincs/vaultspec-rag/commit/8452a3ed9f4d52daf5942b8d7d1fc8e4a8627e15))
* **index:** complete bounded document ingestion ([c6d6e97](https://github.com/nevenincs/vaultspec-rag/commit/c6d6e97109b31fcd949da368be196725628ef4af))
* **index:** define content policy vocabulary ([d97f395](https://github.com/nevenincs/vaultspec-rag/commit/d97f39552db4c9339a245e6f4c1fa110f9b48674))
* **index:** define explicit file outcomes ([f4af5ef](https://github.com/nevenincs/vaultspec-rag/commit/f4af5ef602da711e3e9376192abd1b23eaf64047))
* **index:** define independent support profiles ([4c9fe8c](https://github.com/nevenincs/vaultspec-rag/commit/4c9fe8cf5dddc95b50fe463669f7d8a2fcfbaf73))
* **index:** define ordered content routes ([c42b998](https://github.com/nevenincs/vaultspec-rag/commit/c42b9988add1624b935d649f5e418a62314326e5))
* **index:** define typed resilience outcomes ([3d3288e](https://github.com/nevenincs/vaultspec-rag/commit/3d3288e0a74f6c12caee6f3eec66346472e46935))
* **index:** derive per-kind policy signatures ([3dab032](https://github.com/nevenincs/vaultspec-rag/commit/3dab03215800688ab64802be24a2bd5590040b4d))
* **index:** enforce admitted memory budgets ([72ed907](https://github.com/nevenincs/vaultspec-rag/commit/72ed907de6a4c73857cb526476a245d67420df8a))
* **index:** enforce code support admission ([eedc35a](https://github.com/nevenincs/vaultspec-rag/commit/eedc35a792c004bd37832df92275230511159c1f))
* **indexer:** checkpoint streaming GPU slices ([3b97918](https://github.com/nevenincs/vaultspec-rag/commit/3b97918997774e1b0211d6bbc5872d5d4143762e))
* **indexer:** control code indexing pipeline ([a3282d8](https://github.com/nevenincs/vaultspec-rag/commit/a3282d809bdf36d306d12e9b528cc414ef548411))
* **indexer:** control vault indexing phases ([d96b58e](https://github.com/nevenincs/vaultspec-rag/commit/d96b58e6ee4d0957222e6307097c7b57ec58b262))
* **indexer:** protect code publication spans ([913525d](https://github.com/nevenincs/vaultspec-rag/commit/913525de1d40c4bab7239bf28995871bba924007))
* **index:** expose resource admission dimensions ([2b4ebff](https://github.com/nevenincs/vaultspec-rag/commit/2b4ebff7908654f2d05f3c2c41e8349917ee0075))
* **index:** project canonical resilience state ([c5a8ab8](https://github.com/nevenincs/vaultspec-rag/commit/c5a8ab8edd85ccc6ba92de3a978146b38d79c028))
* **index:** publish resumable code generations ([27d2eaf](https://github.com/nevenincs/vaultspec-rag/commit/27d2eafc5862337c6e81a3f6ec7df95f20552a44))
* **index:** reconcile content routes safely ([8e6c211](https://github.com/nevenincs/vaultspec-rag/commit/8e6c2114e3054a0f114c68e57bf068aa4ba7b868))
* **index:** resolve immutable index policy ([bb3d320](https://github.com/nevenincs/vaultspec-rag/commit/bb3d320855970be900c63d5a216626f0525ec590))
* **index:** restore checkpoint compatibility contract ([e1f2129](https://github.com/nevenincs/vaultspec-rag/commit/e1f2129be1f99bd69674013715c84e22c88538ef))
* **index:** resume code finalization phases ([7131cd0](https://github.com/nevenincs/vaultspec-rag/commit/7131cd0a61bda94c718c3eca64147c47d3238175))
* **index:** resume incomplete clean generations ([fe3266a](https://github.com/nevenincs/vaultspec-rag/commit/fe3266a1a462c69496dff979fe6b910f428002e2))
* **index:** resume scoped code generations ([d054300](https://github.com/nevenincs/vaultspec-rag/commit/d054300ef35f5618ce111c3fbec78b6e5a0b91cd))
* **index:** resume unscoped code generations ([c529c9c](https://github.com/nevenincs/vaultspec-rag/commit/c529c9c9d300d05d5b429b665d3408ddad797040))
* **index:** unify checkpoint safe points ([cd4871a](https://github.com/nevenincs/vaultspec-rag/commit/cd4871a656478c622a562755727ce94163feacf4))
* **index:** version preprocessing ownership schema ([f676892](https://github.com/nevenincs/vaultspec-rag/commit/f67689267c376e34e77cec9efa94164c04f34603))
* **jobs:** add bounded exact job manager ([d02a4bb](https://github.com/nevenincs/vaultspec-rag/commit/d02a4bb120be40596577f6c4531315f8acdab16b))
* **jobs:** add cooperative run control ([89b336c](https://github.com/nevenincs/vaultspec-rag/commit/89b336c2aa572b10e31355bddb2691a1fdd4effe))
* **jobs:** define canonical job resources ([297927b](https://github.com/nevenincs/vaultspec-rag/commit/297927b2408dffb856c067f29ae4cf4bda9dddb8))
* **jobs:** enforce lifecycle transitions ([77c4bee](https://github.com/nevenincs/vaultspec-rag/commit/77c4bee0011e3b2de034c8f1815233c2f0a66d5a))
* **jobs:** isolate document retry and admission ([0ce5527](https://github.com/nevenincs/vaultspec-rag/commit/0ce5527e2ed09a9d4a4dc13b1a29ab4a2f203017))
* **jobs:** make lifecycle transitions deterministic ([29b5fbc](https://github.com/nevenincs/vaultspec-rag/commit/29b5fbccfe15633a67c3519f108340e9f7afbb18))
* **jobs:** own indexing attempt dispatch ([a898d6b](https://github.com/nevenincs/vaultspec-rag/commit/a898d6b55effc76b9bc543fabbbf468b77279818))
* **jobs:** own managed job admission ([22cd1d4](https://github.com/nevenincs/vaultspec-rag/commit/22cd1d49e6f5d0c20cf0ab231ac0996a92739584))
* **jobs:** persist managed lifecycle ([1a82ec8](https://github.com/nevenincs/vaultspec-rag/commit/1a82ec82529833da829eaca4ed1e381ef7e407be))
* **jobs:** require document admission authority ([6ac06a5](https://github.com/nevenincs/vaultspec-rag/commit/6ac06a56942aa914bde0ae971e48bd0d402298fa))
* **lint:** gate code-stands-alone citations ([0195cab](https://github.com/nevenincs/vaultspec-rag/commit/0195cab20bcc69a045b2373a751554e108d29edc))
* **logging:** add source-aware managed reader ([a83b711](https://github.com/nevenincs/vaultspec-rag/commit/a83b711a0d1497d36266c872bf6135009c09dab9))
* **logging:** shape managed log groups ([6d8bac0](https://github.com/nevenincs/vaultspec-rag/commit/6d8bac0ba9490d86b40bfa9dedca25a9036ce140))
* **logging:** wire service managed retention ([5171816](https://github.com/nevenincs/vaultspec-rag/commit/5171816a62bea87812e93d0606ebc747337080a7))
* **preprocess:** bound source and encoded output bytes ([4ea7e66](https://github.com/nevenincs/vaultspec-rag/commit/4ea7e66548f2f5065efabd0efb33d7fe2af6d075))
* **preprocess:** expose faithful execution contract ([4c2d141](https://github.com/nevenincs/vaultspec-rag/commit/4c2d141690a6609358d28da44cb6d8f9d27c9e0f))
* **qdrant:** rotate supervised output ([fc60a99](https://github.com/nevenincs/vaultspec-rag/commit/fc60a99c6c40bc59bb79d09dbc7d68873d50473d))
* **search:** add document-native retrieval shaping ([213bd5b](https://github.com/nevenincs/vaultspec-rag/commit/213bd5b30efd62c1d8a5ec380f29f885a9b17dc2))
* **search:** allocate combined domain candidates ([9dd40f7](https://github.com/nevenincs/vaultspec-rag/commit/9dd40f702f67a001615a1f8281471543e77d68ac))
* **search:** export document outcome types ([c0fadbb](https://github.com/nevenincs/vaultspec-rag/commit/c0fadbba589d0fd8adc5939ddd20e923d6909d6b))
* **search:** expose combined domain status ([3cb81da](https://github.com/nevenincs/vaultspec-rag/commit/3cb81dacbaca8daf71420e563a5b60badf21de2c))
* **search:** query the independent document index ([1c1572b](https://github.com/nevenincs/vaultspec-rag/commit/1c1572bb64dddcfd4a2daa230e615332fd7e2f68))
* **search:** retain per-domain partial outcomes ([c92ab72](https://github.com/nevenincs/vaultspec-rag/commit/c92ab72f447bb0eaa3c370770316eb088e7beaab))
* **search:** validate document filters by source ([afdc944](https://github.com/nevenincs/vaultspec-rag/commit/afdc9442d4343d400777e0deb6c0f4662e16d1b7))
* **server:** complete document lifecycle routes ([770be67](https://github.com/nevenincs/vaultspec-rag/commit/770be676a234b13243e7f8808b14ad8f66457fff))
* **server:** expose managed log sources ([e181512](https://github.com/nevenincs/vaultspec-rag/commit/e181512a3bf01316cdf14356e41b024a4503b0e9))
* **server:** restore and drain managed jobs ([8f46d84](https://github.com/nevenincs/vaultspec-rag/commit/8f46d84a3efdd8cbb96b8214c848168ff53c8b17))
* **server:** route document and combined search ([5b541bb](https://github.com/nevenincs/vaultspec-rag/commit/5b541bbe4eeacbc9f212af74427096a02675752b))
* **server:** serialize document-native results ([4f42f66](https://github.com/nevenincs/vaultspec-rag/commit/4f42f66d2d6c114aab615da4d4c457ffdad65bb9))
* **server:** shape bounded resilience projection into job responses ([05b91d1](https://github.com/nevenincs/vaultspec-rag/commit/05b91d1baf181df4559186375a5ab194601bd8d9))
* **service:** add a bounded non-destructive discovery reconcile ([dd523c7](https://github.com/nevenincs/vaultspec-rag/commit/dd523c7f5d48d09e1a38e0e2e27d696449cebef2))
* **service:** add policy-gated job lifecycle routes ([b0236fe](https://github.com/nevenincs/vaultspec-rag/commit/b0236fe9c6c54fbc896eb09f1504d44a51ab0c7f))
* **service:** expose canonical job lifecycle views ([099e2e6](https://github.com/nevenincs/vaultspec-rag/commit/099e2e661f32bb8056847f740f634a9aa8953889))
* **service:** expose exact job lifecycle resources ([19f2c69](https://github.com/nevenincs/vaultspec-rag/commit/19f2c69821c81e279b543793395b12572dd0a3cf))
* **service:** report canonical job health ([be0e763](https://github.com/nevenincs/vaultspec-rag/commit/be0e7634141bde13c67a707144c70d2bb4a3c420))
* **status:** compose one canonical operator verdict ([d97ff38](https://github.com/nevenincs/vaultspec-rag/commit/d97ff389388216aa75c40dd3754cabb1d04ebf19))
* **status:** expose document generation readiness ([2ec72ad](https://github.com/nevenincs/vaultspec-rag/commit/2ec72ad1ee16d3544ad617c0d821cdd49f33ae4c))
* **status:** expose independent index ceilings ([b02370f](https://github.com/nevenincs/vaultspec-rag/commit/b02370f2222cd548b8e0f953369232200dba00b0))
* **status:** render a live holder instead of reporting stopped ([71bc054](https://github.com/nevenincs/vaultspec-rag/commit/71bc05400ee54cbf3a76c57b6bdefa9bfaabae50))
* **storage:** describe document collection schema ([529fbba](https://github.com/nevenincs/vaultspec-rag/commit/529fbba1cf3d228427f5556b2fc79ea2cad3a730))
* **storage:** isolate document collection lifecycle ([1a28fe8](https://github.com/nevenincs/vaultspec-rag/commit/1a28fe805e57acb1d2009413f1ca05ac5ef9a980))
* **storage:** maintain document namespaces ([ed56551](https://github.com/nevenincs/vaultspec-rag/commit/ed5655191988827449a32686910cafa6d7440376))
* **storage:** migrate document collections ([d2ce46f](https://github.com/nevenincs/vaultspec-rag/commit/d2ce46f90ca00efb35799f16592f2eb961a7c574))
* **storage:** publish document snapshot manifests ([0fabcb1](https://github.com/nevenincs/vaultspec-rag/commit/0fabcb133ef5a3e1d11dcf9bea2056a6b62ee2c3))
* **storage:** reconcile existing collections onto bounded segment geometry ([8bf64f7](https://github.com/nevenincs/vaultspec-rag/commit/8bf64f78668ddbbd402f2b2e13d479b55e814bcf))
* **storage:** reconcile existing collections onto bounded segment geometry ([#251](https://github.com/nevenincs/vaultspec-rag/issues/251)) ([a8ccc54](https://github.com/nevenincs/vaultspec-rag/commit/a8ccc543e9dddbf18cca4d7be058d02a4e7e953f))
* **storage:** record document collections in manifest ([58954ff](https://github.com/nevenincs/vaultspec-rag/commit/58954ff78a198b77435afb0e0cc2e13551986a93))
* **storage:** report document survey counts ([34ff341](https://github.com/nevenincs/vaultspec-rag/commit/34ff341fb2d655dcb4ab3e366bb00feafc6aa79d))
* **watcher:** drain managed jobs on stop ([3a5ea69](https://github.com/nevenincs/vaultspec-rag/commit/3a5ea6986cd11419fafc8b13e90b246d867011cc))
* **watcher:** manage automatic indexing jobs ([d3610ec](https://github.com/nevenincs/vaultspec-rag/commit/d3610ece7bc7e8c8e8afe7a45a651e3ae05a78d9))


### Bug Fixes

* **adapters:** render canonical service outcomes ([55bff6e](https://github.com/nevenincs/vaultspec-rag/commit/55bff6eeb74dc68e3dd7f7e54f9686a97c99c218))
* **api:** reject unknown clean source types ([8c6a43a](https://github.com/nevenincs/vaultspec-rag/commit/8c6a43ae95bb367a5d8c3da357a9080e97f37cdb))
* **api:** validate document search filters ([4c24c17](https://github.com/nevenincs/vaultspec-rag/commit/4c24c17c7a07c3db6fda10151e47e27d8548bea8))
* **cli:** bound the late-spawn cleanup process probes ([16d8a33](https://github.com/nevenincs/vaultspec-rag/commit/16d8a3329fe0db30d58b15e3aadc03ca182229c0))
* **cli:** gate console-group signalling so late-spawn cleanup cannot hang (S27) ([42af9fc](https://github.com/nevenincs/vaultspec-rag/commit/42af9fc864d70138557ab9a171ce7023b1c95c0b))
* **cli:** warn on uvx-ephemeral caller when attaching to a running service ([d67ac33](https://github.com/nevenincs/vaultspec-rag/commit/d67ac3356a04ce629d301cae417c9b87e9f6cee8))
* **docs:** refresh version literals stale since the 0.3.3 release ([d0834b0](https://github.com/nevenincs/vaultspec-rag/commit/d0834b02394c89a864e134b75cb08f75b283adef))
* **index:** bind changed paths to policy preflight ([7e6c0f8](https://github.com/nevenincs/vaultspec-rag/commit/7e6c0f871d26dfc7e789c0da03e471df910daf7d))
* **index:** bind ledger state to committed bytes ([3746e99](https://github.com/nevenincs/vaultspec-rag/commit/3746e999b4698072b4015757951de299b5ebbf69))
* **index:** bound blocked local writes by run deadline ([df4c978](https://github.com/nevenincs/vaultspec-rag/commit/df4c9786b6bc9073a838709aea02a4df119ab769))
* **index:** bound finalization ledger lookup ([6dd0315](https://github.com/nevenincs/vaultspec-rag/commit/6dd031517a5bc8f5a0744df5c0fa90881159c737))
* **index:** bound ledger publication reads ([ec6fa09](https://github.com/nevenincs/vaultspec-rag/commit/ec6fa09cb403eccbe53bcf01a4918ff007a1c783))
* **index:** bound route finalization ([5def952](https://github.com/nevenincs/vaultspec-rag/commit/5def952b2f36072fd1e1285bdda29627f5efde33))
* **index:** bound store retries to run budget ([6c94136](https://github.com/nevenincs/vaultspec-rag/commit/6c94136f244ac47e381b504260198ec85fc6fc6e))
* **index:** carry complete generation manifests ([fcab73a](https://github.com/nevenincs/vaultspec-rag/commit/fcab73a351442e7b59c520f80fc1e277be352493))
* **index:** checkpoint weighted writes atomically ([a1846ff](https://github.com/nevenincs/vaultspec-rag/commit/a1846ff02407ee5d98061dadc732e7f4d1ae9d0f))
* **index:** enforce document runtime ceilings ([be196f7](https://github.com/nevenincs/vaultspec-rag/commit/be196f7b264de4b17a8ac27a2d1a3f7005616e76))
* **index:** enforce fail-closed routing policy ([013e8d9](https://github.com/nevenincs/vaultspec-rag/commit/013e8d9af7146e1e979e23361f94469c59d22c57))
* **index:** enforce policy-driven code admission ([e1254ed](https://github.com/nevenincs/vaultspec-rag/commit/e1254edcd25ad0dd106d6f1d4a8a581a1d76a838))
* **index:** enforce production memory ceilings ([54df3b0](https://github.com/nevenincs/vaultspec-rag/commit/54df3b0169888878a4c5a665cb528c6b7dcb8190))
* **indexer:** collapse the code-kind admission guard to one owner ([074f99f](https://github.com/nevenincs/vaultspec-rag/commit/074f99f2f4bf17007f9629cac2e7231ef55f2274))
* **indexer:** preserve controlled incremental publication ([5d8b4b4](https://github.com/nevenincs/vaultspec-rag/commit/5d8b4b406ed3f8005fadffa79a40353e84919a74))
* **index:** freeze execution policy through publication ([95e9b05](https://github.com/nevenincs/vaultspec-rag/commit/95e9b057e53bf4b4e9bdae2a638760ab74cbf7dd))
* **index:** freeze ledger publication evidence ([5a45e96](https://github.com/nevenincs/vaultspec-rag/commit/5a45e968a3295aa0aef966f3301bb6d92228b9ce))
* **index:** honor configured Qdrant operation timeout ([1a09067](https://github.com/nevenincs/vaultspec-rag/commit/1a0906780b5df86037e67acc68c17e0b92ed3072))
* **index:** isolate metadata publication temps ([19e23de](https://github.com/nevenincs/vaultspec-rag/commit/19e23de6099045ae8e624f8f1c4ae9745d358677))
* **index:** keep failed work retryable ([c1329d8](https://github.com/nevenincs/vaultspec-rag/commit/c1329d879f6399161465348b5794e2a7d0ffc10a))
* **index:** keep scoped scan compatibility ([f7b1bac](https://github.com/nevenincs/vaultspec-rag/commit/f7b1bacb2870d9194516b9b5fcdbae8698a77a17))
* **index:** make large code ingestion progress-aware ([994ce2d](https://github.com/nevenincs/vaultspec-rag/commit/994ce2d00e2bab7422da5a641b83510f5241bec2))
* **index:** preserve confirmed points on control ([0479b58](https://github.com/nevenincs/vaultspec-rag/commit/0479b5832ec1e5f859e291def8e74ccbceb5fa92))
* **index:** preserve content across incremental failure ([1981060](https://github.com/nevenincs/vaultspec-rag/commit/1981060505e5ef395ae981fa0e77d1b18bce7668))
* **index:** preserve incremental publication during failures ([a2fc493](https://github.com/nevenincs/vaultspec-rag/commit/a2fc493f144ac1e6c76cc3e1fb3c4d8037027976))
* **index:** preserve metadata on empty incrementals ([aa11338](https://github.com/nevenincs/vaultspec-rag/commit/aa113386b03d43597896c42ee3c2b7210ccedad4))
* **index:** preserve resumable ledger evidence ([7a97d85](https://github.com/nevenincs/vaultspec-rag/commit/7a97d855c81d54dfb21e48be4f7297cce50b3b86))
* **index:** preserve scoped policy preflight ([45e9515](https://github.com/nevenincs/vaultspec-rag/commit/45e95154d6bfb0a632880a4089d9d0bb5a580981))
* **index:** project enforced CUDA high-water ([643022c](https://github.com/nevenincs/vaultspec-rag/commit/643022cf51f7e80d0efabdecc13f6279f2a3d3c1))
* **index:** reject invalid content routing ([1ff593c](https://github.com/nevenincs/vaultspec-rag/commit/1ff593c4b3a3f8e3dd6bfd4c414781a335622317))
* **index:** retain disabled preprocess ownership ([b74d671](https://github.com/nevenincs/vaultspec-rag/commit/b74d67130c43b43a289dfda238f243d686c660d2))
* **index:** retain last confirmed route owner ([a4d73d7](https://github.com/nevenincs/vaultspec-rag/commit/a4d73d7031f3c82c6eb256b1ced87e196e6280f0))
* **index:** retire repeatedly failing generations and converge empty sources ([ca615f0](https://github.com/nevenincs/vaultspec-rag/commit/ca615f01cb8d3dd70814f5c092d141fe58bf691c))
* **index:** stop deleting carried-forward points on ordinary incremental runs ([a03a841](https://github.com/nevenincs/vaultspec-rag/commit/a03a841f8e1e6363c8950b033c4f58e69729909a))
* **index:** stream raw document ingestion safely ([3257d2b](https://github.com/nevenincs/vaultspec-rag/commit/3257d2b204bef53acd17ae8d98b3f4c6277b9d6a))
* **index:** supply reset_cuda_peak_memory_stats so committed HEAD can index ([5c8dd1e](https://github.com/nevenincs/vaultspec-rag/commit/5c8dd1e37da8224f1d99ec86b65618e09d884c11))
* **index:** thread after_forward/on_cuda_oom into the code slice encoder ([fab0c66](https://github.com/nevenincs/vaultspec-rag/commit/fab0c66dad2420f0b621026a456507c7421c83bb))
* **jobs:** close dispatch admission during shutdown ([4741e05](https://github.com/nevenincs/vaultspec-rag/commit/4741e05a2a751911d375ccdec17332427dc702b6))
* **jobs:** close persistence review gaps ([2cad0e2](https://github.com/nevenincs/vaultspec-rag/commit/2cad0e2250f0de9a3dad03cb1869d63a0d53a0f2))
* **jobs:** expand the home-relative status dir in the managed state path ([b8f904d](https://github.com/nevenincs/vaultspec-rag/commit/b8f904dbb0b7851602cc5c77be24af79b1a7b00c))
* **jobs:** harden state persistence against the Windows replace race ([36c46b8](https://github.com/nevenincs/vaultspec-rag/commit/36c46b841e8caa06e2689f625bafff97122b58a9))
* **jobs:** resolve wave one review ([2361525](https://github.com/nevenincs/vaultspec-rag/commit/23615252159cb6aa280f74a3b9efca683f134899))
* **logging:** bound raw service and qdrant logs ([d4a0505](https://github.com/nevenincs/vaultspec-rag/commit/d4a0505c9c074b5ffb0bef7f4cf8f4f2a54d67f2))
* **metrics:** register the maintenance-reconcile counters and gauge ([616a380](https://github.com/nevenincs/vaultspec-rag/commit/616a3803d88376a0de787667b618a8005fc561c4))
* **metrics:** register the maintenance-reconcile counters and gauge ([8fc70fb](https://github.com/nevenincs/vaultspec-rag/commit/8fc70fbfac8f958bfdc290b0337f029e57588f91))
* **preprocess:** harden invocation and cache fidelity ([15efefc](https://github.com/nevenincs/vaultspec-rag/commit/15efefce9e57345c93f6d184ffbefdb8022dcaef))
* **qdrant:** bound the pre-spawn orphan reap; close S68 review findings ([2cfa97d](https://github.com/nevenincs/vaultspec-rag/commit/2cfa97d8fd74def2c6d99d89b6ec8790a0436717))
* **qdrant:** pin the supervised child's working directory to the managed dir ([9fc43dd](https://github.com/nevenincs/vaultspec-rag/commit/9fc43dd9a35d092a4e35c2cd258390bae02d9b1c))
* **qdrant:** reap zombie child in posix orphan reaper ([7b19988](https://github.com/nevenincs/vaultspec-rag/commit/7b199884afac22a16f114f695af86a08c672355b))
* restore main to green after the integration merge ([81c0611](https://github.com/nevenincs/vaultspec-rag/commit/81c06112cbc21fffd9d0d8e95593e358acd1187c))
* **search:** avoid pushed-filter overfetch ([9f05aca](https://github.com/nevenincs/vaultspec-rag/commit/9f05aca38c716079d9c904129524b2ed7d7207b0))
* **search:** classify collection rebuild races ([fe1e007](https://github.com/nevenincs/vaultspec-rag/commit/fe1e007b0abcbb92feeaa31bb9672978dc1e5bb3))
* **search:** log structured outcomes ([5c40df7](https://github.com/nevenincs/vaultspec-rag/commit/5c40df79d0f218cf0eb7d27478bcf30359e4dc1e))
* **search:** make nonempty availability explicit ([6d1498c](https://github.com/nevenincs/vaultspec-rag/commit/6d1498c89fd7f1d81dc0a5da845678ceee0d3f48))
* **search:** preserve combined domain ownership ([cfe98e7](https://github.com/nevenincs/vaultspec-rag/commit/cfe98e7dc520876ad247a87115aefebfb4512b86))
* **search:** preserve legacy docs alias ([0f2f7f1](https://github.com/nevenincs/vaultspec-rag/commit/0f2f7f151f34f761b045056a934f4e9335b2c166))
* **search:** reject legacy response shapes ([206ee75](https://github.com/nevenincs/vaultspec-rag/commit/206ee75c3e081840aa73bce7c77ae4dbecac7fee))
* **search:** signal unavailable indexes ([9e419c5](https://github.com/nevenincs/vaultspec-rag/commit/9e419c51b8379a955f98669831b239dd759eb8a8))
* **search:** unify availability state evidence ([94b4600](https://github.com/nevenincs/vaultspec-rag/commit/94b4600fdec57c6ba6ece013755fbe05b8cdfd63))
* **search:** use canonical availability jobs ([d1749c1](https://github.com/nevenincs/vaultspec-rag/commit/d1749c14d6b58a0128cbc028f653d3bbed22e3db))
* **search:** validate search type ([1ef825d](https://github.com/nevenincs/vaultspec-rag/commit/1ef825d4c04dc4a45eafd492d8990accb1929d85))
* **server:** bound managed-Qdrant client operations with a finite timeout ([5b6ecd3](https://github.com/nevenincs/vaultspec-rag/commit/5b6ecd3431107f2da10437fd129344bdee921185))
* **server:** bound the daemon exit and discovery-quiesce waits (S29, S30) ([73c338a](https://github.com/nevenincs/vaultspec-rag/commit/73c338ab96ed503597935e2ef320908ffd31a996))
* **server:** expand the qdrant storage path before identity stamping ([0993fff](https://github.com/nevenincs/vaultspec-rag/commit/0993fff359cffa01a7cc08855f75613a271fe35b))
* **server:** export _daemon_process/_daemon_log_capture in _state.__all__ ([679de11](https://github.com/nevenincs/vaultspec-rag/commit/679de11a3df7caded8bd4ce27e61c51ced613e48))
* **server:** fail-loud authoritative RUNNING publish and carve a contention-scoped rollback path (S31, [#6](https://github.com/nevenincs/vaultspec-rag/issues/6)) ([174000d](https://github.com/nevenincs/vaultspec-rag/commit/174000d0f0617d7cbddc1c777dbc61535f7ca481))
* **server:** keep reranker content internal ([5dd19fc](https://github.com/nevenincs/vaultspec-rag/commit/5dd19fc127ba496fedd93c0f0cc0d22c94620673))
* **server:** preserve structured reindex errors ([d124d28](https://github.com/nevenincs/vaultspec-rag/commit/d124d286590644bdb62185ca140496344bc5d980))
* **server:** reject unsupported search feedback ([97afb0c](https://github.com/nevenincs/vaultspec-rag/commit/97afb0c03c7a7433225bcc3a0a601e72d0184aa1))
* **server:** require canonical source types ([59a70a9](https://github.com/nevenincs/vaultspec-rag/commit/59a70a9fac195751b9a2f427d75cea65bbadd591))
* **service:** align resilience reporting contracts ([e33faf8](https://github.com/nevenincs/vaultspec-rag/commit/e33faf8b4016e8a476de93d5d33e0aee9a9d9ede))
* **service:** bound search status and log views ([3395353](https://github.com/nevenincs/vaultspec-rag/commit/339535399b4e1e5cd5eb3628e9728d368c4d5cca))
* **service:** bound the shutdown store teardown so a wedged writer lock cannot hang the daemon (S28) ([599a08e](https://github.com/nevenincs/vaultspec-rag/commit/599a08e12c6fad522262a82d38324c349c7fa385))
* **serviceclient:** close the redirect-refusal review findings ([b8ad5b2](https://github.com/nevenincs/vaultspec-rag/commit/b8ad5b26302345a5b6bbe4f02cda17777a64bb52))
* **serviceclient:** refuse HTTP redirects on the shared admin transport ([ae72856](https://github.com/nevenincs/vaultspec-rag/commit/ae728568ccc3e5b8f644db51574ead7a6b95f895))
* **serviceclient:** resolve the general call timeout through the admin policy ([1ce67b6](https://github.com/nevenincs/vaultspec-rag/commit/1ce67b60db0566658e5cb08ba2039a962e22034a))
* **serviceclient:** tighten live-pointer liveness to the machine-pointer incarnation ([a421616](https://github.com/nevenincs/vaultspec-rag/commit/a4216166cc9a8a61fccbe86afe27b8e2124b4323))
* **service:** keep durable job writes off ASGI ([abe0d5c](https://github.com/nevenincs/vaultspec-rag/commit/abe0d5cc1d74c320c169a4d919a6eca390948d35))
* **service:** let a stop drain before forcing the kill ([64964f0](https://github.com/nevenincs/vaultspec-rag/commit/64964f049efc335b92f75527a2639a5ddbf90a10))
* **service:** reclaim the singleton to clear a stranded pointer ([72ae2aa](https://github.com/nevenincs/vaultspec-rag/commit/72ae2aaa73eff6aab74d065318e0c14634a0706c))
* **storage:** gate reconcile convergence on collection status, not optimizer status ([df21171](https://github.com/nevenincs/vaultspec-rag/commit/df21171e02650e7377fe56b49feae1fad01706e0))
* **store:** restructure the store lifecycle lock bound (S28 completion) ([6693016](https://github.com/nevenincs/vaultspec-rag/commit/6693016462086f2a9c84b96b885b3ebd477ca8df))
* **store:** take the document write-policy lock and pump backpressure on document points ([c3cd3e8](https://github.com/nevenincs/vaultspec-rag/commit/c3cd3e81ccf9cc561a249825814712d338ced99e))
* **store:** validate write-lock deadline budgets ([043805c](https://github.com/nevenincs/vaultspec-rag/commit/043805ceb8ff5b8e788e83514cfe1a421d15200e))
* **test:** contain singleton side effects ([1bf164b](https://github.com/nevenincs/vaultspec-rag/commit/1bf164b74162d88288be2a62c11d7fbe72ca3c27))
* **tests:** cast the narrowed envelope dict before subscripting ([b0f3a89](https://github.com/nevenincs/vaultspec-rag/commit/b0f3a8957fd4377c8aa83456a12c9473ded81571))
* **tests:** close the remaining GPU-marker/integration gap CI exposed ([5ea1089](https://github.com/nevenincs/vaultspec-rag/commit/5ea10898e0016a8e5a67efc0ce3c0f7f117087ad))
* **tests:** gate CI test selection on the full real-infra marker set ([72cc735](https://github.com/nevenincs/vaultspec-rag/commit/72cc73571718140edc918ed11eafa476132d0019))
* **tests:** import WatcherRetryState used by the split retry helpers ([3036f99](https://github.com/nevenincs/vaultspec-rag/commit/3036f9959de33f3397526364e89311b051a6435b))
* **tests:** mark quality/performance/robustness suites as integration too ([e983192](https://github.com/nevenincs/vaultspec-rag/commit/e98319210123f017d3d83776f709f72c118ff177))
* **tests:** mock disk_usage so the preprocess-preflight tests stop tripping the real disk guard ([eb4fae8](https://github.com/nevenincs/vaultspec-rag/commit/eb4fae8963b07412a92045a8b40d76bf1c7d94c2))
* **tests:** move the fake-server attach test to the integration tier ([f4b4df3](https://github.com/nevenincs/vaultspec-rag/commit/f4b4df3a9d304ce8e50430fd92e84f809ae34f92))
* **tests:** reclaim leaked pytest singleton roots crash-safely; stop ops_qdrant's unconditional leak ([f5041d2](https://github.com/nevenincs/vaultspec-rag/commit/f5041d228036ba1c2cbd339dc3d9a72fc4d53b0b))
* **tests:** reconcile-fixture token identity and identity.json path drift ([#4](https://github.com/nevenincs/vaultspec-rag/issues/4)/[#5](https://github.com/nevenincs/vaultspec-rag/issues/5)) ([3482e75](https://github.com/nevenincs/vaultspec-rag/commit/3482e75e734c278d0e5d30b9e297f576198f56db))
* **tests:** replace the Windows-only project literal in the watcher CLI tests ([dd74fce](https://github.com/nevenincs/vaultspec-rag/commit/dd74fce09b273b52c1350fb387466ed86bc8316d))
* **tests:** replace the Windows-only project_root literal with a real cross-platform absolute path ([3d0247a](https://github.com/nevenincs/vaultspec-rag/commit/3d0247ab88e69837d265f6df3ad11522f0fe0b8e))
* **tests:** require the real host binary in the fake-server attach test ([fa73164](https://github.com/nevenincs/vaultspec-rag/commit/fa731645638ac5059c4e89e3a72042982a143aed))
* **tests:** reserve force-kill budget in service teardown ([cc6ba3c](https://github.com/nevenincs/vaultspec-rag/commit/cc6ba3c3c2f9914be0592c2e47d0bac54710a10b))
* **tests:** reserve force-kill budget regardless of teardown budget size ([01585a5](https://github.com/nevenincs/vaultspec-rag/commit/01585a50d674e472e64ef42546b8a41ea396550a))
* **tests:** route graceful shutdown to the process-group leader so restart cycles actually stop (S33, [#2](https://github.com/nevenincs/vaultspec-rag/issues/2)/[#3](https://github.com/nevenincs/vaultspec-rag/issues/3)) ([890330e](https://github.com/nevenincs/vaultspec-rag/commit/890330e1ffeaaa2247b05ed6ae250c7e1ea60ed0))
* **tests:** tolerate Rich's clear-screen escape in the watch-refresh assertion ([11f5ccc](https://github.com/nevenincs/vaultspec-rag/commit/11f5ccccab1cd652c8b1c4c17fe6ee2978e94e99))
* **tests:** update install-report vocabulary assertions to vaultspec-core 0.1.48 ([20f31bd](https://github.com/nevenincs/vaultspec-rag/commit/20f31bdc1a393de431bc3073cc97051fdcb9233d))
* **tests:** update the /search type-contract test for the canonical-vocabulary boundary ([9f4d749](https://github.com/nevenincs/vaultspec-rag/commit/9f4d74965082634a42a52f83d70ab9a232583a1f))
* **types:** annotate admission projection and remove a dead print subtree in cli/_index ([53e4364](https://github.com/nevenincs/vaultspec-rag/commit/53e43643cda4b6afa15ea3d7b3ea5adb696ee33f))
* **types:** annotate point-evidence dict and drop dead None-checks in _codebase_indexer ([747303d](https://github.com/nevenincs/vaultspec-rag/commit/747303dfce5b870b852b9183a6259a0fd28166d4))
* **types:** annotate the self-mapping tables as concrete dict, not Mapping ([6b03f7a](https://github.com/nevenincs/vaultspec-rag/commit/6b03f7a3863757ac036b2ea271326cb7d77d455d))
* **types:** cast JSON/dict Any-propagation in status, document-meta, manifest, preprocess; ignore torch stub gap ([dd9255f](https://github.com/nevenincs/vaultspec-rag/commit/dd9255f04605d3d8b80e9490a84c5161fe9b7bb7))
* **types:** cast tuple-narrowed canonical-option payloads to typed tuples ([33fe5bc](https://github.com/nevenincs/vaultspec-rag/commit/33fe5bc94ca2d57e30d8413d54a55e1a3464742b))
* **types:** clear strict-type errors in _run_ledger ([37a8858](https://github.com/nevenincs/vaultspec-rag/commit/37a88589f0aa69974f20ff3d0da3bfb7730bf29d))
* **types:** clear the last strict-type errors in tests/benchmarks and store __exit__ ([c08acc4](https://github.com/nevenincs/vaultspec-rag/commit/c08acc42d0677a058bd1fb27b518d391b00c147f))
* **types:** document two false-positive possibly-unbound in _chunk_worker ([2aae74c](https://github.com/nevenincs/vaultspec-rag/commit/2aae74caf627548a97b4a9012f3a09d9b1fb8c5a))
* **types:** mark runtime enum/type validators as reportUnnecessaryIsInstance-exempt ([a2c3144](https://github.com/nevenincs/vaultspec-rag/commit/a2c3144048544594461428c18f3a6e1859bf87e6))
* **types:** mark the _resolved_policy tuple casts ty-redundant-exempt ([ac3591e](https://github.com/nevenincs/vaultspec-rag/commit/ac3591eab1da35a34257936a582b797b22ae29d0))
* **types:** resolve cross-module private-usage in the resilience/qdrant paths ([71dc831](https://github.com/nevenincs/vaultspec-rag/commit/71dc831c7f7ef7d52b007719e1a51c3d2ecc0a70))
* **watcher:** persist bounded retry circuits ([b4dc437](https://github.com/nevenincs/vaultspec-rag/commit/b4dc437aa815e9af8a6c8927cd3ac13d97f45f91))
* **watcher:** share content admission snapshot ([3602ee9](https://github.com/nevenincs/vaultspec-rag/commit/3602ee982a6fe37517832faba3fe6399c675f3f2))
* **watcher:** terminally remove a watcher whose init fails ([f163523](https://github.com/nevenincs/vaultspec-rag/commit/f1635236d0bc13cdb0cf58d206bde3d7c17e6ef3))


### Performance

* **index:** bound code vector segments ([0732900](https://github.com/nevenincs/vaultspec-rag/commit/0732900bc9ab379de6ffecec6bd37120473688bf))
* **index:** bound preprocessing future windows ([587933a](https://github.com/nevenincs/vaultspec-rag/commit/587933a1acfb0f5987feabafd3d03f2068009146))
* **index:** linearize scan and line accounting ([d467328](https://github.com/nevenincs/vaultspec-rag/commit/d4673289698e08f163b10d2b5802d9c7bdb5c4e6))
* **index:** stream scoped incremental production ([c4196f7](https://github.com/nevenincs/vaultspec-rag/commit/c4196f76201afc62f9aec5b0235f26dd865030f4))
* **index:** stream unscoped incremental production ([dede3a4](https://github.com/nevenincs/vaultspec-rag/commit/dede3a4ffba11bfdc49ba1737f18f4ad382a78ec))
* **index:** weight full-index production ([35cc9d7](https://github.com/nevenincs/vaultspec-rag/commit/35cc9d740f28fb04501d533765fa107289c20497))

## [0.3.3](https://github.com/nevenincs/vaultspec-rag/compare/vaultspec-rag-v0.3.2...vaultspec-rag-v0.3.3) (2026-07-21)

### Features

- fail-loud index observability, ephemeral namespace TTL, debris reclaim, and test-run isolation ([#242](https://github.com/nevenincs/vaultspec-rag/issues/242)) ([#248](https://github.com/nevenincs/vaultspec-rag/issues/248)) ([cdd61fe](https://github.com/nevenincs/vaultspec-rag/commit/cdd61fe69100896ddf1b31f56e327d8fdfd778b9))
- integrate provider-mcp-enrollment (Core-managed provider lifecycle, Codex-native TOML) ([#250](https://github.com/nevenincs/vaultspec-rag/issues/250)) ([3d51e4d](https://github.com/nevenincs/vaultspec-rag/commit/3d51e4d9a143989a5306ffc861d39aa849358d04))
- **preprocess:** opt-in batch manifest hook invocation (~100x first-index hook speedup) ([#247](https://github.com/nevenincs/vaultspec-rag/issues/247)) ([3fa6f24](https://github.com/nevenincs/vaultspec-rag/commit/3fa6f24b97028d17dba43499f67f5b4e0be8a7fb))

### Bug Fixes

- **cli:** honest start outcomes during warm-up and visible cold-start progress ([#238](https://github.com/nevenincs/vaultspec-rag/issues/238)) ([45cb3f1](https://github.com/nevenincs/vaultspec-rag/commit/45cb3f1e9b3c17bc609a8a5e0bf2471b2eb27db3)), closes [#237](https://github.com/nevenincs/vaultspec-rag/issues/237)
- **indexer,store:** bounded write retry, disk headroom guards, server request timeout ([#246](https://github.com/nevenincs/vaultspec-rag/issues/246)) ([96b6204](https://github.com/nevenincs/vaultspec-rag/commit/96b62046d810ddbaf2b0c49d5ada27a9b1ff8058))
- **install:** clean-worktree invariant for runtime artifacts, sentinel cleanup on uninstall ([#243](https://github.com/nevenincs/vaultspec-rag/issues/243)) ([06571ac](https://github.com/nevenincs/vaultspec-rag/commit/06571acf2882a145a9e07e20b856877e89060dd3)), closes [#236](https://github.com/nevenincs/vaultspec-rag/issues/236)
- **storage:** normalize extended-length root aliases, flag temp-rooted namespaces, harness teardown guidance ([#245](https://github.com/nevenincs/vaultspec-rag/issues/245)) ([276312e](https://github.com/nevenincs/vaultspec-rag/commit/276312e7a01142b07ecb8f3899a43fad4ae00d99))

## [0.3.2](https://github.com/nevenincs/vaultspec-rag/compare/vaultspec-rag-v0.3.1...vaultspec-rag-v0.3.2) (2026-07-17)

### Features

- **server:** stdio watchdog converges on the pipe-creator anchor; e2e suite reaches the functional assertion floor ([#234](https://github.com/nevenincs/vaultspec-rag/issues/234)) ([df9cf6f](https://github.com/nevenincs/vaultspec-rag/commit/df9cf6fad6b855105e1011c33b192cea42b4a211))

## [0.3.1](https://github.com/nevenincs/vaultspec-rag/compare/vaultspec-rag-v0.3.0...vaultspec-rag-v0.3.1) (2026-07-17)

### Features

- **index:** surface preprocess_ok so a working hook pipeline is observable ([#226](https://github.com/nevenincs/vaultspec-rag/issues/226)) ([874f0fe](https://github.com/nevenincs/vaultspec-rag/commit/874f0fea75126daebfc7b1f9ace874d47966e54f))
- **server:** stdio shim owns its lifetime - ancestor-chain watchdog reaps orphaned MCP shims on Windows ([#228](https://github.com/nevenincs/vaultspec-rag/issues/228)) ([6ee6f8f](https://github.com/nevenincs/vaultspec-rag/commit/6ee6f8f738c14d4a70f9ff25a863b2611d267ffb))

### Bug Fixes

- **install:** bind rag to core's static-launch MCP contract ([#233](https://github.com/nevenincs/vaultspec-rag/issues/233)) ([a1a93fb](https://github.com/nevenincs/vaultspec-rag/commit/a1a93fb59b54cc8cec8093aa011fd4619e3e8fad))

## [0.3.0](https://github.com/nevenincs/vaultspec-rag/compare/vaultspec-rag-v0.2.28...vaultspec-rag-v0.3.0) (2026-07-14)

### ⚠ BREAKING CHANGES

- **preprocess:** run hook children with the project root as cwd
- **preprocess:** collapse the preprocess tri-state to on/off across the control surface
- **preprocess:** remove the OS hook sandbox; hooks run as direct bounded subprocesses
- **cli:** the identity-unconfirmed skip now exits 1 (was 0) in both human and --json modes - a stop that leaves the service running is a failure a broker must see (P02.S05).

### Features

- **cli:** attribute service shutdown to the initiating process ([91d697a](https://github.com/nevenincs/vaultspec-rag/commit/91d697a6fd594b508b4c87fd2a63813317c81ee4))
- **cli:** classify runtime envs and derive GPU remediation commands from the cu130 constants ([8a857ad](https://github.com/nevenincs/vaultspec-rag/commit/8a857add26edc3196d146d0a0199385b2a3f5c24))
- **cli:** env-aware start refusal and a loud uvx-ephemeral warning on server start ([e6bfb3e](https://github.com/nevenincs/vaultspec-rag/commit/e6bfb3ed3562bb5f6626fd28dbe20b4c8aee96dd))
- **cli:** render a distinct warming status state (exit 5) instead of stopped/crashed ([2ed542d](https://github.com/nevenincs/vaultspec-rag/commit/2ed542d1d9bebd6a8f1ff987f655eac3dff58dfe))
- **cli:** server stop --json outcome envelopes with idempotent statuses ([5001c7d](https://github.com/nevenincs/vaultspec-rag/commit/5001c7d629c380fa362c9b3f55bd238900b99877))
- **cli:** server storage survey --root reports the queried root's prefix ([a803ec4](https://github.com/nevenincs/vaultspec-rag/commit/a803ec402f935f476708dff7d025e04f18212091))
- **config:** storage_autoprune knobs for the scheduled maintenance tick ([69a5d76](https://github.com/nevenincs/vaultspec-rag/commit/69a5d7654b2ba69f3f0c7b2c001f43be30fb85cd))
- **doctor:** mode-and-floor rows for the vaultspec-rag entry (install-parity W02.P07 S35) ([d0f8edc](https://github.com/nevenincs/vaultspec-rag/commit/d0f8edcbba1606058da295e3c3572a49906ae77b))
- **index:** config-epoch drift sentinels + preprocess TOFU on-by-default ([3a75362](https://github.com/nevenincs/vaultspec-rag/commit/3a75362a895c03d2fd821de3d6377db07ec17390))
- **install:** adopt the three-placement mode model (install-parity W02) ([4faee6a](https://github.com/nevenincs/vaultspec-rag/commit/4faee6acb6a833f7a788467b3a4cee93ede04c87))
- **install:** adopt three-placement mode model (install-parity W02.P06) ([5b07873](https://github.com/nevenincs/vaultspec-rag/commit/5b0787311e7d5574dc6ebf305150c5bc363887a7))
- **preprocess:** collapse the preprocess tri-state to on/off across the control surface ([64a0353](https://github.com/nevenincs/vaultspec-rag/commit/64a0353d701191b700fb40ba4b038781efd11a30))
- **preprocess:** OS-sandbox hooks so the server runs any repo's hooks non-interactively ([cc3d680](https://github.com/nevenincs/vaultspec-rag/commit/cc3d68074fcd83cb9d2845b20fb452aa558f7e62))
- **preprocess:** remove the OS hook sandbox; hooks run as direct bounded subprocesses ([4905707](https://github.com/nevenincs/vaultspec-rag/commit/4905707ebb9c9d038f2e174aa72a0e19e20b2a3f))
- **server:** crash-proof hourly storage-maintenance tick and loop ([282369c](https://github.com/nevenincs/vaultspec-rag/commit/282369c809dd9b7c71edf6bb12f37e9ab538b56c))
- **server:** maintenance cycles are first-class jobs with /metrics rollup ([62824f6](https://github.com/nevenincs/vaultspec-rag/commit/62824f61d2ef9735ab01e93299035c70a2db067b))
- **server:** root-scoped storage survey lookup with queried_root prefix ([031b900](https://github.com/nevenincs/vaultspec-rag/commit/031b9006dfed3e989b114426238992a784b17622))
- **server:** schedule the maintenance loop from the daemon lifespan ([8370a7d](https://github.com/nevenincs/vaultspec-rag/commit/8370a7d39920bd9c3e4e8ab144df7271d4a9caf4))
- **server:** stamp warming/running phases into service.json across model warmup ([2b7390f](https://github.com/nevenincs/vaultspec-rag/commit/2b7390f865d9268a266046d66cd4764bb36193e0))
- **serviceclient:** thread root through the survey transport and MCP client ([acd9be5](https://github.com/nevenincs/vaultspec-rag/commit/acd9be53fac8792ab3a78d1680eecea6652a6c6c))
- **status:** daemon-stamped lifecycle phase vocabulary in the discovery sidecar ([4150505](https://github.com/nevenincs/vaultspec-rag/commit/415050525b06623e6b708e9eb691bbcccbf81073))
- **storage:** O(1) survey via daemon snapshot + idempotent delete --root ([7ae79ca](https://github.com/nevenincs/vaultspec-rag/commit/7ae79caf57ec68f908fb923873ee261d15d3cc95))
- **storage:** persisted first-seen-orphaned grace clock in the manifest ([ba8ad7b](https://github.com/nevenincs/vaultspec-rag/commit/ba8ad7b8092f738fcf4afabfcf3c6118149c108e))
- **storage:** two-tier time-gated reclamation engine with bounded archives ([fe52f33](https://github.com/nevenincs/vaultspec-rag/commit/fe52f33460a35c3f1b730e05c21dd479dae065c5))

### Bug Fixes

- **ci:** repair main gates - win32 typing narrowing, posix shutdown-log test, setuptools triage ([828c810](https://github.com/nevenincs/vaultspec-rag/commit/828c810528610dc8719686c2b75afa985bbd838f))
- **ci:** repair main gates - win32 typing, posix shutdown-log test, setuptools triage ([2784132](https://github.com/nevenincs/vaultspec-rag/commit/27841322cd8a75fd0f53d2a63c4adeace15e127f))
- **ci:** restore a green main - ty platform, complexity, vault schema, stale test ([390b3c6](https://github.com/nevenincs/vaultspec-rag/commit/390b3c6c501cd26b739d1b93d984a24ce8d99b0d))
- **cli:** resolve --root before dispatch and align the survey json envelope ([f43e360](https://github.com/nevenincs/vaultspec-rag/commit/f43e360e1f4f30e65959679288758750a6e15a78))
- **install:** flip the durable tool pin from --index to a --with wheel URL (on-box gate) ([f3ec4b0](https://github.com/nevenincs/vaultspec-rag/commit/f3ec4b0a7ab76e5b4a1cf030d1573eae4031b507))
- **preprocess:** run hook children with the project root as cwd ([fe82c8f](https://github.com/nevenincs/vaultspec-rag/commit/fe82c8fc0dcfa5a57578d61047f75d4be5fdf05e))
- **qdrant:** extended-length child paths end the Windows storage-path limit ([974e6ca](https://github.com/nevenincs/vaultspec-rag/commit/974e6cab514ec732da0063476c5c78fbc46fc729))
- **qdrant:** extended-length child paths end the Windows storage-path limit ([06b13e3](https://github.com/nevenincs/vaultspec-rag/commit/06b13e36b39a45ee26b2b44ad56c8b84075252ac))
- **review:** document status exit 5 (warming) and require identity-confirmed pid for explicit-port warming ([7991681](https://github.com/nevenincs/vaultspec-rag/commit/7991681e9e1d285e1e6330f8be83643f1fa833ed))
- **storage:** review follow-ups - pre-drop re-count and audit-trail docs ([dbbf046](https://github.com/nevenincs/vaultspec-rag/commit/dbbf0469a4d06d2001b9a574a01b75ee88dd1f5d))
- **tests:** rebind the live_service fixture in watcher-control ([2d391f5](https://github.com/nevenincs/vaultspec-rag/commit/2d391f5fcb8dc6224b46f718016336458bca58e2))
- **tests:** unbreak daemon-reindex integration tests - qdrant path cliff + temp hygiene ([5663fd0](https://github.com/nevenincs/vaultspec-rag/commit/5663fd06b52b73cfd867ff48dbaaac83b096e342))
- **types:** satisfy the strict gate - public observed_mcp_mode, stub ignores, typed test helper ([49df8af](https://github.com/nevenincs/vaultspec-rag/commit/49df8af1d35b3fe59b5a0f50b42f6d9ab79025d8))

## [0.2.28](https://github.com/nevenincs/vaultspec-rag/compare/vaultspec-rag-v0.2.27...vaultspec-rag-v0.2.28) (2026-07-01)

### Features

- **builtins:** bundle a semantic-discovery skill and refocus the rag rule ([8c97484](https://github.com/nevenincs/vaultspec-rag/commit/8c974840514a0c32aa025a96634421b1d98d09ea))
- **install:** report seed actions [ADD]/[UPDATE]/[UNCHANGED] like core ([9056351](https://github.com/nevenincs/vaultspec-rag/commit/905635194c8c37f45cd22cb7ddbea31a6391e43a))
- **search:** query-time domain noise filtering, ranking, and a noise profile ([66b18bb](https://github.com/nevenincs/vaultspec-rag/commit/66b18bb14af1cdea5f5b1e1f12c9a1b0ba2a46fc))
- **search:** query-time domain noise filtering, ranking, and a noise profile ([25f6812](https://github.com/nevenincs/vaultspec-rag/commit/25f6812e715003e6725e94d38024f3c809554bc7))

## [0.2.27](https://github.com/nevenincs/vaultspec-rag/compare/vaultspec-rag-v0.2.26...vaultspec-rag-v0.2.27) (2026-06-30)

### Features

- **deps:** make mcp an optional extra so CLI installs do not drag pywin32 ([048585e](https://github.com/nevenincs/vaultspec-rag/commit/048585e522e006c6b6aa9911cd176c9156263316))
- **install:** vaultspec-rag install ensures the [mcp] extra by default (--no-mcp opt-out) ([78d1442](https://github.com/nevenincs/vaultspec-rag/commit/78d1442943f12cd3137d978272651a53bfaf61cf))
- **mcp-conformance:** narrow the MCP surface and harden errors (P02-P06) ([1c859de](https://github.com/nevenincs/vaultspec-rag/commit/1c859deee220963620ed9e818160bb8d0c4ce321))
- **mcp-conformance:** resolve the machine-singleton service via the global pointer (P01) ([f723ca9](https://github.com/nevenincs/vaultspec-rag/commit/f723ca9f2ba8eb6bc03d797b35b0eb36dac160ce))
- **qdrant:** detect-quarantine-retry a corrupt collection on supervised start ([466cdfb](https://github.com/nevenincs/vaultspec-rag/commit/466cdfb83b46fd5e89b77be6c42d70788910304e))
- **service:** make the service\<->python-env coupling legible and fail fast ([7abb85b](https://github.com/nevenincs/vaultspec-rag/commit/7abb85b591eb9936026c784fa83dff8f1daf2b78))
- **torch:** centralize the GPU torch load + make install tell the truth about the wheel ([b6c4e34](https://github.com/nevenincs/vaultspec-rag/commit/b6c4e34bc60a986de42527485a283009797fff28))

### Bug Fixes

- **mcp,search:** typed search outputSchema + Windows model-load crash fix ([3c9d9d2](https://github.com/nevenincs/vaultspec-rag/commit/3c9d9d2f6073c0ea7bbcaca05bf165673b443aab))
- **qdrant:** address code-review findings on store-resilience recovery ([cd2bb2a](https://github.com/nevenincs/vaultspec-rag/commit/cd2bb2a999a5e886a6b259b0e144dbdb202803ad))
- **service:** make the torch pre-flight green (lint, types, complexity) ([1dc9c08](https://github.com/nevenincs/vaultspec-rag/commit/1dc9c085c7e4c2ea4ef9bc7c98aab8569389f35a))
- **service:** reclaim a wedged machine-singleton holder via `server stop` ([45f3907](https://github.com/nevenincs/vaultspec-rag/commit/45f3907551b2608163f0ec37673a41e02f401e87))

## [0.2.26](https://github.com/nevenincs/vaultspec-rag/compare/vaultspec-rag-v0.2.25...vaultspec-rag-v0.2.26) (2026-06-28)

### Features

- **rag-broker-affordances:** idempotent JSON server start + machine-global discovery pointer ([#216](https://github.com/nevenincs/vaultspec-rag/issues/216)) ([143120d](https://github.com/nevenincs/vaultspec-rag/commit/143120d3529bee407f932898a37dca8233ba8075))
- **storage-schema:** versioned typed runtime-advertised Qdrant schema contract ([#215](https://github.com/nevenincs/vaultspec-rag/issues/215)) ([fe7e0ee](https://github.com/nevenincs/vaultspec-rag/commit/fe7e0ee388685ad50d8429a118798e78d3552b55))

## [0.2.25](https://github.com/nevenincs/vaultspec-rag/compare/vaultspec-rag-v0.2.24...vaultspec-rag-v0.2.25) (2026-06-25)

### Features

- **service-hw-singleton:** complete W04.P09 hardening follow-ups (S28–S33) ([#212](https://github.com/nevenincs/vaultspec-rag/issues/212)) ([355b011](https://github.com/nevenincs/vaultspec-rag/commit/355b011e7198dd54049b4809b268468119d95573))
- **storage-lifecycle:** reconcile plan to shipped CLI-direct design + build genuine gaps (45/45) ([#213](https://github.com/nevenincs/vaultspec-rag/issues/213)) ([d3be70d](https://github.com/nevenincs/vaultspec-rag/commit/d3be70d01da224ea5643194553756767214326aa))

### Bug Fixes

- **ci:** make local `just ci` green — relative test imports + precise absolute-imports gate ([#210](https://github.com/nevenincs/vaultspec-rag/issues/210)) ([ca3f934](https://github.com/nevenincs/vaultspec-rag/commit/ca3f934f4907949d9c114bcb3a07d93e7c73895c))

## [0.2.24](https://github.com/nevenincs/vaultspec-rag/compare/vaultspec-rag-v0.2.23...vaultspec-rag-v0.2.24) (2026-06-24)

### Features

- **install:** optional dependency-group placement for managed torch ([#186](https://github.com/nevenincs/vaultspec-rag/issues/186)) ([5e91195](https://github.com/nevenincs/vaultspec-rag/commit/5e911959596c43bd0b5d4183dac6b8ac95391d67))
- **qdrant:** auto-reap managed orphan before spawn (W03.P06) ([b992b61](https://github.com/nevenincs/vaultspec-rag/commit/b992b6166df3b48911c4c427667994c4f0d9abbc))
- **qdrant:** capture supervised child output and diagnose non-ready exits (W01.P01) ([581b558](https://github.com/nevenincs/vaultspec-rag/commit/581b558ddacbf35ba5640dbf2536a3023f362c5f))
- **qdrant:** verified attach-not-spawn + detection/identity primitives (W01.P02, W02) ([5564677](https://github.com/nevenincs/vaultspec-rag/commit/55646778ec3cd320bb48f0b9a1ae02af4a965b20))
- **search:** intent-aware pipeline-role ranking for vault search ([c02c12c](https://github.com/nevenincs/vaultspec-rag/commit/c02c12cff9505f5283dc9c37b08696416a791fe8))
- **serviceclient:** surface admin failures as a structured envelope ([#199](https://github.com/nevenincs/vaultspec-rag/issues/199)) ([d87d190](https://github.com/nevenincs/vaultspec-rag/commit/d87d19004e54e50ec2505c0479e28e0a9788119f))
- **service:** crash-safe machine-scoped service lock primitive (W03.P05) ([ab12f52](https://github.com/nevenincs/vaultspec-rag/commit/ab12f525900512fd0ed48db4aa34b6e09a414fad))
- **service:** doctor reports live truth; daemon survives its launching shell ([#204](https://github.com/nevenincs/vaultspec-rag/issues/204)) ([ffee70e](https://github.com/nevenincs/vaultspec-rag/commit/ffee70e65f01a018b6d934efe5e0fad297424ed5))
- **service:** machine-singleton wiring + adversarial verification gate (W03.P05.S17, W04) ([8747786](https://github.com/nevenincs/vaultspec-rag/commit/8747786796d44c7bcb2f5e01b434da003253a008))
- **service:** version and document the discovery file as a stable interface ([#190](https://github.com/nevenincs/vaultspec-rag/issues/190)) ([a201f6c](https://github.com/nevenincs/vaultspec-rag/commit/a201f6c4b762398f8da74abde9f337947e6bffef))

### Bug Fixes

- **ci:** format vault docs and clear lint/type/test gates on the bundle ([04c16e0](https://github.com/nevenincs/vaultspec-rag/commit/04c16e0aae0ef891e237a4d1ba0dbcc0f78ec181))
- **deps,types:** restore typer 0.26.7 and clear strict basedpyright errors ([551cd3b](https://github.com/nevenincs/vaultspec-rag/commit/551cd3b6f3781307a458bb956deda4a76df59f2b))
- **lint:** move annotation-only pathlib.Path into TYPE_CHECKING (\_models) ([9266fe1](https://github.com/nevenincs/vaultspec-rag/commit/9266fe1f391ba093b81795ee5ab97d2649072bcf))
- **review:** address audit MEDIUM/LOW findings across the four features ([5f6cd63](https://github.com/nevenincs/vaultspec-rag/commit/5f6cd63e6da9ca9643fae08a99f2fc5d4beb82bd))
- **search:** address code-review findings (HIGH-1, HIGH-2, MEDIUM-2) ([801d959](https://github.com/nevenincs/vaultspec-rag/commit/801d959339d305677a39db983de9bca81fc1c9c6))
- **service:** drop unlink on machine-lock release (3rd review HIGH) ([dcfa20f](https://github.com/nevenincs/vaultspec-rag/commit/dcfa20f0ad330a16f0aebc242a6fd3c4e5276350))
- **service:** replace machine lock with OS advisory lock (2nd review HIGH) ([5bdf47a](https://github.com/nevenincs/vaultspec-rag/commit/5bdf47a2312b186beb5eae4ef3589ba632310fe7))
- **service:** resolve code-review HIGH/MEDIUM in machine-singleton hardening ([689c2fa](https://github.com/nevenincs/vaultspec-rag/commit/689c2fafac5bb1c1a497716171eb6e2e0985e3aa))
- **ty:** clear strict ty errors in test_cli and test_install ([8a13f29](https://github.com/nevenincs/vaultspec-rag/commit/8a13f29f5e8029d1cfd06aeb82bcfe25f5ca5d25))

## [0.2.23](https://github.com/nevenincs/vaultspec-rag/compare/vaultspec-rag-v0.2.22...vaultspec-rag-v0.2.23) (2026-06-21)

### Bug Fixes

- **cli:** make search service-first; never silently fall back to local ([#202](https://github.com/nevenincs/vaultspec-rag/issues/202)) ([#205](https://github.com/nevenincs/vaultspec-rag/issues/205)) ([204651a](https://github.com/nevenincs/vaultspec-rag/commit/204651a246b165aaccaa6483f9e2d3816b403be4))

## [0.2.22](https://github.com/nevenincs/vaultspec-rag/compare/vaultspec-rag-v0.2.21...vaultspec-rag-v0.2.22) (2026-06-20)

### Features

- **mcp:** P01 import-light serviceclient package + lazy package init ([#194](https://github.com/nevenincs/vaultspec-rag/issues/194)) ([6fb2c52](https://github.com/nevenincs/vaultspec-rag/commit/6fb2c52d4563a5fea4a292876521d08cdee713b3))
- **mcp:** P02 MCP tools delegate to serviceclient, drop duplicate seam ([#194](https://github.com/nevenincs/vaultspec-rag/issues/194)) ([63d9f99](https://github.com/nevenincs/vaultspec-rag/commit/63d9f99536992dce26a48232ad086ddd0dccac64))
- **mcp:** P03 stdio-only MCP, remove daemon mount and in-process model load ([#194](https://github.com/nevenincs/vaultspec-rag/issues/194)) ([f7b14ed](https://github.com/nevenincs/vaultspec-rag/commit/f7b14ed3cc4c0f3d2566e33b4dfd01fe03b4a41c))

### Bug Fixes

- **cli:** authenticate --port calls via /health token when status file is absent or stale ([ab28b7e](https://github.com/nevenincs/vaultspec-rag/commit/ab28b7e9ded521d76ea0c791a8d8e8125b08e19b))
- **mcp:** P04 remove dead and phantom MCP artifacts ([#194](https://github.com/nevenincs/vaultspec-rag/issues/194)) ([033c78f](https://github.com/nevenincs/vaultspec-rag/commit/033c78f461afab8e9648f860fdb22c04b081b668))
- **mcp:** P06 review fixes (M-1 docstring, M-2 dead route) + audit ([#194](https://github.com/nevenincs/vaultspec-rag/issues/194)) ([3784c17](https://github.com/nevenincs/vaultspec-rag/commit/3784c17594d2a166548bc74a3b9301253fe5b44a))
- **watcher:** evict deleted files on idle — flush cooldown-suppressed changes ([#192](https://github.com/nevenincs/vaultspec-rag/issues/192)) ([c579e9b](https://github.com/nevenincs/vaultspec-rag/commit/c579e9b89cb4a57bb8464c0acb37d302a4d7b536))

## [0.2.21](https://github.com/nevenincs/vaultspec-rag/compare/vaultspec-rag-v0.2.20...vaultspec-rag-v0.2.21) (2026-06-13)

### Features

- server-first default backend with unified provisioning and readiness ([97b6f64](https://github.com/nevenincs/vaultspec-rag/commit/97b6f64544c3f632d7856f04c9ce81730ada4cc5))

## [0.2.20](https://github.com/nevenincs/vaultspec-rag/compare/vaultspec-rag-v0.2.19...vaultspec-rag-v0.2.20) (2026-06-11)

### Features

- generic document-preprocessing hook infrastructure ([#185](https://github.com/nevenincs/vaultspec-rag/issues/185)) ([#187](https://github.com/nevenincs/vaultspec-rag/issues/187)) ([a6d6f12](https://github.com/nevenincs/vaultspec-rag/commit/a6d6f122ea506cbd99d9010562d369ff6aec6193))

## [0.2.19](https://github.com/nevenincs/vaultspec-rag/compare/vaultspec-rag-v0.2.18...vaultspec-rag-v0.2.19) (2026-06-10)

### Bug Fixes

- **packaging:** declare mcp as a core dependency (#182) ([4e4af36](https://github.com/nevenincs/vaultspec-rag/commit/4e4af369105fd0ef1ba32e75767ce64951783ff1))

## [0.2.18](https://github.com/nevenincs/vaultspec-rag/compare/vaultspec-rag-v0.2.17...vaultspec-rag-v0.2.18) (2026-06-10)

### Bug Fixes

- **cli:** report stopped, not orphaned, when no service.json is present ([83033be](https://github.com/nevenincs/vaultspec-rag/commit/83033bef15c5bda41c1aa4dcf54aebb045bc6320))

## [0.2.17](https://github.com/nevenincs/vaultspec-rag/compare/vaultspec-rag-v0.2.16...vaultspec-rag-v0.2.17) (2026-06-10)

### Features

- **arch:** CLI/MCP Decoupling, Qdrant Server Mode, and Stress Testing ([438faf2](https://github.com/nevenincs/vaultspec-rag/commit/438faf2e900c5e91a386dc5216ca81d5df521a76))
- **config:** add sparse_enabled toggle ([10ba167](https://github.com/nevenincs/vaultspec-rag/commit/10ba167da216caaaf8d7a29b61f507fe88583903))
- **mcp:** rewrite MCP admin tools to consume REST daemon endpoints ([377b780](https://github.com/nevenincs/vaultspec-rag/commit/377b78046ec1ed50877e3a15c0ce8602273fe074))
- **search:** skip SPLADE when sparse_enabled is false ([e33cb78](https://github.com/nevenincs/vaultspec-rag/commit/e33cb7831bb411a7db35c3c1d14a6d4c858f8d75))
- **server:** add /vault-document REST route (P05.S17) ([cf249af](https://github.com/nevenincs/vaultspec-rag/commit/cf249af4a732e12d197c59421756da2519552ea6))
- **W01:** runtime correctness — venv interpreter, guard, gated model, bg load ([dbebd62](https://github.com/nevenincs/vaultspec-rag/commit/dbebd628b96c2d8abdeb47b03fd1f146b1f49580))
- **W02:** service lifecycle + management hardening ([a2984e7](https://github.com/nevenincs/vaultspec-rag/commit/a2984e7bc52c02b135ddf6f34a54e05e98e63121))
- **W03:** CLI flatten, help cleanup, indexing docs, testimonial tests ([b7e82c6](https://github.com/nevenincs/vaultspec-rag/commit/b7e82c6aa85fa4673a385151b962f632e71b744a))

### Bug Fixes

- address comprehensive code review findings ([f57b67b](https://github.com/nevenincs/vaultspec-rag/commit/f57b67bed140c124c34d038bf4a64c205793e43f))
- **mcp:** restore decoupled admin routes ([335e9a9](https://github.com/nevenincs/vaultspec-rag/commit/335e9a9c2babd0bf2786a2aecee9d4bb1b1c9ee6))
- **search:** route directly to dense queries when sparse vector is disabled ([7913e16](https://github.com/nevenincs/vaultspec-rag/commit/7913e160e8133c8bb15a6ee28c081839940e46cb))
- **server:** use streamable_http_app instead of get_starlette_app in \_main.py ([e4ce681](https://github.com/nevenincs/vaultspec-rag/commit/e4ce681b88aab849a3717d8698fb07a23fe5f900))
- **ty:** bypass fastmcp get_starlette_app type hint missing and harmonize test suite ([2c79d74](https://github.com/nevenincs/vaultspec-rag/commit/2c79d74bce6339c04656feaa6c3deb55e6a1aeda))
- **W03:** flatten follow-ups — builtin rule, app help wording, stale test ([fc7b0bb](https://github.com/nevenincs/vaultspec-rag/commit/fc7b0bbd2a753a0585dea3562e76833862735128))
- **W04:** address code-review nits ([f997e92](https://github.com/nevenincs/vaultspec-rag/commit/f997e9276c465819a0a6deeda296408642ccf492))

## [0.2.16](https://github.com/nevenincs/vaultspec-rag/compare/vaultspec-rag-v0.2.15...vaultspec-rag-v0.2.16) (2026-06-05)

### Features

- **arch:** decouple CLI/MCP and standardize into backend facade APIs ([#160](https://github.com/nevenincs/vaultspec-rag/issues/160), [#162](https://github.com/nevenincs/vaultspec-rag/issues/162)) ([a87987b](https://github.com/nevenincs/vaultspec-rag/commit/a87987b065cfa23b23254a095c6103879ab9ce24))

## [0.2.15](https://github.com/nevenincs/vaultspec-rag/compare/vaultspec-rag-v0.2.14...vaultspec-rag-v0.2.15) (2026-06-04)

### Features

- implement async background reindexing and timeout-bounded searches with lock contention diagnostics ([#160](https://github.com/nevenincs/vaultspec-rag/issues/160), [#162](https://github.com/nevenincs/vaultspec-rag/issues/162)) ([a084a26](https://github.com/nevenincs/vaultspec-rag/commit/a084a269aae87b7d23fdd0ffa4cae31daa185ea4))
- implement async background reindexing and timeout-bounded searches with lock contention diagnostics ([#160](https://github.com/nevenincs/vaultspec-rag/issues/160), [#162](https://github.com/nevenincs/vaultspec-rag/issues/162)) ([06cbfd3](https://github.com/nevenincs/vaultspec-rag/commit/06cbfd3437cb97f4274865d2aba5d4b7afaa4b6b))

### Bug Fixes

- mitigate concurrent locking, expose live index progress, and terminate stuck watcher jobs ([#150](https://github.com/nevenincs/vaultspec-rag/issues/150), [#158](https://github.com/nevenincs/vaultspec-rag/issues/158), [#159](https://github.com/nevenincs/vaultspec-rag/issues/159)) ([1b1e6f4](https://github.com/nevenincs/vaultspec-rag/commit/1b1e6f459a079d11383b7082c4d0c2b8082e0107))

## [0.2.14](https://github.com/nevenincs/vaultspec-rag/compare/vaultspec-rag-v0.2.13...vaultspec-rag-v0.2.14) (2026-06-03)

### Features

- **embed:** operator-selectable ONNX dense backend with torch fallback (onnx-encoder-backend P01+P02, [#155](https://github.com/nevenincs/vaultspec-rag/issues/155)) ([73e0bac](https://github.com/nevenincs/vaultspec-rag/commit/73e0bacd4038a2d835f4988be0cd5acb4b628267))

### Bug Fixes

- **index:** bound GPU-consumer shutdown so it aborts instead of hanging (index-gpu-pipeline review) ([9309e40](https://github.com/nevenincs/vaultspec-rag/commit/9309e40bb7047eaf5796c6e44e5e245b8ad55d9e))
- **index:** keep index meta complete on chunk failure; harden gate + worker tests ([#155](https://github.com/nevenincs/vaultspec-rag/issues/155) review) ([953cec9](https://github.com/nevenincs/vaultspec-rag/commit/953cec9f9f2fa77bbda83b2bdf2cbdc125db837d))

### Performance

- **index:** dedicated GPU consumer thread + bounded queue (index-gpu-pipeline P01+P02) ([364e3b4](https://github.com/nevenincs/vaultspec-rag/commit/364e3b4f4c1b7ae680d08bb6bff5acd7a5e370f5))
- **index:** encode-batch + flush throttle + single-read IO + parallel gate, with parity tests & benchmark (P03+P04, [#155](https://github.com/nevenincs/vaultspec-rag/issues/155)) ([d9ef491](https://github.com/nevenincs/vaultspec-rag/commit/d9ef4910243588af72c49588275c65cf50bb0277))
- **index:** parallel process-pool chunking + chunk-to-embed pipeline (P01+P02, [#155](https://github.com/nevenincs/vaultspec-rag/issues/155)) ([7fdbbda](https://github.com/nevenincs/vaultspec-rag/commit/7fdbbda5222e80bb9246ecdd6c48225c9ed0f18f))
- **index:** re-architect codebase indexing for parallelism + GPU pipelining ([53e542a](https://github.com/nevenincs/vaultspec-rag/commit/53e542a1d96c5b179cabc800cf0379dbca9cd9c1))

## [0.2.13](https://github.com/nevenincs/vaultspec-rag/compare/vaultspec-rag-v0.2.12...vaultspec-rag-v0.2.13) (2026-06-02)

### Bug Fixes

- **watcher:** scoped reindex from the change set ([#151](https://github.com/nevenincs/vaultspec-rag/issues/151)) ([eed412d](https://github.com/nevenincs/vaultspec-rag/commit/eed412d3f201939ea77cc6c58c0bb2f9817ec9cb))
- **watcher:** scoped reindex from the change set ([#151](https://github.com/nevenincs/vaultspec-rag/issues/151)) ([ff4d02c](https://github.com/nevenincs/vaultspec-rag/commit/ff4d02cac7208ef921cff4c5919d55dbd8e7aebb))

## [0.2.12](https://github.com/nevenincs/vaultspec-rag/compare/vaultspec-rag-v0.2.11...vaultspec-rag-v0.2.12) (2026-06-01)

### Bug Fixes

- correct false claims in the bundled builtin rule (+docs truthfulness) ([66fc9c0](https://github.com/nevenincs/vaultspec-rag/commit/66fc9c06e2dba284ae693e6fc039daaa174afe29))

## [0.2.11](https://github.com/nevenincs/vaultspec-rag/compare/vaultspec-rag-v0.2.10...vaultspec-rag-v0.2.11) (2026-06-01)

### Features

- **service-observability:** P01 in-flight activity registry ([#142](https://github.com/nevenincs/vaultspec-rag/issues/142)) ([bb6c898](https://github.com/nevenincs/vaultspec-rag/commit/bb6c898bcc72b8f206dd094919c6581c95a64f2b))
- **service-observability:** P02 consolidated status + P03 logs (CLI/MCP/HTTP) ([#142](https://github.com/nevenincs/vaultspec-rag/issues/142)) ([ae33966](https://github.com/nevenincs/vaultspec-rag/commit/ae33966e3035be0d98d2530f3c8138b85a9544bf))
- **service-observability:** P04 jobs exposure + P05 metrics ([#142](https://github.com/nevenincs/vaultspec-rag/issues/142)) ([3cc9da7](https://github.com/nevenincs/vaultspec-rag/commit/3cc9da76e1c8f4b395b52e179f8bb6759433a546))
- service-operability cluster ([#142](https://github.com/nevenincs/vaultspec-rag/issues/142)/[#143](https://github.com/nevenincs/vaultspec-rag/issues/143)/[#144](https://github.com/nevenincs/vaultspec-rag/issues/144)/[#145](https://github.com/nevenincs/vaultspec-rag/issues/145)) + monolith modularization ([8120747](https://github.com/nevenincs/vaultspec-rag/commit/8120747f1c0b2a9dd3f2438c36e79118d78374a6))
- **service-operability:** P01 watcher config keys ([#143](https://github.com/nevenincs/vaultspec-rag/issues/143)/[#144](https://github.com/nevenincs/vaultspec-rag/issues/144)) ([1d4fe2c](https://github.com/nevenincs/vaultspec-rag/commit/1d4fe2c0434afd5249e4946c5363fa8061c5a8d8))
- **service-operability:** P02 wire watcher config + enable guard ([#143](https://github.com/nevenincs/vaultspec-rag/issues/143)/[#144](https://github.com/nevenincs/vaultspec-rag/issues/144)) ([691cddb](https://github.com/nevenincs/vaultspec-rag/commit/691cddb7b0e333d460f29cf2e9945a59eddacccf))
- **service-operability:** P03 service-start watcher flags + env translation ([#143](https://github.com/nevenincs/vaultspec-rag/issues/143)) ([40d8718](https://github.com/nevenincs/vaultspec-rag/commit/40d8718868480011ffe5f2c393a8d3c8bf0a7d3e))
- **service-operability:** P04 watcher runtime control parity (CLI\<->MCP) ([89bdd66](https://github.com/nevenincs/vaultspec-rag/commit/89bdd66a6b335c659880821fd1216bb3f5b55fd9))

### Bug Fixes

- **mcp:** restore python -m vaultspec_rag.mcp_server entry point after package split ([bf3b2ed](https://github.com/nevenincs/vaultspec-rag/commit/bf3b2edd57962fda32e89848fdcd1b12c81b2d48))

## [0.2.10](https://github.com/nevenincs/vaultspec-rag/compare/vaultspec-rag-v0.2.9...vaultspec-rag-v0.2.10) (2026-05-31)

### Miscellaneous

- cut 0.2.10 with docs overhaul and core 0.1.20 dep bump ([246614f](https://github.com/nevenincs/vaultspec-rag/commit/246614fcd47dcee048667d1ebe5a880f675c8537))

## [0.2.9](https://github.com/nevenincs/vaultspec-rag/compare/vaultspec-rag-v0.2.8...vaultspec-rag-v0.2.9) (2026-05-31)

### Breaking changes

0.2.9 tightens four CLI contracts. Each change has a clear remediation that
the CLI prints at runtime, but consumers running these commands in scripts
should update their invocations:

- **`vaultspec-rag clean` now requires an explicit target.** Pass `vault`,
  `code`, or `all`. The previous default of `all` was a footgun
  ([#111](https://github.com/nevenincs/vaultspec-rag/issues/111)).
- **`vaultspec-rag search --port` hard-fails when the service is unreachable.**
  Add `--allow-fallback` to opt in to in-process execution. The previous
  silent fallback could acquire the Qdrant lock and strand a resident
  service ([#107](https://github.com/nevenincs/vaultspec-rag/issues/107),
  [#110](https://github.com/nevenincs/vaultspec-rag/issues/110)).
- **`vaultspec-rag index --rebuild` now requires an explicit `--type`.**
  Pass `vault`, `code`, or `all`. The previous default of `all` could
  silently destroy both collections on `--rebuild --type vault`
  ([#115](https://github.com/nevenincs/vaultspec-rag/issues/115)).
- **`vaultspec-rag search --max-results` default changed from 5 to 10.**
  This mitigates top-k crowding by near-duplicate chunks. Pass an explicit
  `--max-results 5` to restore the prior behaviour
  ([#108](https://github.com/nevenincs/vaultspec-rag/issues/108)).

### Features

- **cli:** --json envelope output across every command ([#112](https://github.com/nevenincs/vaultspec-rag/issues/112)) ([bdf47ba](https://github.com/nevenincs/vaultspec-rag/commit/bdf47ba5f47787484257c3d0ecdff6ce4df60017))
- CLI-MCP-backend parity bundle + safety contract ([#107](https://github.com/nevenincs/vaultspec-rag/issues/107), [#110](https://github.com/nevenincs/vaultspec-rag/issues/110) partial, [#111](https://github.com/nevenincs/vaultspec-rag/issues/111)) ([f9749af](https://github.com/nevenincs/vaultspec-rag/commit/f9749afcdd5d51960b4a03e355706888248c8347))
- **cli:** [#123](https://github.com/nevenincs/vaultspec-rag/issues/123) windows-only shutdown log mirror ([05392df](https://github.com/nevenincs/vaultspec-rag/commit/05392df490da3b7bc0bc635d32e1cb2c546a9f8e))
- **cli:** index --rebuild requires --type, scope drop to collection ([#115](https://github.com/nevenincs/vaultspec-rag/issues/115)) ([b19ae1f](https://github.com/nevenincs/vaultspec-rag/commit/b19ae1f2c17cb1d9292ff9c7e64697fb1bc813c6))
- **search:** --dedup-locales + --prefer prod/tests/docs ([#121](https://github.com/nevenincs/vaultspec-rag/issues/121), [#122](https://github.com/nevenincs/vaultspec-rag/issues/122)) ([#134](https://github.com/nevenincs/vaultspec-rag/issues/134)) ([60e9a69](https://github.com/nevenincs/vaultspec-rag/commit/60e9a69078ea98203abe4c8d4a4116402a8a9612))
- **search:** --include-path / --exclude-path post-query glob filter ([#114](https://github.com/nevenincs/vaultspec-rag/issues/114)) ([9e74343](https://github.com/nevenincs/vaultspec-rag/commit/9e74343353a23a4e0490cb0e5bbca9c5f370a1df))
- **service:** daemon-side lifecycle + status divergence + log entries ([#113](https://github.com/nevenincs/vaultspec-rag/issues/113)) ([3e1d656](https://github.com/nevenincs/vaultspec-rag/commit/3e1d65632fe0a6e64b3dcf8a3de3a559c0043ef9))
- **service:** identity-verifying service_token round-trip ([#124](https://github.com/nevenincs/vaultspec-rag/issues/124), [#125](https://github.com/nevenincs/vaultspec-rag/issues/125)) ([bdb72b5](https://github.com/nevenincs/vaultspec-rag/commit/bdb72b56088ddad365eb2cf9c08e532dbc8df198))

### Bug Fixes

- **mcp:** server-side ASGI rewrite eliminates /mcp 307 redirect ([#126](https://github.com/nevenincs/vaultspec-rag/issues/126)) ([41d23e4](https://github.com/nevenincs/vaultspec-rag/commit/41d23e46ae9dcec033cea2fb5a1d6284593e0817))

## [0.2.8](https://github.com/nevenincs/vaultspec-rag/compare/vaultspec-rag-v0.2.7...vaultspec-rag-v0.2.8) (2026-05-03)

### Bug Fixes

- remove dense model deprecation and harden GPU subprocess tests ([87982aa](https://github.com/nevenincs/vaultspec-rag/commit/87982aa8e73696fd69b2607586216c080088ce8d))

## [0.2.7](https://github.com/nevenincs/vaultspec-rag/compare/vaultspec-rag-v0.2.6...vaultspec-rag-v0.2.7) (2026-05-03)

### Bug Fixes

- **cli:** split rebuild from index clean ([af86b08](https://github.com/nevenincs/vaultspec-rag/commit/af86b081e822f637f6988dd48dc91329baeb5160))
- **index:** keep vault docs out of code search ([1fffa8a](https://github.com/nevenincs/vaultspec-rag/commit/1fffa8a389188d05e42354cee715e7576601f168))
- **install:** add direct torch dependency ([7ee10a3](https://github.com/nevenincs/vaultspec-rag/commit/7ee10a34df4a476a513af903036d46ad35f7ec88))
- **install:** surface missing hf auth ([357fe88](https://github.com/nevenincs/vaultspec-rag/commit/357fe881e01a58afb1d8212f62b9d7203efd4545))
- **runtime:** address embedding review findings ([931ba06](https://github.com/nevenincs/vaultspec-rag/commit/931ba06f8f6af780eb83461fdd957719ac7bf31d))
- **runtime:** silence noisy local model warnings ([0de6346](https://github.com/nevenincs/vaultspec-rag/commit/0de63461567d84ff003f62d970798a74c9392e50))

## [0.2.6](https://github.com/nevenincs/vaultspec-rag/compare/vaultspec-rag-v0.2.5...vaultspec-rag-v0.2.6) (2026-04-28)

### Bug Fixes

- **deps:** bump vaultspec-core 0.1.14 → 0.1.16 (raises floor to `>=0.1.16`) to pick up the upstream fix for [vaultspec-core#85](https://github.com/nevenincs/vaultspec-core/issues/85), which moves `yaml.add_representer(_LiteralStr, ...)` out of module top level into a lazy, lock-guarded `_ensure_literal_representer()`. Importing `vaultspec_core` (and therefore `vaultspec_rag`) no longer hard-crashes when PyYAML is partially broken — e.g. a venv with `yaml/__init__.py` deleted. Verified locally with the full unit suite (477 passed) and the actual fragility probe (CLI `--version` survives a deleted `yaml/__init__.py`) ([d5617a3](https://github.com/nevenincs/vaultspec-rag/commit/d5617a3))

### Documentation

- **changelog:** drop the stale `## Unreleased` section that linked to a nonexistent PR #45; the work it described actually shipped in 0.2.1 via PRs #18 / #19 / #71 and was already credited there by release-please ([bb90689](https://github.com/nevenincs/vaultspec-rag/commit/bb90689))

## [0.2.5](https://github.com/nevenincs/vaultspec-rag/compare/vaultspec-rag-v0.2.4...vaultspec-rag-v0.2.5) (2026-04-27)

### Miscellaneous

- **uv:** drop the `pip-audit` dev dependency and route the CVE audit through the native `uv audit --locked --preview-features audit` command; CI job, justfile recipe, and pyproject pin comment updated accordingly ([5d69868](https://github.com/nevenincs/vaultspec-rag/commit/5d69868))
- **uv:** replace every `uv pip install` recovery hint and post-publish smoke check with `uv sync` / `uvx --prerelease=allow` flows; rephrase fourteen vault-doc prose mentions to drop the legacy installer name ([476e510](https://github.com/nevenincs/vaultspec-rag/commit/476e510))
- **vaultspec:** adopt the vaultspec-core 0.1.14 `providers.json` manifest format and add the `vaultspec-projectmanager` skill plus its agent persona and core MCP rule ([5c9c07f](https://github.com/nevenincs/vaultspec-rag/commit/5c9c07f))

## [0.2.4](https://github.com/nevenincs/vaultspec-rag/compare/vaultspec-rag-v0.2.3...vaultspec-rag-v0.2.4) (2026-04-25)

### Bug Fixes

- **deps:** pin tree-sitter-language-pack \<1.6.2 and drop project board workflow ([#85](https://github.com/nevenincs/vaultspec-rag/issues/85)) ([e4f8229](https://github.com/nevenincs/vaultspec-rag/commit/e4f8229aa13b0178dbdac170dd9563d93d432e25))
- **install:** close all PR-[#86](https://github.com/nevenincs/vaultspec-rag/issues/86) deferred audit findings ([#89](https://github.com/nevenincs/vaultspec-rag/issues/89)) ([#90](https://github.com/nevenincs/vaultspec-rag/issues/90)) ([72c6196](https://github.com/nevenincs/vaultspec-rag/commit/72c61962e1b2b220e473d18974d38f60d607c25d))
- **install:** handle scattered [tool.\*] pyprojects, real-world TOML edge cases, exit codes ([#83](https://github.com/nevenincs/vaultspec-rag/issues/83), [#84](https://github.com/nevenincs/vaultspec-rag/issues/84)) ([#86](https://github.com/nevenincs/vaultspec-rag/issues/86)) ([0ca2aaf](https://github.com/nevenincs/vaultspec-rag/commit/0ca2aafcf05ca6af554979c85b903d4afdee8329))

## [0.2.3](https://github.com/nevenincs/vaultspec-rag/compare/vaultspec-rag-v0.2.2...vaultspec-rag-v0.2.3) (2026-04-22)

### Features

- **install:** configure cu130 torch and actionable CPU-torch errors ([#81](https://github.com/nevenincs/vaultspec-rag/issues/81)) ([6e090f4](https://github.com/nevenincs/vaultspec-rag/commit/6e090f474094ef272ebcd8a0748533cd5f9cce13))
- **install:** configure cu130 torch index and actionable CPU-torch errors ([971b75c](https://github.com/nevenincs/vaultspec-rag/commit/971b75cd22dc2ac1aa3ec0e01b3e8dd41c1a7120))

### Bug Fixes

- **#68:** vault indexer memory + wall-clock — failure-safe streaming rebuild ([e3b6d84](https://github.com/nevenincs/vaultspec-rag/commit/e3b6d848dd44fe7480a195b052bc4fddde4cbb27))
- **indexer:** iteration 10 polish — dead branch, type hints, docstrings ([7739f46](https://github.com/nevenincs/vaultspec-rag/commit/7739f4608f4054feabe539ff920a3ddd99a2719a))
- **memory:** iteration 6 audit — concurrent reindex lock + observability ([1036085](https://github.com/nevenincs/vaultspec-rag/commit/1036085f53825299f5e6fd9a2daaad76801278fc))
- **perf:** iteration 9 — env overrides, clean=True schema reset, broader except ([debeb02](https://github.com/nevenincs/vaultspec-rag/commit/debeb02a505154d2b87a8a6f981784e9c9c577ce))
- **perf:** wall-clock — sort by length, smaller encode batch, max_seq cap ([0a7f22e](https://github.com/nevenincs/vaultspec-rag/commit/0a7f22e033f682af0f82032c3a5cdafcc8f5b767))

## [0.2.2](https://github.com/nevenincs/vaultspec-rag/compare/vaultspec-rag-v0.2.1...vaultspec-rag-v0.2.2) (2026-04-12)

### Bug Fixes

- **service:** roll back acquired ref_count if \_acquire raises mid-flight ([#77](https://github.com/nevenincs/vaultspec-rag/issues/77)) ([8c83e37](https://github.com/nevenincs/vaultspec-rag/commit/8c83e371554a16ea776427d0c39f3792cf864490))

## [0.2.1](https://github.com/nevenincs/vaultspec-rag/compare/vaultspec-rag-v0.2.0...vaultspec-rag-v0.2.1) (2026-04-12)

### Features

- add .vaultragignore support for codebase indexer ([#31](https://github.com/nevenincs/vaultspec-rag/issues/31)) ([a8f5e73](https://github.com/nevenincs/vaultspec-rag/commit/a8f5e7344c2dd37cfcc7c0bb0dc8b807accc0544))
- add CI/CD pipeline and fix all 76 ty type errors ([1569a7f](https://github.com/nevenincs/vaultspec-rag/commit/1569a7f1ebb9995022b7aedfd154d9cdba518bc0))
- add GPU CrossEncoder reranker as post-RRF step ([ff0569f](https://github.com/nevenincs/vaultspec-rag/commit/ff0569f1c6591452cc8b81abf729f6622d553a85))
- add service orchestration ADR, research, plan, and roadmap ([f1378dd](https://github.com/nevenincs/vaultspec-rag/commit/f1378dd3e90f8146e243b37fd601fb44a5bc6a66))
- add ServiceRegistry for multi-project state management ([#18](https://github.com/nevenincs/vaultspec-rag/issues/18)) ([ad151b4](https://github.com/nevenincs/vaultspec-rag/commit/ad151b40d9cb7d1c4faccbe52816553906381f7f))
- add vaultspec-rag.builtin.md rule + gitattributes eol=lf ([#54](https://github.com/nevenincs/vaultspec-rag/issues/54), [#47](https://github.com/nevenincs/vaultspec-rag/issues/47)) ([4d17df5](https://github.com/nevenincs/vaultspec-rag/commit/4d17df51a2cc2bc4d2fd1503ad5e69615a9527fe))
- add watcher support and expand RAG coverage ([df01b63](https://github.com/nevenincs/vaultspec-rag/commit/df01b630c35aca3a0c004a9697cd173900883dc9))
- align dev tooling with vaultspec-core conventions ([#9](https://github.com/nevenincs/vaultspec-rag/issues/9), [#13](https://github.com/nevenincs/vaultspec-rag/issues/13)) ([2334787](https://github.com/nevenincs/vaultspec-rag/commit/23347871626a4164eb0f87cab5000c53dce44f9a))
- centralize data paths under .vault/data/search-data/ + synthetic test corpus ([#32](https://github.com/nevenincs/vaultspec-rag/issues/32), [#33](https://github.com/nevenincs/vaultspec-rag/issues/33)) ([e9a90a6](https://github.com/nevenincs/vaultspec-rag/commit/e9a90a624da92fdf2f09ddd65e022645b90ed2a9))
- CI/CD pipeline and release automation ([9729abb](https://github.com/nevenincs/vaultspec-rag/commit/9729abbd659487ad9d32016595e0b9efde0261ce))
- complete architecture alignment with vaultspec-core ([80919f6](https://github.com/nevenincs/vaultspec-rag/commit/80919f6f24fd2ba33838bf1cf54afd3a1d710a7d))
- FastMCP lifespan, Starlette /health, ServiceRegistry integration ([#19](https://github.com/nevenincs/vaultspec-rag/issues/19)) ([d3d0905](https://github.com/nevenincs/vaultspec-rag/commit/d3d09054d6baeeddd391bab4d7c2faa5d42a8a50))
- GPU-only RAG pipeline (Qwen3-Embedding-0.6B + SPLADE v3 + Qdrant) ([908e619](https://github.com/nevenincs/vaultspec-rag/commit/908e6192d160a8704f25a0abfaa6e5e627c4440b))
- granular per-document progress reporting for index command ([f86174c](https://github.com/nevenincs/vaultspec-rag/commit/f86174cd91b66cd3b42e36b5d0ac9cd0d434f3c9))
- granular per-document progress reporting for index command ([f8e70dd](https://github.com/nevenincs/vaultspec-rag/commit/f8e70dda4b35a5668bcba0392cfb5cba8bcfa28f)), closes [#62](https://github.com/nevenincs/vaultspec-rag/issues/62)
- implement SEC-001–SEC-004 security hardening ([118f90c](https://github.com/nevenincs/vaultspec-rag/commit/118f90cec7dc5df6ad179cb28a1f85288233a0bb))
- migrate legacy docs/ to .vault/ and remove docs/ ([af1ed87](https://github.com/nevenincs/vaultspec-rag/commit/af1ed87fe36d07c46617da2dc9081adb5633ccfb))
- migrate pre-commit hooks + register MCP server ([#48](https://github.com/nevenincs/vaultspec-rag/issues/48), [#55](https://github.com/nevenincs/vaultspec-rag/issues/55)) ([570f715](https://github.com/nevenincs/vaultspec-rag/commit/570f71562e50601c5b54d89ba15e7f647d2cfb63))
- narrow GPU semaphore + multi-project watcher ([#22](https://github.com/nevenincs/vaultspec-rag/issues/22), [#23](https://github.com/nevenincs/vaultspec-rag/issues/23)) ([47b1657](https://github.com/nevenincs/vaultspec-rag/commit/47b1657d65678c838778bc278c727824a450b79d))
- service daemon commands and model prefetch ([#16](https://github.com/nevenincs/vaultspec-rag/issues/16), [#20](https://github.com/nevenincs/vaultspec-rag/issues/20)) ([a052433](https://github.com/nevenincs/vaultspec-rag/commit/a052433565b5fc130bf5863d45c9b5a7ccb80d8c))
- store eviction (TTL + LRU) and log rotation for the RAG service ([#71](https://github.com/nevenincs/vaultspec-rag/issues/71)) ([0eaf67f](https://github.com/nevenincs/vaultspec-rag/commit/0eaf67ff17f563ca4c0cc28739821405af51061a))
- switch to Python-native markdown tooling, add lychee and actionlint ([595ee9f](https://github.com/nevenincs/vaultspec-rag/commit/595ee9f333380cd66629a51c1bb5a901037c269d))
- unify graph cache with lock+TTL and dependency injection ([#14](https://github.com/nevenincs/vaultspec-rag/issues/14)) ([22db751](https://github.com/nevenincs/vaultspec-rag/commit/22db751f9ade8b71468d6959c53b4b0fdfb33501))
- vaultspec-rag install/uninstall — companion enrollment via core sync ([d215b40](https://github.com/nevenincs/vaultspec-rag/commit/d215b40d8554599a9eafcf61142ab9b1248ecec0))
- vaultspec-rag install/uninstall — companion enrollment via core sync ([2aa1364](https://github.com/nevenincs/vaultspec-rag/commit/2aa136447b2ca7fdee3290f0a4d0634d48c9ede2))

### Bug Fixes

- actionable error when another process holds the Qdrant lock ([d8d5c30](https://github.com/nevenincs/vaultspec-rag/commit/d8d5c30d0bac21a243cb18bb641f60e1239c9e7e))
- add check-provider-artifacts hook + deep audit + plan update ([db8cb21](https://github.com/nevenincs/vaultspec-rag/commit/db8cb2193d636825d01554b75b786e4814da5123))
- add related links to research doc (fixes vault dangling check) ([0fbfd99](https://github.com/nevenincs/vaultspec-rag/commit/0fbfd995b34d33496ec6f4f7c9001130a6b6302a))
- add UV_NO_SOURCES to release and publish workflows ([7da1ded](https://github.com/nevenincs/vaultspec-rag/commit/7da1ded68a505f2c369b496f493efa499583d4d6))
- add UV_NO_SOURCES to release-please and publish workflows ([0ef25ea](https://github.com/nevenincs/vaultspec-rag/commit/0ef25ea0bf38411f0fffd0da3a07bc4242933201))
- address code review findings — watcher lifecycle, shutdown race, lock scope ([8ec521d](https://github.com/nevenincs/vaultspec-rag/commit/8ec521d96fad644d8530e19852e0a01570e9f392))
- address code review findings for transport mode deconflation ([9943081](https://github.com/nevenincs/vaultspec-rag/commit/99430812e6cc0e05396d15b412a76bef9e6e0244))
- address gemini review findings on progress reporter and indexer ([77a931e](https://github.com/nevenincs/vaultspec-rag/commit/77a931e49c168a76c67b79e534f957ae92f7ac8a)), closes [#67](https://github.com/nevenincs/vaultspec-rag/issues/67)
- align dev tooling with core after audit review ([b546d1b](https://github.com/nevenincs/vaultspec-rag/commit/b546d1b73aae5483c11dd9e028f1bfeb2e35ef73))
- **build:** mirror companion-owned files into sdist force-include ([2d15305](https://github.com/nevenincs/vaultspec-rag/commit/2d1530541af42e5a083b28c5801687114aac19f8))
- CI uses UV_NO_SOURCES to bypass local dev overrides ([fdf1c9b](https://github.com/nevenincs/vaultspec-rag/commit/fdf1c9bbe87d518c31fe1a0d1a5ef48e27ffd080))
- complete markdown pipeline alignment with core ([bb28d2a](https://github.com/nevenincs/vaultspec-rag/commit/bb28d2a595a563b3a3da067edc667cbe6af243df))
- correct builtin rule accuracy + review audit ([#54](https://github.com/nevenincs/vaultspec-rag/issues/54)) ([7c76cb6](https://github.com/nevenincs/vaultspec-rag/commit/7c76cb612760f02ed4172d86f2186538d1f4b840))
- deconflate MCP transport modes — make project_root required in HTTP service mode ([dd07edc](https://github.com/nevenincs/vaultspec-rag/commit/dd07edcc51178f6ba075f10fc052cfe3a190c3b1))
- exclude .vaultspec/rules/skills/ from lychee link checker ([450c825](https://github.com/nevenincs/vaultspec-rag/commit/450c8257c8b6567a7caf2c6c6d6185ec6c996430))
- exclude torch and vaultspec-core from pip-audit export ([e2a699b](https://github.com/nevenincs/vaultspec-rag/commit/e2a699bceb33c38d729968befbaaa1344f9f71d8))
- exhaustive audit — watcher lifecycle, shutdown races, prompt/CLI fixes ([6a7e7ef](https://github.com/nevenincs/vaultspec-rag/commit/6a7e7efa061371f4114ede07a8b68ed0b44bc894))
- gitignore cleanup and vault-audit CI bug ([85c79ce](https://github.com/nevenincs/vaultspec-rag/commit/85c79cecdda31ca406a8fae7d081e5f43de9e010))
- harden transport mode deconflation ([992800b](https://github.com/nevenincs/vaultspec-rag/commit/992800bba627947dc64c4385b44a8ec2bda7104f))
- **install:** security hardening — symlink rejection, partial-seed rollback, path containment ([feea637](https://github.com/nevenincs/vaultspec-rag/commit/feea637e0aab1009d5196a500f22010723ee1f74))
- **install:** six review findings — global --target, uninstall self-bootstrap, partial-seed, onexc, ADR ([da2be36](https://github.com/nevenincs/vaultspec-rag/commit/da2be36ba0fb5e308cfd48ce5017dab538626572))
- **install:** use core's atomic_write per ADR; drop redundant skip subtraction ([ff7361c](https://github.com/nevenincs/vaultspec-rag/commit/ff7361c1db887bf0f0d81d258c3630a6eefa7618))
- make project_root required in HTTP service mode ([#56](https://github.com/nevenincs/vaultspec-rag/issues/56)) ([945edbc](https://github.com/nevenincs/vaultspec-rag/commit/945edbc9cea9315b8c9df7c182db56efde8961fd))
- MCP HTTP transport session manager never initialized ([b41f6f6](https://github.com/nevenincs/vaultspec-rag/commit/b41f6f667389a1491ce629e06f7f7b59792e2a54))
- **mcp-server:** parse argv in main() so --help does not require a GPU ([3ccb066](https://github.com/nevenincs/vaultspec-rag/commit/3ccb066bb6438e7f93ceaee3059df93044ea3902))
- narrow GPU lock in indexers — hold only during encode, not full_index ([bdf9249](https://github.com/nevenincs/vaultspec-rag/commit/bdf924953151a46fe2e6a88e62bf73f97b382196))
- pass --no-hashes to uv export for pip-audit ([94d74ac](https://github.com/nevenincs/vaultspec-rag/commit/94d74acd86f82c8f715e3118584b3f6c9a3b1ca8))
- publish vaultspec-rag to PyPI — fix release pipeline trigger and version manifest ([f6da869](https://github.com/nevenincs/vaultspec-rag/commit/f6da869a6071ffee66efa44948ff1b6e9a134a5b))
- publish vaultspec-rag to PyPI — fix release pipeline trigger and version manifest ([19267a4](https://github.com/nevenincs/vaultspec-rag/commit/19267a40eba4e32a7ab50f71c438766ba312ce1e)), closes [#65](https://github.com/nevenincs/vaultspec-rag/issues/65)
- **rag:** address gemini round-2 review findings ([#73](https://github.com/nevenincs/vaultspec-rag/issues/73)) ([80f9aa8](https://github.com/nevenincs/vaultspec-rag/commit/80f9aa8d91e954dc1db34f8df82f11afd793ed40))
- **rag:** address gemini round-3 review findings ([#74](https://github.com/nevenincs/vaultspec-rag/issues/74)) ([0f15ae4](https://github.com/nevenincs/vaultspec-rag/commit/0f15ae42b122729c8221ba8557e8b5a07673cee6))
- regenerate uv.lock with UV_NO_SOURCES=1 for CI compatibility ([5b67abb](https://github.com/nevenincs/vaultspec-rag/commit/5b67abb891f5818cdc23390685e6feb833bfedd0))
- remove .vault/\*.index.md from git (generated artifacts) ([effa0d8](https://github.com/nevenincs/vaultspec-rag/commit/effa0d8f85c5341604a477af769a77cdd2ac0c6f))
- remove \[[wiki-links]\] from HTML comments in vault docs ([52c3624](https://github.com/nevenincs/vaultspec-rag/commit/52c36244cc66cffc47f9c5fb2f4991e2e205ea91))
- remove editable vaultspec-core path from pyproject.toml + regenerate lock ([ca044c0](https://github.com/nevenincs/vaultspec-rag/commit/ca044c0d16ea831cf9ec4a7f68a2334ab54ee0fe))
- resolve 1 CRITICAL + 10 HIGH audit findings ([4c16af5](https://github.com/nevenincs/vaultspec-rag/commit/4c16af5b4ed085fd117f00ef1e15d6b6c6bce1f8))
- resolve all deferred audit items — zero remaining ([9214cdf](https://github.com/nevenincs/vaultspec-rag/commit/9214cdf7c2dc87efeb0a6aece7311b84cb071207))
- resolve all vault audit errors for CI ([3ad9506](https://github.com/nevenincs/vaultspec-rag/commit/3ad950646e539631eda15cd500e92cc93c06a07f))
- resolve CI failures — ty windll error and vault dangling links ([c2217d5](https://github.com/nevenincs/vaultspec-rag/commit/c2217d5870591fde17f9f2a40d39baad6428b629))
- resolve MEDIUM audit findings — thread safety, error handling, tests ([a171637](https://github.com/nevenincs/vaultspec-rag/commit/a171637b22207f2f3c18fb7f541d478ea574f9aa))
- resolve remaining LOW audit findings ([599b8fa](https://github.com/nevenincs/vaultspec-rag/commit/599b8fad845d15c02e4a57dfe524383e84bf75ef))
- resolve remaining OPEN audit findings (batch 2) ([27dc976](https://github.com/nevenincs/vaultspec-rag/commit/27dc9766b9496c5cf7fc7b66dfb14ce58ccbd035))
- resolve vaultspec-core from GitHub, remove UV_NO_SOURCES hack ([dd819f5](https://github.com/nevenincs/vaultspec-rag/commit/dd819f564985b63705715787b4e83b5044f8949e))
- run CrossEncoder rerank before graph boost in search_vault() ([2e0952d](https://github.com/nevenincs/vaultspec-rag/commit/2e0952dbdbdf204731f16f16ba4cd8b71a94d634))
- **service:** tear down popped victims if \_acquire raises mid-flight ([#75](https://github.com/nevenincs/vaultspec-rag/issues/75)) ([9c87aed](https://github.com/nevenincs/vaultspec-rag/commit/9c87aed027028c4f45296f6051f7560d23a363c5))
- **tests:** accept threading.RLock in ServiceRegistry lock regression ([#76](https://github.com/nevenincs/vaultspec-rag/issues/76)) ([825d1c6](https://github.com/nevenincs/vaultspec-rag/commit/825d1c65fad84b72e24e508db3a90bf6ef806756))
- warmup tests need GPU (mark integration), pip-audit --frozen→--locked ([69d26fe](https://github.com/nevenincs/vaultspec-rag/commit/69d26fee8c77dfbed8ec4d4189ecc22036794fda))

## [0.2.0a0](https://github.com/nevenincs/vaultspec-rag/compare/vaultspec-rag-v0.1.4...vaultspec-rag-v0.2.0a0) (2026-04-06)

First alpha release. This milestone collects all work since 0.1.1 into a single
pre-release suitable for early adopter testing.

### Service orchestration

- Service orchestration layer with multi-project routing ([#21](https://github.com/nevenincs/vaultspec-rag/pull/21))
- Narrow GPU semaphore, shared CrossEncoder, per-root locks, multi-project watcher ([#30](https://github.com/nevenincs/vaultspec-rag/pull/30))

### Dev tooling

- Full architecture alignment with vaultspec-core ([#26](https://github.com/nevenincs/vaultspec-rag/pull/26))

### Documentation

- Documentation rewrite and MCP registration guide ([#27](https://github.com/nevenincs/vaultspec-rag/pull/27))

### CLI polish

- pyproject metadata, `doctor` command, `--json` output, `__main__.py` entrypoint ([#29](https://github.com/nevenincs/vaultspec-rag/pull/29))

### Test framework

- Test framework overhaul with centralized data paths and synthetic corpus ([#35](https://github.com/nevenincs/vaultspec-rag/pull/35))

### .vaultragignore

- `.vaultragignore` support for codebase indexer ([#36](https://github.com/nevenincs/vaultspec-rag/pull/36))

### Security hardening

- `project_root` validation and `/health` endpoint hardening ([#37](https://github.com/nevenincs/vaultspec-rag/pull/37))

### Integration tests

- Service lifecycle integration tests with HTTP transport ([#38](https://github.com/nevenincs/vaultspec-rag/pull/38))

______________________________________________________________________

## [0.1.4](https://github.com/nevenincs/vaultspec-rag/compare/vaultspec-rag-v0.1.3...vaultspec-rag-v0.1.4) (2026-04-06)

### Features

- add .vaultragignore support for codebase indexer ([#31](https://github.com/nevenincs/vaultspec-rag/issues/31)) ([a8f5e73](https://github.com/nevenincs/vaultspec-rag/commit/a8f5e7344c2dd37cfcc7c0bb0dc8b807accc0544))
- centralize data paths under .vault/data/search-data/ + synthetic test corpus ([#32](https://github.com/nevenincs/vaultspec-rag/issues/32), [#33](https://github.com/nevenincs/vaultspec-rag/issues/33)) ([e9a90a6](https://github.com/nevenincs/vaultspec-rag/commit/e9a90a624da92fdf2f09ddd65e022645b90ed2a9))
- implement SEC-001–SEC-004 security hardening ([118f90c](https://github.com/nevenincs/vaultspec-rag/commit/118f90cec7dc5df6ad179cb28a1f85288233a0bb))
- narrow GPU semaphore + multi-project watcher ([#22](https://github.com/nevenincs/vaultspec-rag/issues/22), [#23](https://github.com/nevenincs/vaultspec-rag/issues/23)) ([47b1657](https://github.com/nevenincs/vaultspec-rag/commit/47b1657d65678c838778bc278c727824a450b79d))

### Bug Fixes

- add related links to research doc (fixes vault dangling check) ([0fbfd99](https://github.com/nevenincs/vaultspec-rag/commit/0fbfd995b34d33496ec6f4f7c9001130a6b6302a))
- address code review findings — watcher lifecycle, shutdown race, lock scope ([8ec521d](https://github.com/nevenincs/vaultspec-rag/commit/8ec521d96fad644d8530e19852e0a01570e9f392))
- exclude .vaultspec/rules/skills/ from lychee link checker ([450c825](https://github.com/nevenincs/vaultspec-rag/commit/450c8257c8b6567a7caf2c6c6d6185ec6c996430))
- MCP HTTP transport session manager never initialized ([b41f6f6](https://github.com/nevenincs/vaultspec-rag/commit/b41f6f667389a1491ce629e06f7f7b59792e2a54))
- narrow GPU lock in indexers — hold only during encode, not full_index ([bdf9249](https://github.com/nevenincs/vaultspec-rag/commit/bdf924953151a46fe2e6a88e62bf73f97b382196))
- regenerate uv.lock with UV_NO_SOURCES=1 for CI compatibility ([5b67abb](https://github.com/nevenincs/vaultspec-rag/commit/5b67abb891f5818cdc23390685e6feb833bfedd0))
- remove .vault/\*.index.md from git (generated artifacts) ([effa0d8](https://github.com/nevenincs/vaultspec-rag/commit/effa0d8f85c5341604a477af769a77cdd2ac0c6f))
- remove \[[wiki-links]\] from HTML comments in vault docs ([52c3624](https://github.com/nevenincs/vaultspec-rag/commit/52c36244cc66cffc47f9c5fb2f4991e2e205ea91))
- resolve all vault audit errors for CI ([3ad9506](https://github.com/nevenincs/vaultspec-rag/commit/3ad950646e539631eda15cd500e92cc93c06a07f))
- resolve CI failures — ty windll error and vault dangling links ([c2217d5](https://github.com/nevenincs/vaultspec-rag/commit/c2217d5870591fde17f9f2a40d39baad6428b629))
- warmup tests need GPU (mark integration), pip-audit --frozen→--locked ([69d26fe](https://github.com/nevenincs/vaultspec-rag/commit/69d26fee8c77dfbed8ec4d4189ecc22036794fda))

## [0.1.3](https://github.com/nevenincs/vaultspec-rag/compare/vaultspec-rag-v0.1.2...vaultspec-rag-v0.1.3) (2026-04-03)

### Features

- complete architecture alignment with vaultspec-core ([80919f6](https://github.com/nevenincs/vaultspec-rag/commit/80919f6f24fd2ba33838bf1cf54afd3a1d710a7d))

### Bug Fixes

- complete markdown pipeline alignment with core ([bb28d2a](https://github.com/nevenincs/vaultspec-rag/commit/bb28d2a595a563b3a3da067edc667cbe6af243df))
- gitignore cleanup and vault-audit CI bug ([85c79ce](https://github.com/nevenincs/vaultspec-rag/commit/85c79cecdda31ca406a8fae7d081e5f43de9e010))

## [0.1.2](https://github.com/nevenincs/vaultspec-rag/compare/vaultspec-rag-v0.1.1...vaultspec-rag-v0.1.2) (2026-04-03)

### Features

- add service orchestration ADR, research, plan, and roadmap ([f1378dd](https://github.com/nevenincs/vaultspec-rag/commit/f1378dd3e90f8146e243b37fd601fb44a5bc6a66))
- add ServiceRegistry for multi-project state management ([#18](https://github.com/nevenincs/vaultspec-rag/issues/18)) ([ad151b4](https://github.com/nevenincs/vaultspec-rag/commit/ad151b40d9cb7d1c4faccbe52816553906381f7f))
- FastMCP lifespan, Starlette /health, ServiceRegistry integration ([#19](https://github.com/nevenincs/vaultspec-rag/issues/19)) ([d3d0905](https://github.com/nevenincs/vaultspec-rag/commit/d3d09054d6baeeddd391bab4d7c2faa5d42a8a50))
- migrate legacy docs/ to .vault/ and remove docs/ ([af1ed87](https://github.com/nevenincs/vaultspec-rag/commit/af1ed87fe36d07c46617da2dc9081adb5633ccfb))
- service daemon commands and model prefetch ([#16](https://github.com/nevenincs/vaultspec-rag/issues/16), [#20](https://github.com/nevenincs/vaultspec-rag/issues/20)) ([a052433](https://github.com/nevenincs/vaultspec-rag/commit/a052433565b5fc130bf5863d45c9b5a7ccb80d8c))
- unify graph cache with lock+TTL and dependency injection ([#14](https://github.com/nevenincs/vaultspec-rag/issues/14)) ([22db751](https://github.com/nevenincs/vaultspec-rag/commit/22db751f9ade8b71468d6959c53b4b0fdfb33501))

### Bug Fixes

- resolve 1 CRITICAL + 10 HIGH audit findings ([4c16af5](https://github.com/nevenincs/vaultspec-rag/commit/4c16af5b4ed085fd117f00ef1e15d6b6c6bce1f8))
- resolve MEDIUM audit findings — thread safety, error handling, tests ([a171637](https://github.com/nevenincs/vaultspec-rag/commit/a171637b22207f2f3c18fb7f541d478ea574f9aa))
- resolve remaining LOW audit findings ([599b8fa](https://github.com/nevenincs/vaultspec-rag/commit/599b8fad845d15c02e4a57dfe524383e84bf75ef))
- resolve remaining OPEN audit findings (batch 2) ([27dc976](https://github.com/nevenincs/vaultspec-rag/commit/27dc9766b9496c5cf7fc7b66dfb14ce58ccbd035))

## [0.1.1](https://github.com/nevenincs/vaultspec-rag/compare/vaultspec-rag-v0.1.0...vaultspec-rag-v0.1.1) (2026-04-01)

### Features

- add CI/CD pipeline and fix all 76 ty type errors ([1569a7f](https://github.com/nevenincs/vaultspec-rag/commit/1569a7f1ebb9995022b7aedfd154d9cdba518bc0))
- add GPU CrossEncoder reranker as post-RRF step ([ff0569f](https://github.com/nevenincs/vaultspec-rag/commit/ff0569f1c6591452cc8b81abf729f6622d553a85))
- add watcher support and expand RAG coverage ([df01b63](https://github.com/nevenincs/vaultspec-rag/commit/df01b630c35aca3a0c004a9697cd173900883dc9))
- CI/CD pipeline and release automation ([9729abb](https://github.com/nevenincs/vaultspec-rag/commit/9729abbd659487ad9d32016595e0b9efde0261ce))
- GPU-only RAG pipeline (Qwen3-Embedding-0.6B + SPLADE v3 + Qdrant) ([908e619](https://github.com/nevenincs/vaultspec-rag/commit/908e6192d160a8704f25a0abfaa6e5e627c4440b))

### Bug Fixes

- add UV_NO_SOURCES to release and publish workflows ([7da1ded](https://github.com/nevenincs/vaultspec-rag/commit/7da1ded68a505f2c369b496f493efa499583d4d6))
- add UV_NO_SOURCES to release-please and publish workflows ([0ef25ea](https://github.com/nevenincs/vaultspec-rag/commit/0ef25ea0bf38411f0fffd0da3a07bc4242933201))
- CI uses UV_NO_SOURCES to bypass local dev overrides ([fdf1c9b](https://github.com/nevenincs/vaultspec-rag/commit/fdf1c9bbe87d518c31fe1a0d1a5ef48e27ffd080))
- run CrossEncoder rerank before graph boost in search_vault() ([2e0952d](https://github.com/nevenincs/vaultspec-rag/commit/2e0952dbdbdf204731f16f16ba4cd8b71a94d634))

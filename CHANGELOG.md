# Changelog

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

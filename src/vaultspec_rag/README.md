# vaultspec-rag

vaultspec-rag is the companion search toolkit for
[vaultspec-core](https://github.com/nevenincs/vaultspec-core): a semantic retrieval engine
for codebases and the architecture decisions behind them. It runs on an NVIDIA GPU with
CUDA on Windows or Linux, or on Apple silicon.

Code search collapses locale variants with similar relevance scores by default. Pass
`--no-dedup-locales` to inspect each variant or `--dedup-locales` to enable collapse
for a search. Pass `--prefer production`, `--prefer tests`, or
`--prefer documentation` to favor that kind of code while keeping other results:

```bash
vaultspec-rag search "translation lookup" --type code --no-dedup-locales
vaultspec-rag search "encode batch" --type code --prefer tests
```

Installation, usage, and configuration are in the
[project README](https://github.com/nevenincs/vaultspec-rag#readme). Report issues on the
[issue tracker](https://github.com/nevenincs/vaultspec-rag/issues).

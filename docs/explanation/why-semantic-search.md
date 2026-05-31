# Why semantic search?

If you already live in `grep`, `ripgrep`, or your editor's project-wide find, the honest question is: why add another search tool? Keyword search is fast, predictable, and almost certainly already in your shell. It isn't going anywhere, and it shouldn't.

This page is about the gap it leaves.

## The gap keyword search leaves

Keyword search matches characters. That's its strength and its ceiling. A search for `rate limiting` finds files containing the literal string `rate limiting`. It does not find the file where someone called the same idea `request throttling`, or `backpressure`, or `429 handling`, or `token bucket`. Those files exist. You wrote some of them. You just can't remember which word past-you reached for.

In a small codebase you patch around this by trying three or four queries until something hits. In a vault of architectural notes, research, ADRs, and a few thousand source files, that strategy runs out of patience before it runs out of synonyms. The cost isn't a missed file. It's the slow, corrosive sense that information you know exists is unreachable from the words you currently have.

## What semantic search does differently

Semantic search compares meaning rather than spelling. Each document and each query gets turned into a vector, a numeric fingerprint that captures roughly what the text is about. The tool then finds documents whose fingerprints sit near the query's. "Near" here means conceptually adjacent, not lexically identical.

The practical effect: a query for `rate limiting` surfaces the throttling note, the 429 retry policy, and the token bucket ADR, even when none of them contain the phrase you typed. You ask in your words. The index answers in its words, on your behalf.

This is also why the tool feels different at the prompt. You stop guessing keywords and start asking questions. `how do we handle slow clients` is a reasonable query. `grep` would laugh at it; semantic search treats it as a description of what you're looking for.

## What it costs

Nothing here is free.

Indexing takes time and disk. The first index of a large vault and codebase runs for minutes, not seconds, and the index itself is sizeable. Embedding models run on the GPU, so a capable card is part of the deal. Incremental updates are cheap once the index exists, but the initial build is a real commitment.

Semantic search also gives up exact-match guarantees. If you need every occurrence of `MAX_RETRIES = 5`, or you're hunting a specific error string, or you want to refactor a symbol across files, the right tool is still the one that matches characters. Semantic similarity is fuzzy by design; it ranks rather than enumerates, and ranking can be wrong.

And the answers depend on a model. A different embedding model would surface a slightly different set of files for the same query. That's worth knowing before you treat the top result as authoritative.

## A working rule of thumb

Reach for `grep -r` or `ripgrep` when you know the string. Function names, error messages, configuration keys, anything where the exact characters are the point. They will always be faster and more honest about what they did and didn't find.

Reach for `vaultspec-rag search` when you know the idea but not the words. Cross-document questions, "where did we discuss x", finding related work in a vault that has grown past the point where you remember which note used which phrasing.

Most days you'll want both, in that order. Semantic search to locate the neighbourhood, keyword search to pin down the exact line.

For the mechanics behind the fingerprints, see [how it works](how-it-works.md).

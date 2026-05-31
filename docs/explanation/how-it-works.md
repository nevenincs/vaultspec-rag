# How vaultspec-rag works

You type a query, press Enter, and a ranked list of files appears almost instantly. This page explains what happens in between, and why the results often include things you didn't literally type.

## The core idea

vaultspec-rag does most of its work before you ever run a search. When you index a project, the tool reads your files, breaks them into small pieces called chunks, and computes a numeric representation for each chunk. That representation - a list of numbers that captures the meaning of the text - is what makes search fast and meaning-aware.

When you search, the same kind of representation is computed for your query, and the tool finds the chunks whose numbers sit closest to it. Closeness in number-space corresponds to closeness in meaning. That is the whole trick.

## Indexing: doing the slow work upfront

Indexing has three stages, all done ahead of time:

- **Read.** The tool walks your project and collects the files it should index.
- **Chunk.** Each file is split into pieces small enough to be useful as a search result. A whole 2,000-line file is not a useful answer; a single function or a single paragraph is.
- **Represent.** Each chunk is turned into its numeric representation and stored, along with metadata like the file path and line numbers.

Pre-computing all this matters because the expensive part - turning text into numbers - happens once per chunk, not once per search. At query time, only your short query needs fresh processing, so results come back in a few hundred milliseconds.

## Searching: finding the closest neighbours

When you search, the tool:

- Computes the numeric representation of your query.
- Compares it against every stored chunk.
- Returns the chunks whose numbers are closest.

This is why a query for "how do I cancel a running job" can surface a chunk that talks about "stopping in-flight tasks" without sharing a single keyword. The two phrases sit near each other in number-space because they mean similar things. Traditional keyword search would miss this; meaning-based search catches it.

## The Score column

Every result comes with a score. The score measures how close that chunk's numbers are to your query's numbers. Higher means closer, which means a stronger match. Scores are useful for comparing results within a single search; they are not absolute ratings. A top result with a score of 0.7 in one search is not directly comparable to a 0.7 in another search on a different corpus.

If the top score is much higher than the rest, the leading result is probably what you want. If the top few scores are bunched together, the tool is telling you several chunks are plausible and you should skim them.

## Two indexes, two shapes of content

vaultspec-rag maintains two separate indexes: one for your vault (the `.md` documentation files) and one for your codebase (source files). They are separate because documentation and code have different shapes, and the right way to chunk them differs.

- **Documentation** flows in paragraphs and sections. Splitting by paragraph keeps each chunk readable and topically coherent.
- **Code** is structured around functions and classes. Splitting by those boundaries means a search result lands on a whole function rather than a random midpoint inside one.

Keeping the two indexes separate also lets you search just docs, just code, or both, depending on what you're looking for.

## What the GPU is for

Three small models run on the GPU during indexing and search.

Two of them compute the numeric representation of text. They look at meaning from different angles - one captures broad semantic similarity, the other captures the specific words and phrases that matter - and their results are combined. Combining two angles on the meaning so neither one dominates is called hybrid search, and it gives better results than either angle alone.

The third model runs only at the end, on the top candidates. It re-reads the query alongside each candidate and produces a sharper judgement of how well they actually match. This re-ranking step cleans up the ordering so the best result is more reliably at the top.

These models are small enough to fit comfortably on a consumer GPU, but they're the reason the tool needs one at all. For the longer answer, see [Why a GPU](why-gpu.md).

## What this tool is not

vaultspec-rag is a search engine, not an assistant. It does not:

- Generate code or write documentation.
- Summarise files or answer questions in prose.
- Hold a conversation or remember previous searches.

What it does is index your files and return ranked locations. The thinking afterwards is still yours, or your editor's, or whichever assistant you hand the results to next.

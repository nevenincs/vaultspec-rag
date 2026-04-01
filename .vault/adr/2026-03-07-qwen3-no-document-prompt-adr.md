---
tags:
  - "#adr"
  - "#gpu-rag-stack"
date: 2026-03-07
related:
  - "[[2026-03-06-gpu-only-rag-stack-adr]]"
  - "[[2026-03-09-qwen3-task-prefix-verification-research]]"
---

# ADR: Qwen3-Embedding encodes documents without prompt, queries with `prompt_name="query"`

## Status

Accepted

## Context

Qwen/Qwen3-Embedding-0.6B supports asymmetric retrieval with different
encoding for queries vs documents. The model ships with predefined prompts
in `model.prompts`. Incorrect prompt usage can degrade retrieval performance
by 1-5% (per the Qwen3 model card).

## Decision

- **Queries**: `model.encode(texts, prompt_name="query")` -- prepends the
  built-in instruction prefix.
- **Documents**: `model.encode(texts)` -- no prompt, no `prompt_name`.

## Rationale

The model's prompt configuration (verified via runtime inspection):

```python
model.prompts = {
    'query': 'Instruct: Given a web search query, retrieve relevant passages that answer the query\nQuery:',
    'document': '',  # empty string
}
model.default_prompt_name = None
```

1. **Query prompt is meaningful**: the `"query"` prompt prepends an instruction
   that tells the model to optimize for retrieval. Omitting it drops
   performance 1-5%.

2. **Document prompt is empty**: `prompt_name="document"` prepends an empty
   string -- functionally identical to omitting it. Explicitly passing it is
   harmless but unnecessary.

3. **`prompt` overrides `prompt_name`**: if both are provided, `prompt` takes
   priority. This allows custom code-specific instructions:

   ```python
   model.encode(queries, prompt="Instruct: Given a code search query, retrieve relevant source code\nQuery:")
   ```

4. **Current codebase is correct**: `embeddings.py` already uses
   `prompt_name="query"` for queries and omits it for documents.

## Consequences

- No code changes needed -- current implementation is correct.
- Future code-specific prompt optimization can use `prompt=` parameter
  without changing the document encoding path.
- Any new embedding methods must follow the same pattern: queries get
  `prompt_name="query"`, documents get no prompt.

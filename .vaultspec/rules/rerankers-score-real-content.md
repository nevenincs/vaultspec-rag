---
name: rerankers-score-real-content
---

# Rerankers score real content

## Rule

- Feed the reranker the token-bounded full candidate content.
- Never feed it a display snippet, a title, or any fixed-width prefix.

## Why

- A fixed-character snippet discards the model's semantic capacity and biases
  ranking toward candidates whose opening characters echo the query.
- It passes every test while silently degrading ranking quality.

## How

- Good: carry the full content on the result object, cap it at a generous
  multiple of the token bound, and let the reranker's tokenizer truncate.
- Bad: passing the display snippet as the document side.

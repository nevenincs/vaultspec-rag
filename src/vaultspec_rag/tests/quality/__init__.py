"""Intent-aware search-quality evaluation support.

Holds the graded-relevance rubric, the role-aware ranking metrics, and the
labeled query set used by the intent-ranking integration harness. These are
evaluation *support* modules (data + pure functions), not test modules; the
gating test lives under ``tests/integration/test_intent_ranking.py``.
"""

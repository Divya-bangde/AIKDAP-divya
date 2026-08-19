"""Operational health: what is working, what is degraded, and why.

Implemented in Sprint 9G. The module answers `GET /health` for the
whole platform — database, cache, worker, reranker, and every
configured LLM provider — without spending money, GPU time, or model
quota to do it. See `service.py` for how each component is checked and
why that check was chosen.
"""

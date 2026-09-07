"""Sprint 16 Phase 8.1 evaluation harness.

Deliberately isolated from `app/`: this package scores production
decision logic (imported, never duplicated) against a hand-curated
benchmark. It must never be imported BY production code -- the
dependency points one way, evaluation -> app, never app -> evaluation.
"""

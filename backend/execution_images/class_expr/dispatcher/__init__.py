"""Sprint 16 Phase 7B.26 -- the EVALUATE_EXPRESSION dispatcher.

Runs inside the class_expr execution image ONLY. Every fact about its
stdin/stdout protocol, exit-code contract, and evaluator boundary was
INVENTED this phase -- `execution_launcher/docker_policy.py` fixes only
the argv (`python3 -m dispatcher --operation evaluate_expression`);
nothing else about this module pre-existed anywhere in the repository.
See `__main__.py` for the contract itself.
"""

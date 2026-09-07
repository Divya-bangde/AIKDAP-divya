"""Sprint 16 Phase 7B.3 -- guard-layer implementation slice.

This package implements ONLY the pre-Docker security boundary designed in
Phase 7B.1/7B.2:

    LaunchRequest -> build_candidate() -> CandidateLaunchSpec
        -> validate_and_approve() -> ApprovedLaunchSpec

No Docker SDK is imported anywhere in this package. No container is ever
created. `docker_policy.py` is reserved as the ONLY module that would ever
import the Docker SDK in a future slice -- it does not do so yet.
"""

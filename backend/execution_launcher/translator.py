"""Part E: candidate construction (the "translator" layer).

`build_candidate()` is intentionally the LOWER-trust layer: it is allowed
to have bugs, because `docker_policy.validate_and_approve()` re-derives
and checks everything it produces. It never talks to Docker either -- it
only builds a `CandidateLaunchSpec` value from fixed constants, the
resource-class table, and the closed operation catalog, exactly like the
guard does, so that a correctly-functioning translator's output always
passes the guard, while tests can still construct deliberately-wrong
`CandidateLaunchSpec` values directly (bypassing this function entirely)
to simulate the translator-bug scenarios in Phase 7B.2 Part E.
"""

from __future__ import annotations

from execution_launcher.docker_policy import (
    _DISPATCH_COMMAND,
    _FIXED_CAP_ADD,
    _FIXED_CAP_DROP,
    _FIXED_DEVICES,
    _FIXED_ENTRYPOINT,
    _FIXED_IPC_MODE,
    _FIXED_NETWORK_MODE,
    _FIXED_PID_MODE,
    _FIXED_PRIVILEGED,
    _FIXED_READ_ONLY,
    _FIXED_SECURITY_OPT,
    _FIXED_USER,
    _APPROVED_IMAGE_DIGESTS,
    _OPERATION_CATALOG,
    _RESOURCE_CLASS_CONFIG,
    _expected_environment,
    _expected_mounts,
)
from execution_launcher.models import CandidateLaunchSpec, InputResolver, LaunchRequest, SecurityBlocked


async def build_candidate(request: LaunchRequest, resolver: InputResolver) -> CandidateLaunchSpec:
    """Builds a `CandidateLaunchSpec` for `request`. Raises `SecurityBlocked`
    early for a request whose operation/capability/resource_class are
    inconsistent or whose inputs cannot be resolved -- the same failure
    modes the guard independently re-checks, so a malformed request never
    even reaches a mismatched-but-constructible candidate.

    Async (Phase 7B.6): awaits `_expected_mounts()` -- same reasoning as
    `docker_policy.validate_and_approve()`.
    """
    catalog_entry = _OPERATION_CATALOG.get(request.operation)
    if catalog_entry is None:
        raise SecurityBlocked("unknown_operation", str(request.operation))
    expected_capability, expected_resource_class = catalog_entry
    if request.capability != expected_capability:
        raise SecurityBlocked(
            "capability_mismatch",
            f"operation {request.operation} implies {expected_capability}, "
            f"request declared {request.capability}",
        )
    if request.resource_class != expected_resource_class:
        raise SecurityBlocked(
            "resource_class_mismatch",
            f"operation {request.operation} implies {expected_resource_class}, "
            f"request declared {request.resource_class}",
        )

    class_config = _RESOURCE_CLASS_CONFIG[expected_resource_class]
    image = _APPROVED_IMAGE_DIGESTS[expected_resource_class]
    mounts = await _expected_mounts(request, resolver)
    environment = _expected_environment(expected_resource_class, class_config, request)
    command = _DISPATCH_COMMAND[request.operation]

    return CandidateLaunchSpec(
        request=request,
        image=image,
        network_mode=_FIXED_NETWORK_MODE,
        privileged=_FIXED_PRIVILEGED,
        cap_drop=_FIXED_CAP_DROP,
        cap_add=_FIXED_CAP_ADD,
        security_opt=_FIXED_SECURITY_OPT,
        read_only=_FIXED_READ_ONLY,
        user=_FIXED_USER,
        mem_limit_mb=class_config.memory_mb,
        memswap_limit_mb=class_config.memory_mb,
        cpus=class_config.cpus,
        pids_limit=class_config.pids_limit,
        tmpfs_mb=class_config.tmpfs_mb,
        mounts=mounts,
        environment=environment,
        command=command,
        entrypoint=_FIXED_ENTRYPOINT,
        devices=_FIXED_DEVICES,
        pid_mode=_FIXED_PID_MODE,
        ipc_mode=_FIXED_IPC_MODE,
        timeout_s=class_config.timeout_s,
    )

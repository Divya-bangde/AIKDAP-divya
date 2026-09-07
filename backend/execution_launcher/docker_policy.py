"""Sprint 16 Phase 7B.3 -- the guard layer.

THIS MODULE MUST NEVER IMPORT THE DOCKER SDK IN THIS SLICE. It is reserved
as the ONLY module that would do so in a FUTURE slice, once a Docker call
is actually authorized (Phase 7B.2 Part 2/H). Everything below is pure
Python: dict lookups, dataclass construction, and equality comparisons.
There is no `import docker`, no socket, no subprocess, no filesystem
access, and no network call anywhere in this file.

`validate_and_approve()` is the single entry point. It never trusts a
`CandidateLaunchSpec`'s Docker-shaped fields -- for every one of Phase
7B.2's Part C / Part G checks, it independently RE-DERIVES the expected
value from the candidate's embedded `LaunchRequest` and the fixed catalogs
below, then compares. A candidate field is used for exactly one purpose:
comparison against the independently-derived expectation. `ApprovedLaunchSpec`
is built field-by-field from the derived values, never by copying or
lightly editing the candidate -- so an unexpected candidate field cannot
survive into the approved object (Part J), and there is no field on
`ApprovedLaunchSpec` capable of holding one anyway (see its docstring).
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from execution_launcher.models import (
    ApprovedLaunchSpec,
    CandidateLaunchSpec,
    ExecutionCapability,
    ExecutionOperation,
    InputResolutionError,
    InputResolver,
    LaunchRequest,
    MountSpec,
    ResourceClass,
    SecurityBlocked,
)

# ---------------------------------------------------------------------------
# Fixed, non-negotiable Docker security posture (Phase 7B.1 Part 11/18,
# 7B.2 Part C). None of these vary by resource class, capability, or
# request -- they are constants precisely because Docker's own defaults
# fail OPEN (missing --network defaults to bridge, missing --cap-drop
# defaults to full capabilities), so the guard must always assert
# PRESENCE of the safe value rather than assume absence is safe.
# ---------------------------------------------------------------------------

_FIXED_NETWORK_MODE = "none"
_FIXED_PRIVILEGED = False
_FIXED_CAP_DROP: tuple[str, ...] = ("ALL",)
_FIXED_CAP_ADD: tuple[str, ...] = ()
_FIXED_SECURITY_OPT: tuple[str, ...] = ("no-new-privileges",)
_FIXED_READ_ONLY = True
_FIXED_USER = "10001:10001"
_FIXED_DEVICES: tuple[str, ...] = ()
_FIXED_PID_MODE: str | None = None
_FIXED_IPC_MODE: str | None = None
_FIXED_ENTRYPOINT: tuple[str, ...] | None = None
_DOCKER_SOCKET_MARKERS = ("docker.sock", "/var/run/docker")


# ---------------------------------------------------------------------------
# Resource classes (Phase 7A.5-derived, PROVISIONAL -- Part C of this
# phase's prompt). These are NOT claimed production-safe; n=3 synthetic
# benchmark samples back CPU/memory/timeout/pids only. `tmpfs_mb` was not
# independently benchmarked anywhere in this session's evidence and is a
# conservative placeholder pending its own review (flagged again in the
# final report's evidence classification, not silently presented as
# equally well-grounded).
#
# CLASS_ARRAY was profiled across a CPU=1.0-2.0 range; this slice fixes a
# single approved value (1.0, the more conservative bound) because a
# resource class must resolve to one exact value for equality-based guard
# checks to be meaningful. Widening to a second approved variant is a
# future decision, not one this slice invents.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ResourceClassConfig:
    cpus: float
    memory_mb: int
    timeout_s: float
    pids_limit: int
    tmpfs_mb: int


_RESOURCE_CLASS_CONFIG: dict[ResourceClass, ResourceClassConfig] = {
    ResourceClass.CLASS_EXPR: ResourceClassConfig(
        cpus=1.0, memory_mb=256, timeout_s=10.0, pids_limit=32, tmpfs_mb=64
    ),
    ResourceClass.CLASS_ARRAY: ResourceClassConfig(
        cpus=1.0, memory_mb=512, timeout_s=5.0, pids_limit=32, tmpfs_mb=64
    ),
    ResourceClass.CLASS_TABLE: ResourceClassConfig(
        cpus=1.0, memory_mb=512, timeout_s=10.0, pids_limit=32, tmpfs_mb=64
    ),
}


# ---------------------------------------------------------------------------
# Closed operation catalog (Part D). Plain dict lookups only -- no
# getattr(), no eval(), no exec(), no caller-supplied command string.
# ---------------------------------------------------------------------------

_OPERATION_CATALOG: dict[ExecutionOperation, tuple[ExecutionCapability, ResourceClass]] = {
    ExecutionOperation.EVALUATE_EXPRESSION: (
        ExecutionCapability.EVALUATE_EXPRESSION,
        ResourceClass.CLASS_EXPR,
    ),
    ExecutionOperation.MATMUL: (ExecutionCapability.ARRAY_COMPUTE, ResourceClass.CLASS_ARRAY),
    ExecutionOperation.PERCENTILE: (ExecutionCapability.ARRAY_COMPUTE, ResourceClass.CLASS_ARRAY),
    ExecutionOperation.MEAN: (ExecutionCapability.ARRAY_COMPUTE, ResourceClass.CLASS_ARRAY),
    ExecutionOperation.STD: (ExecutionCapability.ARRAY_COMPUTE, ResourceClass.CLASS_ARRAY),
    ExecutionOperation.CORRCOEF: (ExecutionCapability.ARRAY_COMPUTE, ResourceClass.CLASS_ARRAY),
    ExecutionOperation.GROUPBY_AGG: (ExecutionCapability.TABLE_COMPUTE, ResourceClass.CLASS_TABLE),
    ExecutionOperation.PIVOT_TABLE: (ExecutionCapability.TABLE_COMPUTE, ResourceClass.CLASS_TABLE),
}

# One fixed, closed command per operation. The value is a fixed argv tuple,
# never a string a shell would interpret, and never built from caller input.
_DISPATCH_COMMAND: dict[ExecutionOperation, tuple[str, ...]] = {
    op: ("python3", "-m", "dispatcher", "--operation", op.value) for op in ExecutionOperation
}

# ---------------------------------------------------------------------------
# Approved image digests (Part K). CLEARLY TEST-ONLY: no production
# execution image has been built yet (Phase 7B.2 Part 10/13 is a future
# step). These are recognizable, unmistakable placeholders -- never to be
# read as real digests.
# ---------------------------------------------------------------------------

_TEST_ONLY_DIGEST_PREFIX = "TEST-ONLY-NOT-A-REAL-IMAGE@sha256:"
_APPROVED_IMAGE_DIGESTS: dict[ResourceClass, str] = {
    # Sprint 16 Phase 7B.26 built the image; Phase 7B.27 rebuilt it
    # (dispatcher now reads AIKDAP_EXECUTION_PARAMETERS -- see
    # _expected_class_expr_environment below) and re-pinned this digest
    # -- the ONLY entry this phase is authorized to replace. CLASS_ARRAY
    # and CLASS_TABLE keep their test-only placeholders; no real image
    # exists for either yet.
    ResourceClass.CLASS_EXPR: "aikdap-exec-class-expr@sha256:cd631bedb89e1ed7d1b5f69883619d5547336f8d34bc8bc670768c4d9e3eae6e",
    ResourceClass.CLASS_ARRAY: _TEST_ONLY_DIGEST_PREFIX + "a" * 64,
    ResourceClass.CLASS_TABLE: _TEST_ONLY_DIGEST_PREFIX + "7" * 64,
}


#: Sprint 16 Phase 7B.27: the ONE parameter-transport channel this slice
#: authorizes, and ONLY for CLASS_EXPR/EVALUATE_EXPRESSION -- verified
#: against the real daemon that docker-py's attach_socket()-based stdin
#: delivery hangs indefinitely on this environment's transport (two
#: independent real-daemon probes, both required a manual `docker rm
#: -f` after `wait()` timed out), so the guard-computed, size-bounded
#: environment variable below is the channel that was actually proven
#: to work, not merely assumed safe from documentation. Bound chosen
#: with headroom over ExperimentPlanCreateFromEquation's own 500-char
#: expression cap (experiment_schemas.py) plus JSON framing.
_MAX_EXPRESSION_PARAMETER_BYTES = 2048
_EXPRESSION_PARAMETER_ENV_VAR = "AIKDAP_EXECUTION_PARAMETERS"


def _expected_class_expr_environment(request: LaunchRequest) -> dict[str, str]:
    """Independently re-derives the ONLY environment CLASS_EXPR is
    allowed to receive, from `request.parameters["expression"]` alone --
    never from `candidate.environment`, matching `_expected_mounts()`'s
    "the guard recomputes, never trusts" discipline for the same field
    shape. Carries EXACTLY `{"expression": ...}` -- no other key from
    `request.parameters` (e.g. stray VARIABLE/PARAMETER/CONSTANT
    entries the dispatcher does not understand), no request metadata,
    no secrets. Raises `SecurityBlocked` for a missing/blank/oversized
    expression -- BEFORE any Docker call, since this runs inside
    `build_candidate()`/`validate_and_approve()`, both of which
    complete entirely before `execute_approved_launch()` ever touches
    Docker."""
    expression = request.parameters.get("expression")
    if not isinstance(expression, str) or not expression.strip():
        raise SecurityBlocked(
            "expression_parameter_missing",
            "CLASS_EXPR/EVALUATE_EXPRESSION requires a non-empty 'expression' parameter",
        )
    payload = json.dumps({"expression": expression}, separators=(",", ":"), sort_keys=True)
    payload_bytes = len(payload.encode("utf-8"))
    if payload_bytes > _MAX_EXPRESSION_PARAMETER_BYTES:
        raise SecurityBlocked(
            "expression_parameter_too_large",
            f"{payload_bytes} bytes exceeds the {_MAX_EXPRESSION_PARAMETER_BYTES}-byte bound",
        )
    return {_EXPRESSION_PARAMETER_ENV_VAR: payload}


def _expected_environment(
    resource_class: ResourceClass, config: ResourceClassConfig, request: LaunchRequest
) -> dict[str, str]:
    """OpenBLAS/OMP thread pinning (Phase 7A.5's crash finding) applies
    only to the NumPy/pandas-backed classes -- CLASS_EXPR's pure-SymPy
    path never imports NumPy, so it never gets those. Sprint 16 Phase
    7B.27: CLASS_EXPR instead gets its own single-purpose, guard-
    computed parameter channel (see `_expected_class_expr_environment`)
    -- CLASS_ARRAY/CLASS_TABLE are unaffected by this phase, exactly as
    scoped ("DO NOT generalize parameter transport to all resource
    classes")."""
    if resource_class == ResourceClass.CLASS_EXPR:
        return _expected_class_expr_environment(request)
    threads = str(max(1, round(config.cpus)))
    return {"OPENBLAS_NUM_THREADS": threads, "OMP_NUM_THREADS": threads}


async def _expected_mounts(request: LaunchRequest, resolver: InputResolver) -> tuple[MountSpec, ...]:
    """Independently resolves every input asset itself -- never reads
    `candidate.mounts` or any pre-resolved value to decide what SHOULD be
    mounted (Phase 7B.2 Part 6/13).

    Async (Phase 7B.6): `resolver.resolve()` is awaited, closing the
    sync/async gap Phase 7B.5 found -- `ProductionInputResolver` can now
    drive this function directly, no test-only adapter needed.
    """
    mounts: list[MountSpec] = []
    for asset_id in request.input_asset_ids:
        try:
            resolved = await resolver.resolve(
                owner_id=request.owner_id, project_id=request.project_id, asset_id=asset_id
            )
        except InputResolutionError as exc:
            raise SecurityBlocked("input_resolution_failed", str(exc)) from exc
        mounts.append(
            MountSpec(source=resolved.host_path, destination=f"/input/{resolved.mount_name}", mode="ro")
        )
    return tuple(mounts)


def _assert_no_dangerous_mount_paths(mounts: tuple[MountSpec, ...]) -> None:
    """Belt-and-suspenders on top of the mount-equality check below:
    explicit, named rejection of the two mount shapes Phase 7B.2 Part G
    calls out individually (#18 Docker socket, #19 host filesystem) even
    though the equality check would already catch both as a mismatch
    against the freshly-resolved expected set."""
    for mount in mounts:
        lowered_source = mount.source.lower()
        for marker in _DOCKER_SOCKET_MARKERS:
            if marker in lowered_source:
                raise SecurityBlocked("docker_socket_mount", f"mount source references {marker!r}")
        if mount.mode != "ro":
            raise SecurityBlocked("mount_not_readonly", f"{mount.destination} mode={mount.mode!r}")
        if not mount.destination.startswith("/input/"):
            raise SecurityBlocked("mount_destination", f"{mount.destination} is not under /input/")


def resource_class_timeout_s(resource_class: ResourceClass) -> float:
    """Re-derives one resource class's bounded-execution timeout (Sprint 16
    Phase 7B.29) -- the SAME authoritative source `ApprovedLaunchSpec.
    timeout_s` is built from inside `validate_and_approve()` below, exposed
    as its own pure lookup for Docker-aware reconciliation.

    Why this is needed: `ApprovedLaunchSpec` is never persisted (by design
    -- Docker POLICY lives only in the ephemeral object the guard produces
    fresh for every launch, never in a database row). A reconciler picking
    up an orphaned container days later has no `ApprovedLaunchSpec` to
    read `timeout_s` from -- but it DOES have the durable `ExecutionJob.
    resource_class`, from which this is a pure, deterministic
    re-derivation (the exact value the original launch was approved
    with), not a guess or a re-benchmark.

    Raises `SecurityBlocked` for an unrecognized resource class, matching
    every other "the catalog does not know this value" failure in this
    module -- fail closed, never silently default to some other class's
    timeout.
    """
    config = _RESOURCE_CLASS_CONFIG.get(resource_class)
    if config is None:
        raise SecurityBlocked("unknown_resource_class", str(resource_class))
    return config.timeout_s


async def validate_and_approve(
    candidate: CandidateLaunchSpec, resolver: InputResolver
) -> ApprovedLaunchSpec:
    """The guard. Raises `SecurityBlocked` on the FIRST failed check --
    no partial evaluation, no accumulate-and-report, no fallback that
    widens a permission or relaxes a limit (Phase 7B.2 Part D/I).

    Async (Phase 7B.6): awaits `_expected_mounts()`, which awaits
    `resolver.resolve()` -- the only change from Phase 7B.2/7B.3's
    logic is the calling convention; every check, order, and fail-closed
    behavior is unchanged.
    """

    request = candidate.request

    # --- 0. capability/operation/resource_class consistency -------------
    # Re-derived from `operation` alone, the single fact this catalog is
    # actually keyed on -- `request.capability` and `request.resource_class`
    # are independently-supplied fields on the message and are trusted
    # for nothing until they are shown to agree with this derivation.
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

    class_config = _RESOURCE_CLASS_CONFIG.get(expected_resource_class)
    if class_config is None:
        raise SecurityBlocked("unknown_resource_class", str(expected_resource_class))

    # --- 1. approved image digest ----------------------------------------
    expected_image = _APPROVED_IMAGE_DIGESTS.get(expected_resource_class)
    if expected_image is None:
        raise SecurityBlocked("image_digest_missing", str(expected_resource_class))
    if "@sha256:" not in expected_image:
        # Guards the guard's own config -- a tag-shaped entry in
        # _APPROVED_IMAGE_DIGESTS is a configuration bug, not a runtime
        # attack, but must still fail closed (Phase 7B.2 Part 12/18).
        raise SecurityBlocked("approved_digest_not_digest_shaped", expected_image)
    if candidate.image != expected_image:
        raise SecurityBlocked("image_mismatch", f"{candidate.image!r} != approved digest")

    # --- 2-7. fixed container posture ------------------------------------
    if candidate.network_mode != _FIXED_NETWORK_MODE:
        raise SecurityBlocked("network_mode", f"{candidate.network_mode!r} != {_FIXED_NETWORK_MODE!r}")
    if candidate.privileged is not _FIXED_PRIVILEGED:
        raise SecurityBlocked("privileged", f"{candidate.privileged!r} != {_FIXED_PRIVILEGED!r}")
    if tuple(candidate.cap_drop) != _FIXED_CAP_DROP:
        raise SecurityBlocked("cap_drop", f"{candidate.cap_drop!r} != {_FIXED_CAP_DROP!r}")
    if tuple(candidate.cap_add) != _FIXED_CAP_ADD:
        raise SecurityBlocked("cap_add", f"{candidate.cap_add!r} != {_FIXED_CAP_ADD!r}")
    if tuple(candidate.security_opt) != _FIXED_SECURITY_OPT:
        raise SecurityBlocked(
            "security_opt", f"{candidate.security_opt!r} != {_FIXED_SECURITY_OPT!r}"
        )
    if candidate.read_only is not _FIXED_READ_ONLY:
        raise SecurityBlocked("read_only", f"{candidate.read_only!r} != {_FIXED_READ_ONLY!r}")
    if candidate.user != _FIXED_USER:
        raise SecurityBlocked("user", f"{candidate.user!r} != {_FIXED_USER!r}")

    # --- 8-12. resource limits, resource-class-derived --------------------
    if candidate.mem_limit_mb != class_config.memory_mb:
        raise SecurityBlocked(
            "mem_limit", f"{candidate.mem_limit_mb!r} != {class_config.memory_mb!r}"
        )
    if candidate.memswap_limit_mb != class_config.memory_mb:
        raise SecurityBlocked(
            "memswap_limit", f"{candidate.memswap_limit_mb!r} != {class_config.memory_mb!r}"
        )
    if candidate.cpus != class_config.cpus:
        raise SecurityBlocked("cpus", f"{candidate.cpus!r} != {class_config.cpus!r}")
    if candidate.pids_limit != class_config.pids_limit:
        raise SecurityBlocked(
            "pids_limit", f"{candidate.pids_limit!r} != {class_config.pids_limit!r}"
        )
    if candidate.tmpfs_mb != class_config.tmpfs_mb:
        raise SecurityBlocked("tmpfs", f"{candidate.tmpfs_mb!r} != {class_config.tmpfs_mb!r}")

    # --- Sprint 16 Phase 7B.28: bounded execution lifetime -----------------
    if candidate.timeout_s != class_config.timeout_s:
        raise SecurityBlocked("timeout", f"{candidate.timeout_s!r} != {class_config.timeout_s!r}")

    # --- 13, 18, 19. mounts: independently resolved, not trusted ---------
    # Candidate mounts are scanned FIRST, for specific, named rejection
    # reasons (Docker socket, non-read-only, wrong destination prefix) --
    # Phase 7B.2 Part G lists these as their own numbered checks (#18,
    # #19) even though the equality check below would also catch them
    # generically. Checking the candidate's own proposal first gives a
    # precise `check_name` instead of a generic "mounts" mismatch.
    _assert_no_dangerous_mount_paths(tuple(candidate.mounts))
    expected_mounts = await _expected_mounts(request, resolver)
    _assert_no_dangerous_mount_paths(expected_mounts)  # defensive: our own derivation must be safe too
    if tuple(candidate.mounts) != expected_mounts:
        raise SecurityBlocked(
            "mounts", f"{candidate.mounts!r} != independently-resolved {expected_mounts!r}"
        )

    # --- 14, 15. environment: closed allowlist ----------------------------
    expected_environment = _expected_environment(expected_resource_class, class_config, request)
    if candidate.environment != expected_environment:
        raise SecurityBlocked(
            "environment", f"{candidate.environment!r} != {expected_environment!r}"
        )

    # --- 16, 17. fixed dispatcher command, no entrypoint override ---------
    expected_command = _DISPATCH_COMMAND[request.operation]
    if tuple(candidate.command or ()) != expected_command:
        raise SecurityBlocked("command", f"{candidate.command!r} != {expected_command!r}")
    if candidate.entrypoint != _FIXED_ENTRYPOINT:
        raise SecurityBlocked("entrypoint", f"{candidate.entrypoint!r} != {_FIXED_ENTRYPOINT!r}")

    # --- 20-23. no additional privilege surface ---------------------------
    if tuple(candidate.devices) != _FIXED_DEVICES:
        raise SecurityBlocked("devices", f"{candidate.devices!r} != {_FIXED_DEVICES!r}")
    if candidate.pid_mode != _FIXED_PID_MODE:
        raise SecurityBlocked("pid_mode", f"{candidate.pid_mode!r} != {_FIXED_PID_MODE!r}")
    if candidate.ipc_mode != _FIXED_IPC_MODE:
        raise SecurityBlocked("ipc_mode", f"{candidate.ipc_mode!r} != {_FIXED_IPC_MODE!r}")

    # --- 24. no caller-configurable Docker flags ---------------------------
    # Structural, not a runtime check: every value used to build the
    # object below came from a fixed constant or a class_config/expected_*
    # lookup, never from `candidate` directly (except where already
    # verified equal above) and never from `request.parameters`.

    return ApprovedLaunchSpec(
        job_id=request.job_id,
        image=expected_image,
        network_mode=_FIXED_NETWORK_MODE,
        privileged=_FIXED_PRIVILEGED,
        cap_drop=_FIXED_CAP_DROP,
        security_opt=_FIXED_SECURITY_OPT,
        read_only=_FIXED_READ_ONLY,
        user=_FIXED_USER,
        mem_limit_mb=class_config.memory_mb,
        memswap_limit_mb=class_config.memory_mb,
        cpus=class_config.cpus,
        pids_limit=class_config.pids_limit,
        tmpfs_mb=class_config.tmpfs_mb,
        mounts=expected_mounts,
        environment=expected_environment,
        command=expected_command,
        timeout_s=class_config.timeout_s,
    )

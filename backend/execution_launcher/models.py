"""Typed models for the Sprint 16 Phase 7B execution guard boundary.

Every model here is a pure data container -- no Docker SDK usage, no
filesystem access, no network calls. `LaunchRequest` is the ONLY shape a
Celery message is trusted to supply (Phase 7B.1 Part 10 / 7B.2 Part 2): it
has no field that could ever represent a Docker image, flag, path, or
command, and `extra="forbid"` makes smuggling an unrecognized field a
validation error rather than a silently-ignored one.

`CandidateLaunchSpec` and `ApprovedLaunchSpec` are deliberately DISTINCT
types (Phase 7B.2 Part 2/Part H) -- a candidate is the translator's
possibly-buggy proposal; an approved spec can only be produced by
`docker_policy.validate_and_approve()`. Nothing in this module constructs
an `ApprovedLaunchSpec` directly.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from enum import Enum
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Closed vocabularies (Part B: "use enums ... not arbitrary strings")
# ---------------------------------------------------------------------------


class ExecutionCapability(str, Enum):
    """The broad domain a job belongs to. Every value maps to exactly one
    `ResourceClass` via the fixed catalog in `docker_policy.py` -- never
    read from the request as an independent, trusted fact."""

    EVALUATE_EXPRESSION = "evaluate_expression"
    ARRAY_COMPUTE = "array_compute"
    TABLE_COMPUTE = "table_compute"


class ExecutionOperation(str, Enum):
    """The exact 8-operation Phase 7B catalog. Nothing else is a legal
    value -- adding a 9th operation here is out of scope for this slice."""

    EVALUATE_EXPRESSION = "evaluate_expression"
    MATMUL = "matmul"
    PERCENTILE = "percentile"
    MEAN = "mean"
    STD = "std"
    CORRCOEF = "corrcoef"
    GROUPBY_AGG = "groupby_agg"
    PIVOT_TABLE = "pivot_table"


class ResourceClass(str, Enum):
    CLASS_EXPR = "class_expr"
    CLASS_ARRAY = "class_array"
    CLASS_TABLE = "class_table"


# ---------------------------------------------------------------------------
# LaunchRequest -- the only shape trusted from the Celery message
# ---------------------------------------------------------------------------

LaunchParameterValue = str | int | float | bool


class LaunchRequest(BaseModel):
    """What a (future) Celery execution message is allowed to carry.

    Deliberately has NO field for: image, image_tag, image_digest, command,
    entrypoint, any Docker flag, a host path, network mode, an environment
    dict, capabilities, or devices (Phase 7B.1 Part 10 / this phase's Part
    B). `extra="forbid"` turns an attempt to smuggle any such field into a
    hard validation failure at the model boundary, before any application
    code runs.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    job_id: uuid.UUID
    experiment_plan_id: uuid.UUID
    experiment_plan_version: int = Field(ge=1)
    owner_id: uuid.UUID
    project_id: uuid.UUID
    capability: ExecutionCapability
    operation: ExecutionOperation
    parameters: dict[str, LaunchParameterValue] = Field(default_factory=dict)
    resource_class: ResourceClass
    input_asset_ids: list[uuid.UUID] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Input resolution
# ---------------------------------------------------------------------------


class InputResolutionError(Exception):
    """Raised by an `InputResolver` when an asset cannot be safely mounted
    -- unauthorized, missing, a symlink, or not a regular file. The guard
    treats every subtype identically: fail closed (Phase 7B.2 Part 6/13)."""


@dataclass(frozen=True)
class ResolvedInput:
    """A single input asset, already proven safe to mount read-only.

    Only ever constructed by an `InputResolver` implementation that has
    independently verified ownership, existence, symlink-safety, and
    regular-file-ness -- never accepted as a caller-supplied host path
    (Phase 7B.2 Part L)."""

    asset_id: uuid.UUID
    host_path: str
    mount_name: str


class InputResolver(Protocol):
    """Abstraction the guard calls itself, fresh, for every asset id in a
    `LaunchRequest` -- never a pre-resolved value trusted from elsewhere
    (Phase 7B.2 Part 6).

    Async (Phase 7B.6): `ProductionInputResolver` (Phase 7B.4) necessarily
    does real database I/O, so this protocol -- and every caller of it in
    `docker_policy.py`/`translator.py` -- is async all the way through.
    `StaticInputResolver` implements this with no actual awaiting inside;
    being a coroutine function costs it nothing and lets it satisfy the
    same protocol a real, DB-backed resolver must.
    """

    async def resolve(
        self, *, owner_id: uuid.UUID, project_id: uuid.UUID, asset_id: uuid.UUID
    ) -> ResolvedInput: ...


# ---------------------------------------------------------------------------
# Candidate / Approved launch specs
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MountSpec:
    source: str
    destination: str
    mode: str


@dataclass(frozen=True)
class CandidateLaunchSpec:
    """The translator's (possibly buggy) proposal for how to launch a job.

    Carries the original `LaunchRequest` so the guard can independently
    re-derive every expected value from it -- the guard never trusts any
    Docker-shaped field below merely because it is present here (Phase
    7B.2 Part F)."""

    request: LaunchRequest
    image: str
    network_mode: str | None
    privileged: bool | None
    cap_drop: tuple[str, ...]
    cap_add: tuple[str, ...]
    security_opt: tuple[str, ...]
    read_only: bool | None
    user: str | None
    mem_limit_mb: int | None
    memswap_limit_mb: int | None
    cpus: float | None
    pids_limit: int | None
    tmpfs_mb: int | None
    mounts: tuple[MountSpec, ...]
    environment: dict[str, str]
    command: tuple[str, ...] | None
    entrypoint: tuple[str, ...] | None
    devices: tuple[str, ...]
    pid_mode: str | None
    ipc_mode: str | None
    #: Sprint 16 Phase 7B.28 -- bounded execution lifetime, resource-class-
    #: derived exactly like mem_limit_mb/cpus/pids_limit/tmpfs_mb above
    #: (docker_policy.py's own `_RESOURCE_CLASS_CONFIG` already carried
    #: this value; it was simply never plumbed past that module before).
    timeout_s: float | None


@dataclass(frozen=True)
class ApprovedLaunchSpec:
    """Proof that every Phase 7B.2 Part C/G check passed. Every field here
    is fixed or resource-class-derived -- there is no field that could
    ever hold a caller-controlled Docker flag, because the fields that
    only ever have one legal value (cap_add, devices, pid_mode, ipc_mode,
    entrypoint) are not carried at all: their single legal value is
    implied by this type's existence, not stored redundantly.

    Constructed ONLY by `docker_policy.validate_and_approve()`. No other
    code in this repository is permitted to construct one (Part O)."""

    job_id: uuid.UUID
    image: str
    network_mode: str
    privileged: bool
    cap_drop: tuple[str, ...]
    security_opt: tuple[str, ...]
    read_only: bool
    user: str
    mem_limit_mb: int
    memswap_limit_mb: int
    cpus: float
    pids_limit: int
    tmpfs_mb: int
    mounts: tuple[MountSpec, ...]
    environment: dict[str, str]
    command: tuple[str, ...]
    #: Sprint 16 Phase 7B.28 -- the bounded deadline `launcher.py`'s
    #: `execute_approved_launch` enforces for this launch. Resource-class-
    #: derived, guard-verified, never caller-controlled -- same discipline
    #: as every other field on this dataclass.
    timeout_s: float


class SecurityBlocked(Exception):
    """Raised by the guard for any failed check. Never caught-and-defaulted
    anywhere in this package -- a raised `SecurityBlocked` always means no
    launch happens (Phase 7B.2 Part 4/I)."""

    def __init__(self, check_name: str, reason: str) -> None:
        self.check_name = check_name
        self.reason = reason
        super().__init__(f"{check_name}: {reason}")

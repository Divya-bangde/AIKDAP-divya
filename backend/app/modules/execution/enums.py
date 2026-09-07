"""Enumerations for the execution module.

`ExecutionCapability`, `ExecutionOperation`, and `ResourceClass` are
deliberately NOT redefined here -- they already exist as the closed
vocabularies the guard layer trusts (`execution_launcher.models`), and
duplicating them would risk the two enums drifting apart. This module
only adds `ExecutionJobStatus`, which has no equivalent in
`execution_launcher` because that package has no concept of a
persisted job.
"""

import enum


class ExecutionJobStatus(str, enum.Enum):
    """Lifecycle state of a persisted execution job.

    The authoritative status vocabulary (Phase 7B.11), superseding the
    smaller, speculative set Phase 7B.8 originally guessed at
    (`LAUNCHED`/`SECURITY_BLOCKED`/`COMPLETED`, never actually written by
    any code path). Only `PENDING -> VALIDATING` is implemented as of this
    slice -- every other transition (`VALIDATING -> LAUNCHING -> RUNNING ->
    SUCCEEDED`, the `FAILED`/`TIMED_OUT`/`CANCEL_REQUESTED`/`CANCELLED`
    branches) belongs to a future Docker-launcher slice. A guard/resolver
    rejection is represented as `FAILED` with `reason` carrying the
    detail, not a dedicated status -- consistent with how
    `docker_policy.SecurityBlocked` already reports rejections via a
    `check_name`/`reason` pair, not a distinct exception type per check.
    """

    PENDING = "PENDING"
    VALIDATING = "VALIDATING"
    LAUNCHING = "LAUNCHING"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    TIMED_OUT = "TIMED_OUT"
    CANCEL_REQUESTED = "CANCEL_REQUESTED"
    CANCELLED = "CANCELLED"


class ExecutionAttemptStatus(str, enum.Enum):
    """Lifecycle state of one `ExecutionAttempt` -- deliberately a
    SEPARATE, smaller vocabulary from `ExecutionJobStatus` (Phase 7B.12
    design, Part 3: "a job's status and one attempt's relationship to a
    Docker container are different lifecycles"). A job's status describes
    the job as a whole across possibly many attempts; an attempt's status
    describes only that one attempt's relationship to (at most) one
    Docker container.

    Closed at exactly the states this slice's persistence layer and the
    approved Phase 7B.12 design need. Deliberately does NOT include
    speculative future states (`RETRYING`, `DESTROYING`, `ORPHANED`) --
    nothing in the current design or repository evidence requires them
    yet; they can be added deliberately, with their own migration, once
    an actual future slice needs them.
    """

    #: Written once, by this slice, at row creation. No Docker call has
    #: been attempted yet.
    PENDING_CREATE = "PENDING_CREATE"
    #: A future launcher slice writes this after `docker.containers.create()`
    #: is CONFIRMED to have returned -- never before.
    CREATED = "CREATED"
    RUNNING = "RUNNING"
    #: The container has exited, successfully or not; `exit_code` carries
    #: which. A future slice may still choose to add more granular
    #: success/failure states later -- not needed by this persistence-only
    #: slice.
    EXITED = "EXITED"
    #: A future reconciler's fallback when it cannot determine the real
    #: state from Docker (e.g. the daemon itself is unreachable) -- kept
    #: here now because the Phase 7B.12 design's recovery protocol
    #: depends on there being a safe "we don't know" state to land in,
    #: not because this slice writes it.
    UNKNOWN = "UNKNOWN"

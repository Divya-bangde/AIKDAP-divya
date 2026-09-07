"""Sprint 16 Phase 7B.3 -- permanent security tests for the guard layer.

These are pure unit tests: no Docker, no database, no filesystem, no
network. Every test in this file either proves the guard approves a
correctly-built candidate, or proves it blocks a specific translator
mistake / attack shape with the correct `SecurityBlocked.check_name`
(Phase 7B.2 Part 15 / this phase's Part N).

Async (Phase 7B.6): `build_candidate()`/`validate_and_approve()` became
`async def` to let `ProductionInputResolver` (Phase 7B.4, necessarily
async) drive them directly, closing the gap Phase 7B.5 found. Every test
here still uses `StaticInputResolver` (no real I/O) -- only the calling
convention changed, never the security logic or expected outcomes.
"""

from __future__ import annotations

import uuid
from dataclasses import replace

import pytest
import pytest_asyncio
from pydantic import ValidationError

from execution_launcher import docker_policy
from execution_launcher.docker_policy import validate_and_approve
from execution_launcher.models import (
    ApprovedLaunchSpec,
    CandidateLaunchSpec,
    ExecutionCapability,
    ExecutionOperation,
    LaunchRequest,
    MountSpec,
    ResourceClass,
    SecurityBlocked,
)
from execution_launcher.resolvers import StaticInputResolver
from execution_launcher.translator import build_candidate

OWNER_ID = uuid.uuid4()
PROJECT_ID = uuid.uuid4()
OTHER_PROJECT_ID = uuid.uuid4()
OTHER_OWNER_ID = uuid.uuid4()
ASSET_ID = uuid.uuid4()


# ---------------------------------------------------------------------------
# Request / resolver builders
# ---------------------------------------------------------------------------


def _matmul_request(**overrides) -> LaunchRequest:
    fields = dict(
        job_id=uuid.uuid4(),
        experiment_plan_id=uuid.uuid4(),
        experiment_plan_version=1,
        owner_id=OWNER_ID,
        project_id=PROJECT_ID,
        capability=ExecutionCapability.ARRAY_COMPUTE,
        operation=ExecutionOperation.MATMUL,
        parameters={},
        resource_class=ResourceClass.CLASS_ARRAY,
        input_asset_ids=[ASSET_ID],
    )
    fields.update(overrides)
    return LaunchRequest(**fields)


def _expr_request(**overrides) -> LaunchRequest:
    fields = dict(
        job_id=uuid.uuid4(),
        experiment_plan_id=uuid.uuid4(),
        experiment_plan_version=1,
        owner_id=OWNER_ID,
        project_id=PROJECT_ID,
        capability=ExecutionCapability.EVALUATE_EXPRESSION,
        operation=ExecutionOperation.EVALUATE_EXPRESSION,
        parameters={"expression": "1+1"},
        resource_class=ResourceClass.CLASS_EXPR,
        input_asset_ids=[],
    )
    fields.update(overrides)
    return LaunchRequest(**fields)


def _matmul_resolver(**asset_overrides) -> StaticInputResolver:
    resolver = StaticInputResolver()
    kwargs = dict(
        owner_id=OWNER_ID,
        project_id=PROJECT_ID,
        host_path="/data/storage/proj/matrix.csv",
        mount_name="matrix.csv",
    )
    kwargs.update(asset_overrides)
    resolver.register(ASSET_ID, **kwargs)
    return resolver


@pytest_asyncio.fixture
async def valid_matmul_candidate() -> tuple[CandidateLaunchSpec, StaticInputResolver]:
    resolver = _matmul_resolver()
    candidate = await build_candidate(_matmul_request(), resolver)
    return candidate, resolver


@pytest_asyncio.fixture
async def valid_expr_candidate() -> tuple[CandidateLaunchSpec, StaticInputResolver]:
    resolver = StaticInputResolver()
    candidate = await build_candidate(_expr_request(), resolver)
    return candidate, resolver


# ---------------------------------------------------------------------------
# Valid candidates approve
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_valid_matmul_candidate_is_approved(valid_matmul_candidate):
    candidate, resolver = valid_matmul_candidate
    assert isinstance(candidate, CandidateLaunchSpec)

    approved = await validate_and_approve(candidate, resolver)

    assert isinstance(approved, ApprovedLaunchSpec)
    assert approved.job_id == candidate.request.job_id
    assert approved.network_mode == "none"
    assert approved.privileged is False
    assert approved.cap_drop == ("ALL",)
    assert approved.read_only is True
    assert approved.mem_limit_mb == 512
    assert approved.cpus == 1.0
    assert approved.pids_limit == 32
    assert approved.mounts == (
        MountSpec(source="/data/storage/proj/matrix.csv", destination="/input/matrix.csv", mode="ro"),
    )
    assert approved.environment == {"OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1"}
    assert approved.command == ("python3", "-m", "dispatcher", "--operation", "matmul")


@pytest.mark.asyncio
async def test_valid_expr_candidate_is_approved(valid_expr_candidate):
    candidate, resolver = valid_expr_candidate

    approved = await validate_and_approve(candidate, resolver)

    assert isinstance(approved, ApprovedLaunchSpec)
    assert approved.mem_limit_mb == 256
    assert approved.pids_limit == 32
    assert approved.mounts == ()
    # Sprint 16 Phase 7B.27: CLASS_EXPR now carries its expression via a
    # guard-computed, size-bounded environment variable (the one
    # parameter-transport channel this phase authorizes) -- no longer
    # always {} the way it was in 7B.25/7B.26.
    assert approved.environment == {"AIKDAP_EXECUTION_PARAMETERS": '{"expression":"1+1"}'}
    assert approved.command == ("python3", "-m", "dispatcher", "--operation", "evaluate_expression")


# ---------------------------------------------------------------------------
# Network
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_missing_network(valid_matmul_candidate):
    candidate, resolver = valid_matmul_candidate
    bad = replace(candidate, network_mode=None)
    with pytest.raises(SecurityBlocked) as exc:
        await validate_and_approve(bad, resolver)
    assert exc.value.check_name == "network_mode"


@pytest.mark.asyncio
async def test_bridge_network(valid_matmul_candidate):
    candidate, resolver = valid_matmul_candidate
    bad = replace(candidate, network_mode="bridge")
    with pytest.raises(SecurityBlocked) as exc:
        await validate_and_approve(bad, resolver)
    assert exc.value.check_name == "network_mode"


@pytest.mark.asyncio
async def test_host_network(valid_matmul_candidate):
    candidate, resolver = valid_matmul_candidate
    bad = replace(candidate, network_mode="host")
    with pytest.raises(SecurityBlocked) as exc:
        await validate_and_approve(bad, resolver)
    assert exc.value.check_name == "network_mode"


# ---------------------------------------------------------------------------
# Privilege / capabilities
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_privileged(valid_matmul_candidate):
    candidate, resolver = valid_matmul_candidate
    bad = replace(candidate, privileged=True)
    with pytest.raises(SecurityBlocked) as exc:
        await validate_and_approve(bad, resolver)
    assert exc.value.check_name == "privileged"


@pytest.mark.asyncio
async def test_missing_cap_drop(valid_matmul_candidate):
    candidate, resolver = valid_matmul_candidate
    bad = replace(candidate, cap_drop=())
    with pytest.raises(SecurityBlocked) as exc:
        await validate_and_approve(bad, resolver)
    assert exc.value.check_name == "cap_drop"


@pytest.mark.asyncio
async def test_extra_capability(valid_matmul_candidate):
    candidate, resolver = valid_matmul_candidate
    bad = replace(candidate, cap_add=("SYS_ADMIN",))
    with pytest.raises(SecurityBlocked) as exc:
        await validate_and_approve(bad, resolver)
    assert exc.value.check_name == "cap_add"


@pytest.mark.asyncio
async def test_missing_no_new_privileges(valid_matmul_candidate):
    candidate, resolver = valid_matmul_candidate
    bad = replace(candidate, security_opt=())
    with pytest.raises(SecurityBlocked) as exc:
        await validate_and_approve(bad, resolver)
    assert exc.value.check_name == "security_opt"


# ---------------------------------------------------------------------------
# Filesystem / user posture
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_writable_root(valid_matmul_candidate):
    candidate, resolver = valid_matmul_candidate
    bad = replace(candidate, read_only=False)
    with pytest.raises(SecurityBlocked) as exc:
        await validate_and_approve(bad, resolver)
    assert exc.value.check_name == "read_only"


@pytest.mark.asyncio
async def test_wrong_uid(valid_matmul_candidate):
    candidate, resolver = valid_matmul_candidate
    bad = replace(candidate, user="1000:1000")
    with pytest.raises(SecurityBlocked) as exc:
        await validate_and_approve(bad, resolver)
    assert exc.value.check_name == "user"


@pytest.mark.asyncio
async def test_root_uid(valid_matmul_candidate):
    candidate, resolver = valid_matmul_candidate
    bad = replace(candidate, user="0:0")
    with pytest.raises(SecurityBlocked) as exc:
        await validate_and_approve(bad, resolver)
    assert exc.value.check_name == "user"


# ---------------------------------------------------------------------------
# Resource limits
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_wrong_memory(valid_matmul_candidate):
    candidate, resolver = valid_matmul_candidate
    bad = replace(candidate, mem_limit_mb=99999)
    with pytest.raises(SecurityBlocked) as exc:
        await validate_and_approve(bad, resolver)
    assert exc.value.check_name == "mem_limit"


@pytest.mark.asyncio
async def test_wrong_memswap(valid_matmul_candidate):
    candidate, resolver = valid_matmul_candidate
    bad = replace(candidate, memswap_limit_mb=99999)
    with pytest.raises(SecurityBlocked) as exc:
        await validate_and_approve(bad, resolver)
    assert exc.value.check_name == "memswap_limit"


@pytest.mark.asyncio
async def test_wrong_cpu(valid_matmul_candidate):
    candidate, resolver = valid_matmul_candidate
    bad = replace(candidate, cpus=8.0)
    with pytest.raises(SecurityBlocked) as exc:
        await validate_and_approve(bad, resolver)
    assert exc.value.check_name == "cpus"


@pytest.mark.asyncio
async def test_wrong_pids(valid_matmul_candidate):
    candidate, resolver = valid_matmul_candidate
    bad = replace(candidate, pids_limit=99999)
    with pytest.raises(SecurityBlocked) as exc:
        await validate_and_approve(bad, resolver)
    assert exc.value.check_name == "pids_limit"


@pytest.mark.asyncio
async def test_wrong_tmpfs(valid_matmul_candidate):
    candidate, resolver = valid_matmul_candidate
    bad = replace(candidate, tmpfs_mb=99999)
    with pytest.raises(SecurityBlocked) as exc:
        await validate_and_approve(bad, resolver)
    assert exc.value.check_name == "tmpfs"


# ---------------------------------------------------------------------------
# Mounts
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_writable_mount(valid_matmul_candidate):
    candidate, resolver = valid_matmul_candidate
    original = candidate.mounts[0]
    bad = replace(
        candidate,
        mounts=(MountSpec(source=original.source, destination=original.destination, mode="rw"),),
    )
    with pytest.raises(SecurityBlocked) as exc:
        await validate_and_approve(bad, resolver)
    assert exc.value.check_name == "mount_not_readonly"


@pytest.mark.asyncio
async def test_host_mount(valid_matmul_candidate):
    candidate, resolver = valid_matmul_candidate
    bad = replace(
        candidate,
        mounts=(MountSpec(source="/etc/passwd", destination="/input/passwd", mode="ro"),),
    )
    with pytest.raises(SecurityBlocked) as exc:
        await validate_and_approve(bad, resolver)
    assert exc.value.check_name == "mounts"


@pytest.mark.asyncio
async def test_dotenv_mount(valid_matmul_candidate):
    candidate, resolver = valid_matmul_candidate
    bad = replace(
        candidate,
        mounts=(MountSpec(source="/app/.env", destination="/input/.env", mode="ro"),),
    )
    with pytest.raises(SecurityBlocked) as exc:
        await validate_and_approve(bad, resolver)
    assert exc.value.check_name == "mounts"


@pytest.mark.asyncio
async def test_docker_socket_mount(valid_matmul_candidate):
    candidate, resolver = valid_matmul_candidate
    bad = replace(
        candidate,
        mounts=(
            MountSpec(source="/var/run/docker.sock", destination="/input/sock", mode="ro"),
        ),
    )
    with pytest.raises(SecurityBlocked) as exc:
        await validate_and_approve(bad, resolver)
    assert exc.value.check_name == "docker_socket_mount"


@pytest.mark.asyncio
async def test_mount_destination_outside_input(valid_matmul_candidate):
    candidate, resolver = valid_matmul_candidate
    original = candidate.mounts[0]
    bad = replace(
        candidate,
        mounts=(MountSpec(source=original.source, destination="/etc/evil", mode="ro"),),
    )
    with pytest.raises(SecurityBlocked) as exc:
        await validate_and_approve(bad, resolver)
    assert exc.value.check_name == "mount_destination"


@pytest.mark.asyncio
async def test_symlink_input_rejected():
    resolver = _matmul_resolver(is_symlink=True)
    with pytest.raises(SecurityBlocked) as exc:
        await build_candidate(_matmul_request(), resolver)
    assert exc.value.check_name == "input_resolution_failed"


@pytest.mark.asyncio
async def test_non_regular_file_input_rejected():
    resolver = _matmul_resolver(is_regular_file=False)
    with pytest.raises(SecurityBlocked) as exc:
        await build_candidate(_matmul_request(), resolver)
    assert exc.value.check_name == "input_resolution_failed"


@pytest.mark.asyncio
async def test_wrong_project_input_rejected():
    resolver = _matmul_resolver(project_id=OTHER_PROJECT_ID)
    with pytest.raises(SecurityBlocked) as exc:
        await build_candidate(_matmul_request(), resolver)
    assert exc.value.check_name == "input_resolution_failed"


@pytest.mark.asyncio
async def test_wrong_owner_input_rejected():
    resolver = _matmul_resolver(owner_id=OTHER_OWNER_ID)
    with pytest.raises(SecurityBlocked) as exc:
        await build_candidate(_matmul_request(), resolver)
    assert exc.value.check_name == "input_resolution_failed"


@pytest.mark.asyncio
async def test_missing_input_rejected():
    resolver = _matmul_resolver(exists=False)
    with pytest.raises(SecurityBlocked) as exc:
        await build_candidate(_matmul_request(), resolver)
    assert exc.value.check_name == "input_resolution_failed"


@pytest.mark.asyncio
async def test_unregistered_input_rejected():
    resolver = StaticInputResolver()  # ASSET_ID never registered
    with pytest.raises(SecurityBlocked) as exc:
        await build_candidate(_matmul_request(), resolver)
    assert exc.value.check_name == "input_resolution_failed"


@pytest.mark.asyncio
async def test_guard_reresolves_inputs_independently_of_candidate(valid_matmul_candidate):
    """The guard must not trust `candidate.mounts` as proof inputs were
    authorized -- it re-resolves from `candidate.request` itself. A
    resolver that would now reject the same asset (e.g. ownership
    revoked between candidate construction and approval) must still
    block approval, even though the candidate's mounts look fine."""
    candidate, _ = valid_matmul_candidate
    revoked_resolver = _matmul_resolver(project_id=OTHER_PROJECT_ID)
    with pytest.raises(SecurityBlocked) as exc:
        await validate_and_approve(candidate, revoked_resolver)
    assert exc.value.check_name == "input_resolution_failed"


# ---------------------------------------------------------------------------
# Environment / secrets
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_extra_environment_key(valid_matmul_candidate):
    candidate, resolver = valid_matmul_candidate
    bad = replace(candidate, environment={**candidate.environment, "EXTRA_VAR": "1"})
    with pytest.raises(SecurityBlocked) as exc:
        await validate_and_approve(bad, resolver)
    assert exc.value.check_name == "environment"


@pytest.mark.asyncio
async def test_secret_environment_key(valid_matmul_candidate):
    candidate, resolver = valid_matmul_candidate
    bad = replace(
        candidate, environment={**candidate.environment, "DATABASE_URL": "postgresql://x"}
    )
    with pytest.raises(SecurityBlocked) as exc:
        await validate_and_approve(bad, resolver)
    assert exc.value.check_name == "environment"


@pytest.mark.asyncio
async def test_missing_required_environment_key(valid_matmul_candidate):
    candidate, resolver = valid_matmul_candidate
    bad = replace(candidate, environment={})
    with pytest.raises(SecurityBlocked) as exc:
        await validate_and_approve(bad, resolver)
    assert exc.value.check_name == "environment"


# ---------------------------------------------------------------------------
# Command / entrypoint
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_wrong_command(valid_matmul_candidate):
    candidate, resolver = valid_matmul_candidate
    bad = replace(candidate, command=("/bin/sh", "-c", "echo pwned"))
    with pytest.raises(SecurityBlocked) as exc:
        await validate_and_approve(bad, resolver)
    assert exc.value.check_name == "command"


@pytest.mark.asyncio
async def test_wrong_entrypoint(valid_matmul_candidate):
    candidate, resolver = valid_matmul_candidate
    bad = replace(candidate, entrypoint=("/bin/sh",))
    with pytest.raises(SecurityBlocked) as exc:
        await validate_and_approve(bad, resolver)
    assert exc.value.check_name == "entrypoint"


# ---------------------------------------------------------------------------
# Devices / namespaces
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_extra_device(valid_matmul_candidate):
    candidate, resolver = valid_matmul_candidate
    bad = replace(candidate, devices=("/dev/kmsg",))
    with pytest.raises(SecurityBlocked) as exc:
        await validate_and_approve(bad, resolver)
    assert exc.value.check_name == "devices"


@pytest.mark.asyncio
async def test_host_pid(valid_matmul_candidate):
    candidate, resolver = valid_matmul_candidate
    bad = replace(candidate, pid_mode="host")
    with pytest.raises(SecurityBlocked) as exc:
        await validate_and_approve(bad, resolver)
    assert exc.value.check_name == "pid_mode"


@pytest.mark.asyncio
async def test_host_ipc(valid_matmul_candidate):
    candidate, resolver = valid_matmul_candidate
    bad = replace(candidate, ipc_mode="host")
    with pytest.raises(SecurityBlocked) as exc:
        await validate_and_approve(bad, resolver)
    assert exc.value.check_name == "ipc_mode"


# ---------------------------------------------------------------------------
# Image digest
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unapproved_digest(valid_matmul_candidate):
    candidate, resolver = valid_matmul_candidate
    bad = replace(candidate, image="TEST-ONLY-NOT-A-REAL-IMAGE@sha256:" + "9" * 64)
    with pytest.raises(SecurityBlocked) as exc:
        await validate_and_approve(bad, resolver)
    assert exc.value.check_name == "image_mismatch"


@pytest.mark.asyncio
async def test_mutable_tag_rejected(valid_matmul_candidate):
    candidate, resolver = valid_matmul_candidate
    bad = replace(candidate, image="aikdap-execution:latest")
    with pytest.raises(SecurityBlocked) as exc:
        await validate_and_approve(bad, resolver)
    assert exc.value.check_name == "image_mismatch"


@pytest.mark.asyncio
async def test_missing_digest_for_resource_class(valid_matmul_candidate, monkeypatch):
    candidate, resolver = valid_matmul_candidate
    monkeypatch.delitem(docker_policy._APPROVED_IMAGE_DIGESTS, ResourceClass.CLASS_ARRAY)
    with pytest.raises(SecurityBlocked) as exc:
        await validate_and_approve(candidate, resolver)
    assert exc.value.check_name == "image_digest_missing"


@pytest.mark.asyncio
async def test_tag_shaped_approved_digest_rejected(valid_matmul_candidate, monkeypatch):
    """Defends the guard's OWN configuration: if `_APPROVED_IMAGE_DIGESTS`
    were ever misconfigured with a mutable tag instead of a digest, the
    guard must refuse to approve anything for that class rather than
    silently trusting a tag (Phase 7B.2 Part 12)."""
    candidate, resolver = valid_matmul_candidate
    monkeypatch.setitem(
        docker_policy._APPROVED_IMAGE_DIGESTS, ResourceClass.CLASS_ARRAY, "aikdap-execution:latest"
    )
    with pytest.raises(SecurityBlocked) as exc:
        await validate_and_approve(candidate, resolver)
    assert exc.value.check_name == "approved_digest_not_digest_shaped"


# ---------------------------------------------------------------------------
# Unknown / malformed requests
# ---------------------------------------------------------------------------


def test_unknown_capability_rejected_at_schema_boundary():
    with pytest.raises(ValidationError):
        _matmul_request(capability="not_a_real_capability")


def test_unknown_operation_rejected_at_schema_boundary():
    with pytest.raises(ValidationError):
        _matmul_request(operation="not_a_real_operation")


def test_unknown_resource_class_rejected_at_schema_boundary():
    with pytest.raises(ValidationError):
        _matmul_request(resource_class="not_a_real_class")


@pytest.mark.asyncio
async def test_capability_operation_mismatch_rejected(valid_matmul_candidate):
    candidate, resolver = valid_matmul_candidate
    # LaunchRequest is a frozen Pydantic model, not a stdlib dataclass --
    # model_copy(update=...) is its equivalent of dataclasses.replace().
    mismatched_request = candidate.request.model_copy(
        update={"capability": ExecutionCapability.EVALUATE_EXPRESSION}
    )
    bad = replace(candidate, request=mismatched_request)
    with pytest.raises(SecurityBlocked) as exc:
        await validate_and_approve(bad, resolver)
    assert exc.value.check_name == "capability_mismatch"


@pytest.mark.asyncio
async def test_resource_class_mismatch_rejected(valid_matmul_candidate):
    candidate, resolver = valid_matmul_candidate
    mismatched_request = candidate.request.model_copy(
        update={"resource_class": ResourceClass.CLASS_TABLE}
    )
    bad = replace(candidate, request=mismatched_request)
    with pytest.raises(SecurityBlocked) as exc:
        await validate_and_approve(bad, resolver)
    assert exc.value.check_name == "resource_class_mismatch"


@pytest.mark.asyncio
async def test_capability_operation_mismatch_rejected_by_translator():
    mismatched = _matmul_request(capability=ExecutionCapability.EVALUATE_EXPRESSION)
    resolver = _matmul_resolver()
    with pytest.raises(SecurityBlocked) as exc:
        await build_candidate(mismatched, resolver)
    assert exc.value.check_name == "capability_mismatch"


@pytest.mark.asyncio
async def test_unknown_operation_at_guard_level(valid_expr_candidate, monkeypatch):
    """Defense-in-depth backstop: even if the closed operation catalog
    were ever missing an entry for an otherwise-valid enum member, the
    guard fails closed rather than proceeding with an unresolved
    operation."""
    candidate, resolver = valid_expr_candidate
    monkeypatch.delitem(docker_policy._OPERATION_CATALOG, ExecutionOperation.EVALUATE_EXPRESSION)
    with pytest.raises(SecurityBlocked) as exc:
        await validate_and_approve(candidate, resolver)
    assert exc.value.check_name == "unknown_operation"


def test_launch_request_rejects_unknown_fields():
    """`extra='forbid'` -- the schema-level defense against smuggling a
    Docker-shaped field (an image, a path, a flag) onto the message at
    all (Phase 7B.2 Part B)."""
    with pytest.raises(ValidationError):
        _matmul_request(image="malicious:latest")


# ---------------------------------------------------------------------------
# Part J: unexpected fields cannot survive into ApprovedLaunchSpec
# ---------------------------------------------------------------------------


def test_approved_spec_has_no_field_for_privilege_escalating_options():
    """`ApprovedLaunchSpec` structurally has no `cap_add`, `devices`,
    `pid_mode`, `ipc_mode`, or `entrypoint` field at all -- their one
    legal value is implied by the type, never carried as data that could
    be overwritten or misread downstream."""
    approved_fields = {f for f in ApprovedLaunchSpec.__dataclass_fields__}
    for forbidden in ("cap_add", "devices", "pid_mode", "ipc_mode", "entrypoint"):
        assert forbidden not in approved_fields


def test_approved_spec_constructor_rejects_unknown_kwargs():
    """Proves the allowlist property structurally: even a caller with
    direct access to the dataclass constructor cannot attach an
    unrecognized field -- Python raises before the object exists."""
    with pytest.raises(TypeError):
        ApprovedLaunchSpec(  # type: ignore[call-arg]
            job_id=uuid.uuid4(),
            image="x",
            network_mode="none",
            privileged=False,
            cap_drop=("ALL",),
            security_opt=("no-new-privileges",),
            read_only=True,
            user="10001:10001",
            mem_limit_mb=256,
            memswap_limit_mb=256,
            cpus=1.0,
            pids_limit=32,
            tmpfs_mb=64,
            mounts=(),
            environment={},
            command=("python3",),
            timeout_s=10.0,
            extra_docker_flag="--privileged",  # not a real field
        )


# ---------------------------------------------------------------------------
# Part O: ApprovedLaunchSpec can only be produced by the guard
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_build_candidate_returns_candidate_type(valid_matmul_candidate):
    candidate, _ = valid_matmul_candidate
    assert type(candidate) is CandidateLaunchSpec
    assert type(candidate) is not ApprovedLaunchSpec


@pytest.mark.asyncio
async def test_validate_and_approve_returns_approved_type(valid_matmul_candidate):
    candidate, resolver = valid_matmul_candidate
    approved = await validate_and_approve(candidate, resolver)
    assert type(approved) is ApprovedLaunchSpec


def test_no_approved_launch_spec_construction_outside_docker_policy():
    """Structural scan: the only place in the (non-test) execution_launcher
    package that calls `ApprovedLaunchSpec(...)` is docker_policy.py's own
    `return` statement. `models.py`'s class definition doesn't count (no
    trailing paren after the class name)."""
    import pathlib
    import re

    package_dir = pathlib.Path(docker_policy.__file__).parent
    call_pattern = re.compile(r"ApprovedLaunchSpec\(")
    offending_files = []
    for path in package_dir.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        if call_pattern.search(text) and path.name != "docker_policy.py":
            offending_files.append(path.name)
    assert offending_files == []
    # And docker_policy.py itself must contain exactly the one approving call.
    docker_policy_text = pathlib.Path(docker_policy.__file__).read_text(encoding="utf-8")
    assert len(call_pattern.findall(docker_policy_text)) == 1


# ---------------------------------------------------------------------------
# Part M: no Docker SDK import anywhere in this slice
# ---------------------------------------------------------------------------


def _imports_docker_sdk(source: str) -> bool:
    """AST-based check, not substring matching -- a docstring that
    mentions 'import docker' in prose (as this file's own module
    docstring does, explaining what it does NOT do) must not itself
    trip a "contains the Docker SDK import" false positive. Only actual
    `Import`/`ImportFrom` nodes count."""
    import ast

    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any(alias.name == "docker" or alias.name.startswith("docker.") for alias in node.names):
                return True
        elif isinstance(node, ast.ImportFrom):
            if node.module == "docker" or (node.module or "").startswith("docker."):
                return True
    return False


def test_docker_policy_module_never_imports_docker_sdk():
    import pathlib

    text = pathlib.Path(docker_policy.__file__).read_text(encoding="utf-8")
    assert not _imports_docker_sdk(text), "docker_policy.py must not import the docker SDK"
    # Belt-and-suspenders textual check for the SDK's actual call sites
    # (these never legitimately appear in prose the way "import docker" can).
    for forbidden in ("docker.from_env", "DockerClient", "APIClient"):
        assert forbidden not in text, f"docker_policy.py must not contain {forbidden!r}"


def test_no_module_in_execution_launcher_imports_docker_sdk_except_launcher():
    """Sprint 16 Phase 7B.25: `launcher.py` is now the ONE designated
    boundary module permitted to import the Docker SDK -- every OTHER
    file in this package (policy, translator, resolvers, models) must
    stay exactly as Docker-free as before."""
    import pathlib

    package_dir = pathlib.Path(docker_policy.__file__).parent
    for path in package_dir.glob("*.py"):
        if path.name == "launcher.py":
            continue
        text = path.read_text(encoding="utf-8")
        assert not _imports_docker_sdk(text), f"{path.name} imports the Docker SDK"


def test_launcher_module_is_the_only_docker_sdk_importer_in_execution_launcher():
    import pathlib

    package_dir = pathlib.Path(docker_policy.__file__).parent
    importers = [
        path.name for path in package_dir.glob("*.py") if _imports_docker_sdk(path.read_text(encoding="utf-8"))
    ]
    assert importers == ["launcher.py"], importers


def test_docker_sdk_module_not_actually_imported_at_runtime():
    """AST-based (Sprint 16 Phase 7B.25 correction): a `sys.modules`
    check is no longer a valid full-suite proxy -- `execution_launcher.
    launcher` (a sibling module in this same package) now legitimately
    imports the Docker SDK, and pytest runs the whole suite in one
    process, so `sys.modules["docker"]` can already be populated by an
    unrelated test file that happened to run first. Re-checks these
    four modules' own source directly instead (same helper as
    `test_no_module_in_execution_launcher_imports_docker_sdk_except_launcher`
    above)."""
    import pathlib

    import execution_launcher.docker_policy as docker_policy_mod
    import execution_launcher.models as models_mod
    import execution_launcher.resolvers as resolvers_mod
    import execution_launcher.translator as translator_mod

    for module in (docker_policy_mod, translator_mod, models_mod, resolvers_mod):
        source = pathlib.Path(module.__file__).read_text(encoding="utf-8")
        assert not _imports_docker_sdk(source), module.__name__

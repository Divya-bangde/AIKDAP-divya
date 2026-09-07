"""Sprint 16 Phase 7B.4 -- `ProductionInputResolver` tests.

Real database (via the `session`/`project`-style fixtures already used
throughout this suite) and real filesystem I/O under the actual configured
storage root (`get_storage_provider()`) -- no mocks for the authorization
or filesystem checks themselves. `StaticInputResolver` (Phase 7B.3) is not
re-tested here; that suite already covers it.
"""

from __future__ import annotations

import inspect
import os
import uuid
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio

from app.modules.assets.enums import AssetSource, AssetStatus, AssetType
from app.modules.assets.models import Asset
from app.modules.assets.repository import AssetRepository
from app.modules.assets.storage import get_storage_provider
from app.modules.auth.models import User
from app.modules.projects.models import Project, ProjectStatus, ProjectType
from execution_launcher.models import InputResolutionError
from execution_launcher.resolvers import ProductionInputResolver


async def _make_owner_and_project(session, *, name: str) -> Project:
    user = User(
        email=f"pytest-resolver-{uuid.uuid4().hex[:12]}@example.com",
        hashed_password="not-a-real-hash",
        full_name="Resolver Test User",
        is_active=True,
    )
    session.add(user)
    await session.flush()

    project = Project(
        owner_id=user.id,
        name=name,
        description="Created by test_execution_input_resolver.py",
        project_type=ProjectType.RESEARCH,
        status=ProjectStatus.ACTIVE,
    )
    session.add(project)
    await session.flush()
    await session.commit()
    return project


async def _make_asset(session, project: Project, *, storage_path: str, file_name: str = "input.csv") -> Asset:
    asset = Asset(
        project_id=project.id,
        owner_id=project.owner_id,
        title=file_name,
        file_name=file_name,
        file_extension=file_name.rsplit(".", 1)[-1],
        mime_type="text/csv",
        file_size=0,
        storage_path=storage_path,
        checksum="test-checksum",
        asset_type=AssetType.DATASET,
        status=AssetStatus.ACTIVE,
        source=AssetSource.UPLOAD,
        tags=[],
    )
    return await AssetRepository(session).create(asset)


async def _write_real_file(project: Project, *, filename: str, content: bytes = b"a,b\n1,2\n") -> str:
    """Writes a real file under the actual storage root via the real
    `StorageProvider.save()` and returns the storage_path it assigns."""
    storage = get_storage_provider()
    return await storage.save(project_id=project.id, filename=filename, content=content)


@pytest_asyncio.fixture
async def project_a(session) -> AsyncIterator[Project]:
    project = await _make_owner_and_project(session, name="Resolver Project A")
    yield project
    user = await session.get(User, project.owner_id)
    if user is not None:
        await session.delete(user)
        await session.commit()


@pytest_asyncio.fixture
async def project_b(session) -> AsyncIterator[Project]:
    project = await _make_owner_and_project(session, name="Resolver Project B")
    yield project
    user = await session.get(User, project.owner_id)
    if user is not None:
        await session.delete(user)
        await session.commit()


@pytest.fixture
def resolver(session) -> ProductionInputResolver:
    return ProductionInputResolver(session)


# ---------------------------------------------------------------------------
# Test 1-6: authorization
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_valid_owner_project_asset_succeeds(session, resolver, project_a):
    storage_path = await _write_real_file(project_a, filename="valid.csv")
    asset = await _make_asset(session, project_a, storage_path=storage_path, file_name="valid.csv")
    await session.commit()

    resolved = await resolver.resolve(
        owner_id=project_a.owner_id, project_id=project_a.id, asset_id=asset.id
    )

    assert resolved.asset_id == asset.id
    assert resolved.mount_name == "valid.csv"
    assert os.path.isfile(resolved.host_path)


@pytest.mark.asyncio
async def test_wrong_owner_rejected(session, resolver, project_a):
    storage_path = await _write_real_file(project_a, filename="a.csv")
    asset = await _make_asset(session, project_a, storage_path=storage_path)
    await session.commit()

    with pytest.raises(InputResolutionError):
        await resolver.resolve(owner_id=uuid.uuid4(), project_id=project_a.id, asset_id=asset.id)


@pytest.mark.asyncio
async def test_wrong_project_rejected(session, resolver, project_a):
    storage_path = await _write_real_file(project_a, filename="a.csv")
    asset = await _make_asset(session, project_a, storage_path=storage_path)
    await session.commit()

    with pytest.raises(InputResolutionError):
        await resolver.resolve(
            owner_id=project_a.owner_id, project_id=uuid.uuid4(), asset_id=asset.id
        )


@pytest.mark.asyncio
async def test_asset_belongs_to_different_project_rejected(session, resolver, project_a, project_b):
    storage_path = await _write_real_file(project_a, filename="a.csv")
    asset = await _make_asset(session, project_a, storage_path=storage_path)
    await session.commit()

    # project_b is a real, owned project -- just not this asset's project.
    with pytest.raises(InputResolutionError):
        await resolver.resolve(
            owner_id=project_b.owner_id, project_id=project_b.id, asset_id=asset.id
        )


@pytest.mark.asyncio
async def test_missing_asset_rejected(resolver, project_a):
    with pytest.raises(InputResolutionError):
        await resolver.resolve(
            owner_id=project_a.owner_id, project_id=project_a.id, asset_id=uuid.uuid4()
        )


@pytest.mark.asyncio
async def test_cross_owner_asset_rejected(session, resolver, project_a, project_b):
    storage_path = await _write_real_file(project_a, filename="a.csv")
    asset = await _make_asset(session, project_a, storage_path=storage_path)
    await session.commit()

    with pytest.raises(InputResolutionError):
        await resolver.resolve(
            owner_id=project_b.owner_id, project_id=project_a.id, asset_id=asset.id
        )


# ---------------------------------------------------------------------------
# Test 7-13: filesystem security
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_valid_regular_file_succeeds(session, resolver, project_a):
    storage_path = await _write_real_file(project_a, filename="regular.csv")
    asset = await _make_asset(session, project_a, storage_path=storage_path, file_name="regular.csv")
    await session.commit()

    resolved = await resolver.resolve(
        owner_id=project_a.owner_id, project_id=project_a.id, asset_id=asset.id
    )
    assert os.path.isfile(resolved.host_path)


@pytest.mark.asyncio
async def test_missing_backing_file_rejected(session, resolver, project_a):
    """DB row exists; the file it points at was never written."""
    ghost_path = f"{project_a.id}/{uuid.uuid4()}_ghost.csv"
    asset = await _make_asset(session, project_a, storage_path=ghost_path)
    await session.commit()

    with pytest.raises(InputResolutionError):
        await resolver.resolve(
            owner_id=project_a.owner_id, project_id=project_a.id, asset_id=asset.id
        )


@pytest.mark.asyncio
async def test_directory_instead_of_file_rejected(session, resolver, project_a):
    storage = get_storage_provider()
    dir_relative = f"{project_a.id}/a_directory"
    (storage._base_dir / dir_relative).mkdir(parents=True, exist_ok=True)
    asset = await _make_asset(session, project_a, storage_path=dir_relative)
    await session.commit()

    with pytest.raises(InputResolutionError):
        await resolver.resolve(
            owner_id=project_a.owner_id, project_id=project_a.id, asset_id=asset.id
        )


@pytest.mark.asyncio
async def test_symlink_backing_path_rejected(session, resolver, project_a):
    storage = get_storage_provider()
    target_path = await _write_real_file(project_a, filename="symlink_target.csv")
    link_relative = f"{project_a.id}/{uuid.uuid4()}_link.csv"
    link_abs = storage._base_dir / link_relative
    target_abs = storage._base_dir / target_path
    try:
        link_abs.symlink_to(target_abs)
    except OSError as exc:
        pytest.skip(f"platform/permissions do not allow creating a symlink here: {exc}")

    asset = await _make_asset(session, project_a, storage_path=link_relative)
    await session.commit()

    with pytest.raises(InputResolutionError):
        await resolver.resolve(
            owner_id=project_a.owner_id, project_id=project_a.id, asset_id=asset.id
        )


@pytest.mark.asyncio
async def test_traversal_attempt_rejected(session, resolver, project_a):
    asset = await _make_asset(session, project_a, storage_path="../../secret.env")
    await session.commit()

    with pytest.raises(InputResolutionError):
        await resolver.resolve(
            owner_id=project_a.owner_id, project_id=project_a.id, asset_id=asset.id
        )


@pytest.mark.asyncio
async def test_absolute_external_path_rejected(session, resolver, project_a):
    external = "C:\\Windows\\win.ini" if os.name == "nt" else "/etc/passwd"
    asset = await _make_asset(session, project_a, storage_path=external)
    await session.commit()

    with pytest.raises(InputResolutionError):
        await resolver.resolve(
            owner_id=project_a.owner_id, project_id=project_a.id, asset_id=asset.id
        )


@pytest.mark.asyncio
async def test_storage_root_escape_rejected(session, resolver, project_a):
    asset = await _make_asset(session, project_a, storage_path="foo/../../secret")
    await session.commit()

    with pytest.raises(InputResolutionError):
        await resolver.resolve(
            owner_id=project_a.owner_id, project_id=project_a.id, asset_id=asset.id
        )


# ---------------------------------------------------------------------------
# Test 14-18: trust boundary
# ---------------------------------------------------------------------------


def test_resolve_has_no_caller_controlled_path_parameter():
    """Structural: `resolve()`'s only parameters are the three identifiers
    -- there is no `path` (or similarly-shaped) parameter for a caller to
    substitute a value through."""
    params = set(inspect.signature(ProductionInputResolver.resolve).parameters)
    assert params == {"self", "owner_id", "project_id", "asset_id"}


@pytest.mark.asyncio
async def test_resolved_path_derives_from_asset_metadata_not_a_guess(session, resolver, project_a):
    storage_path = await _write_real_file(project_a, filename="metadata_derived.csv")
    asset = await _make_asset(
        session, project_a, storage_path=storage_path, file_name="metadata_derived.csv"
    )
    await session.commit()

    resolved = await resolver.resolve(
        owner_id=project_a.owner_id, project_id=project_a.id, asset_id=asset.id
    )

    storage = get_storage_provider()
    assert resolved.host_path == str(storage._resolve(storage_path))


@pytest.mark.asyncio
async def test_resolution_is_fresh_not_cached(session, resolver, project_a, project_b):
    """Revoking access between two calls (moving the asset to another
    project) must be reflected on the second call -- proves there is no
    resolver-side cache of a prior authorization decision."""
    storage_path = await _write_real_file(project_a, filename="revocable.csv")
    asset = await _make_asset(session, project_a, storage_path=storage_path)
    await session.commit()

    first = await resolver.resolve(
        owner_id=project_a.owner_id, project_id=project_a.id, asset_id=asset.id
    )
    assert first.asset_id == asset.id

    asset.project_id = project_b.id
    asset.owner_id = project_b.owner_id
    await session.commit()

    with pytest.raises(InputResolutionError):
        await resolver.resolve(
            owner_id=project_a.owner_id, project_id=project_a.id, asset_id=asset.id
        )


@pytest.mark.asyncio
async def test_identical_filenames_across_projects_stay_isolated(session, resolver, project_a, project_b):
    path_a = await _write_real_file(project_a, filename="results.csv", content=b"project-a-data\n")
    path_b = await _write_real_file(project_b, filename="results.csv", content=b"project-b-data\n")
    asset_a = await _make_asset(session, project_a, storage_path=path_a, file_name="results.csv")
    asset_b = await _make_asset(session, project_b, storage_path=path_b, file_name="results.csv")
    await session.commit()

    resolved_a = await resolver.resolve(
        owner_id=project_a.owner_id, project_id=project_a.id, asset_id=asset_a.id
    )
    resolved_b = await resolver.resolve(
        owner_id=project_b.owner_id, project_id=project_b.id, asset_id=asset_b.id
    )

    assert resolved_a.host_path != resolved_b.host_path
    with open(resolved_a.host_path, "rb") as f:
        assert f.read() == b"project-a-data\n"
    with open(resolved_b.host_path, "rb") as f:
        assert f.read() == b"project-b-data\n"

    # Requesting Project B's asset under Project A's identity must fail --
    # not silently return Project A's same-named file.
    with pytest.raises(InputResolutionError):
        await resolver.resolve(
            owner_id=project_a.owner_id, project_id=project_a.id, asset_id=asset_b.id
        )


@pytest.mark.asyncio
async def test_storage_metadata_pointing_outside_root_rejected(session, resolver, project_a):
    """Same guarantee as the traversal/absolute-path tests, framed as the
    prompt's Test 18: authorized asset, tampered/corrupted metadata."""
    asset = await _make_asset(session, project_a, storage_path="../outside_root.txt")
    await session.commit()

    with pytest.raises(InputResolutionError):
        await resolver.resolve(
            owner_id=project_a.owner_id, project_id=project_a.id, asset_id=asset.id
        )


# ---------------------------------------------------------------------------
# Cross-project isolation topology (Owner A/Project A/Asset A,
# Owner B/Project B/Asset B), matching the prompt's explicit test topology.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cross_project_isolation_topology(session, resolver, project_a, project_b):
    path_a = await _write_real_file(project_a, filename="topology.csv")
    path_b = await _write_real_file(project_b, filename="topology.csv")
    asset_a = await _make_asset(session, project_a, storage_path=path_a)
    asset_b = await _make_asset(session, project_b, storage_path=path_b)
    await session.commit()

    with pytest.raises(InputResolutionError):
        await resolver.resolve(owner_id=project_a.owner_id, project_id=project_a.id, asset_id=asset_b.id)

    with pytest.raises(InputResolutionError):
        await resolver.resolve(owner_id=project_b.owner_id, project_id=project_b.id, asset_id=asset_a.id)


# ---------------------------------------------------------------------------
# Path normalization: forms that STAY inside the root must still resolve
# correctly and deterministically (canonicalization, not string matching).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_contained_relative_forms_still_resolve_via_canonicalization(session, resolver, project_a):
    storage_path = await _write_real_file(project_a, filename="norm.csv")
    storage = get_storage_provider()
    # `<proj>/x/../<uuid>_norm.csv` still canonicalizes to the same real
    # file -- proves resolution goes through Path.resolve(), not a naive
    # string prefix check that could be fooled by either form.
    parts = storage_path.split("/")
    noisy_path = "/".join(parts[:-1]) + "/does_not_exist/../" + parts[-1]
    asset = await _make_asset(session, project_a, storage_path=noisy_path, file_name="norm.csv")
    await session.commit()

    resolved = await resolver.resolve(
        owner_id=project_a.owner_id, project_id=project_a.id, asset_id=asset.id
    )
    assert resolved.host_path == str(storage._resolve(storage_path))


# ---------------------------------------------------------------------------
# Structural security checks
# ---------------------------------------------------------------------------


def _imports_any_of(source: str, module_names: set[str]) -> bool:
    import ast

    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any(alias.name.split(".")[0] in module_names for alias in node.names):
                return True
        elif isinstance(node, ast.ImportFrom):
            if (node.module or "").split(".")[0] in module_names:
                return True
    return False


def test_resolver_module_imports_no_docker_or_subprocess():
    import pathlib

    import execution_launcher.resolvers as resolvers_module

    source = pathlib.Path(resolvers_module.__file__).read_text(encoding="utf-8")
    assert not _imports_any_of(source, {"docker", "subprocess"})


def test_resolver_module_does_not_call_shell_or_read_dotenv_directly():
    import pathlib

    import execution_launcher.resolvers as resolvers_module

    source = pathlib.Path(resolvers_module.__file__).read_text(encoding="utf-8")
    for forbidden in ("os.system(", "os.popen(", "shell=True", "load_dotenv", "open(\".env\"", "open('.env'"):
        assert forbidden not in source


def test_production_resolver_never_instantiates_static_resolver():
    """No production fallback: `ProductionInputResolver` never constructs
    a `StaticInputResolver` internally."""
    import inspect as _inspect

    source = _inspect.getsource(ProductionInputResolver)
    assert "StaticInputResolver(" not in source


def test_docker_sdk_not_imported_at_runtime_by_resolver_module():
    """AST-based (Sprint 16 Phase 7B.25 correction): a `sys.modules`
    check is no longer a valid proxy -- `execution_launcher.launcher`
    (a SIBLING module in the same package) now legitimately imports the
    Docker SDK, and pytest runs the whole suite in one process, so
    `sys.modules["docker"]` can already be populated by an unrelated
    test file by the time this one runs. Checks `resolvers.py`'s own
    source directly instead."""
    import pathlib

    import execution_launcher.resolvers as resolvers_module

    source = pathlib.Path(resolvers_module.__file__).read_text(encoding="utf-8")
    assert not _imports_any_of(source, {"docker"})

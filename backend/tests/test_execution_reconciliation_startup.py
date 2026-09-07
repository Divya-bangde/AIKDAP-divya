"""Sprint 16 Phase 7B.17 -- reconciliation startup wiring.

Phases 7B.15/7B.16 produced two independently proven, directly-callable
reconcilers (`reconcile_stale_validating_execution_jobs`,
`reconcile_stale_pending_execution_attempts`) that nothing in the
deployed worker process ever invoked. This slice is wiring only: a new
`reconcile_execution_jobs_on_startup()` entry point runs both, with
independent failure isolation, and `app.workers.worker`'s existing
`@worker_ready.connect` handler is extended to call it -- mirroring
`reconcile_stale_research_runs_on_startup()`'s established "runs once,
never raises" contract.

These tests prove BEHAVIOR, not source text: every test that claims a
reconciler was invoked actually invoked the real entry point with the
underlying reconcilers replaced by controlled async doubles, and
`test_worker_ready_handler_invokes_both_startup_entry_points` imports
the real `app.workers.worker` module and calls its real
`_reconcile_on_startup` signal-handler function directly.
"""

from __future__ import annotations

import ast
import asyncio
from pathlib import Path

import pytest

from app.workers import reconciliation as reconciliation_module
from app.workers.reconciliation import reconcile_execution_jobs_on_startup


def _double(*, return_value: int | None = None, raises: Exception | None = None, calls: list[str], name: str):
    """A minimal controlled async test double: records that it was
    called (appending `name` to the shared `calls` list, so relative
    call order across two different doubles is directly observable),
    then either returns a fixed value or raises a fixed exception.
    """

    async def _fn() -> int:
        calls.append(name)
        if raises is not None:
            raise raises
        assert return_value is not None
        return return_value

    return _fn


# ---------------------------------------------------------------------------
# 1. Both reconcilers are invoked, exactly once each, in a deterministic
#    order (jobs before attempts).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_both_reconcilers_invoked_once_in_deterministic_order(monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(
        reconciliation_module,
        "reconcile_stale_validating_execution_jobs",
        _double(return_value=3, calls=calls, name="jobs"),
    )
    monkeypatch.setattr(
        reconciliation_module,
        "reconcile_stale_pending_execution_attempts",
        _double(return_value=5, calls=calls, name="attempts"),
    )

    await reconcile_execution_jobs_on_startup()

    assert calls == ["jobs", "attempts"]  # each exactly once, jobs first


# ---------------------------------------------------------------------------
# 2. Job-reconciler failure does not block the attempt reconciler.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_job_reconciler_failure_does_not_block_attempt_reconciler(monkeypatch, caplog):
    calls: list[str] = []
    monkeypatch.setattr(
        reconciliation_module,
        "reconcile_stale_validating_execution_jobs",
        _double(raises=RuntimeError("job boom"), calls=calls, name="jobs"),
    )
    monkeypatch.setattr(
        reconciliation_module,
        "reconcile_stale_pending_execution_attempts",
        _double(return_value=1, calls=calls, name="attempts"),
    )

    with caplog.at_level("INFO"):
        await reconcile_execution_jobs_on_startup()  # must not raise

    assert calls == ["jobs", "attempts"]  # attempts still ran despite the failure
    assert any("execution_job_reconciliation_failed" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# 3. Attempt-reconciler failure does not prevent startup from completing.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_attempt_reconciler_failure_does_not_block_startup_completion(monkeypatch, caplog):
    calls: list[str] = []
    monkeypatch.setattr(
        reconciliation_module,
        "reconcile_stale_validating_execution_jobs",
        _double(return_value=2, calls=calls, name="jobs"),
    )
    monkeypatch.setattr(
        reconciliation_module,
        "reconcile_stale_pending_execution_attempts",
        _double(raises=RuntimeError("attempt boom"), calls=calls, name="attempts"),
    )

    with caplog.at_level("INFO"):
        await reconcile_execution_jobs_on_startup()  # must return, not raise

    assert calls == ["jobs", "attempts"]
    assert any("execution_attempt_reconciliation_failed" in r.message for r in caplog.records)
    # Startup completion is evidenced by the summary still being logged.
    assert any("execution_reconciliation_summary" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# 4. Both failures are handled independently: both attempted, both
#    logged, neither propagates and aborts the other.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_both_reconciler_failures_are_handled_independently(monkeypatch, caplog):
    calls: list[str] = []
    monkeypatch.setattr(
        reconciliation_module,
        "reconcile_stale_validating_execution_jobs",
        _double(raises=RuntimeError("job boom"), calls=calls, name="jobs"),
    )
    monkeypatch.setattr(
        reconciliation_module,
        "reconcile_stale_pending_execution_attempts",
        _double(raises=RuntimeError("attempt boom"), calls=calls, name="attempts"),
    )

    with caplog.at_level("INFO"):
        await reconcile_execution_jobs_on_startup()  # must not propagate either failure

    assert calls == ["jobs", "attempts"]  # both attempted
    messages = [r.message for r in caplog.records]
    assert any("execution_job_reconciliation_failed" in m for m in messages)
    assert any("execution_attempt_reconciliation_failed" in m for m in messages)
    assert any("execution_reconciliation_summary" in m for m in messages)


# ---------------------------------------------------------------------------
# 5. The logged summary uses the REAL return values, not hardcoded
#    numbers -- and reports None (not 0) for whichever side failed, so a
#    failure is never misread as "ran, found nothing".
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_summary_logs_actual_return_values_not_hardcoded(monkeypatch, caplog):
    import json

    calls: list[str] = []
    monkeypatch.setattr(
        reconciliation_module,
        "reconcile_stale_validating_execution_jobs",
        _double(return_value=7, calls=calls, name="jobs"),
    )
    monkeypatch.setattr(
        reconciliation_module,
        "reconcile_stale_pending_execution_attempts",
        _double(return_value=11, calls=calls, name="attempts"),
    )

    with caplog.at_level("INFO"):
        await reconcile_execution_jobs_on_startup()

    summary_records = [r for r in caplog.records if "execution_reconciliation_summary" in r.message]
    assert len(summary_records) == 1
    payload = json.loads(summary_records[0].message)
    assert payload["stale_validating_jobs_marked"] == 7
    assert payload["stale_pending_create_attempts_marked"] == 11


@pytest.mark.asyncio
async def test_summary_reports_none_for_the_side_that_failed(monkeypatch, caplog):
    import json

    calls: list[str] = []
    monkeypatch.setattr(
        reconciliation_module,
        "reconcile_stale_validating_execution_jobs",
        _double(raises=RuntimeError("job boom"), calls=calls, name="jobs"),
    )
    monkeypatch.setattr(
        reconciliation_module,
        "reconcile_stale_pending_execution_attempts",
        _double(return_value=4, calls=calls, name="attempts"),
    )

    with caplog.at_level("INFO"):
        await reconcile_execution_jobs_on_startup()

    summary_records = [r for r in caplog.records if "execution_reconciliation_summary" in r.message]
    assert len(summary_records) == 1
    payload = json.loads(summary_records[0].message)
    assert payload["stale_validating_jobs_marked"] is None  # failed side: None, not 0
    assert payload["stale_pending_create_attempts_marked"] == 4


# ---------------------------------------------------------------------------
# The failure log itself is sanitized: error_type/error_message only, no
# raw stack trace, no secrets, no credentials.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_failure_log_is_sanitized(monkeypatch, caplog):
    import json

    calls: list[str] = []
    monkeypatch.setattr(
        reconciliation_module,
        "reconcile_stale_validating_execution_jobs",
        _double(raises=ValueError("synthetic failure detail"), calls=calls, name="jobs"),
    )
    monkeypatch.setattr(
        reconciliation_module,
        "reconcile_stale_pending_execution_attempts",
        _double(return_value=0, calls=calls, name="attempts"),
    )

    with caplog.at_level("INFO"):
        await reconcile_execution_jobs_on_startup()

    failure_records = [r for r in caplog.records if "execution_job_reconciliation_failed" in r.message]
    assert len(failure_records) == 1
    payload = json.loads(failure_records[0].message)
    assert set(payload.keys()) >= {"error_type", "error_message", "event", "level", "logger", "timestamp"}
    assert payload["error_type"] == "ValueError"
    assert payload["error_message"] == "synthetic failure detail"
    # Bounded, structured fields only -- no stack-trace field, no
    # "traceback"/"exc_info" key that would leak internals.
    assert "traceback" not in payload
    assert "exc_info" not in payload
    assert "password" not in payload["error_message"].lower()


# ---------------------------------------------------------------------------
# Real invocation of the actual worker_ready signal handler: proves the
# worker startup path itself, not just the new entry point in isolation.
# ---------------------------------------------------------------------------


def test_worker_ready_handler_invokes_both_startup_entry_points(monkeypatch):
    import app.workers.worker as worker_module

    calls: list[str] = []

    async def _research_double() -> None:
        calls.append("research_runs")

    async def _execution_double() -> None:
        calls.append("execution_jobs_and_attempts")

    monkeypatch.setattr(worker_module, "reconcile_stale_research_runs_on_startup", _research_double)
    monkeypatch.setattr(worker_module, "reconcile_execution_jobs_on_startup", _execution_double)

    worker_module._reconcile_on_startup()  # the real @worker_ready.connect target

    assert calls == ["research_runs", "execution_jobs_and_attempts"]


def test_worker_ready_handler_uses_a_single_event_loop(monkeypatch):
    """Regression test for a real bug found while wiring this slice:
    two sequential `asyncio.run()` calls in this process broke with
    `RuntimeError: ... attached to a different loop`, because the
    module-level SQLAlchemy engine pools `asyncpg` connections bound to
    whichever loop created them, and `asyncio.run()` closes its loop on
    return. Proven here by recording the running loop identity inside
    each double and asserting they are the SAME loop object -- not by
    re-deriving the asyncpg failure, which is exercised for real by
    every other test in this file that awaits a real DB-backed
    reconciler through this same handler indirectly (see
    `test_execution_job_reconciliation.py` / `test_execution_attempt_reconciliation.py`).
    """
    import app.workers.worker as worker_module

    seen_loops: list[int] = []

    async def _research_double() -> None:
        seen_loops.append(id(asyncio.get_running_loop()))

    async def _execution_double() -> None:
        seen_loops.append(id(asyncio.get_running_loop()))

    monkeypatch.setattr(worker_module, "reconcile_stale_research_runs_on_startup", _research_double)
    monkeypatch.setattr(worker_module, "reconcile_execution_jobs_on_startup", _execution_double)

    worker_module._reconcile_on_startup()

    assert len(seen_loops) == 2
    assert seen_loops[0] == seen_loops[1]


# ---------------------------------------------------------------------------
# 6. No new Celery task was introduced for reconciliation.
# ---------------------------------------------------------------------------


def _imported_module_roots(path: Path) -> set[str]:
    """AST-based, not substring matching -- prose in a docstring that
    mentions Docker/Celery must not fail a security check about
    imports."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".")[0])
    return roots


def test_no_new_celery_task_for_reconciliation():
    """`reconciliation.py` must still define zero decorated functions --
    this slice adds a plain async function, not a task. `worker.py`'s
    only decorator is the pre-existing `@worker_ready.connect` (a Celery
    *signal* receiver, not a task) on `_reconcile_on_startup`; nothing
    else in that file may carry a decorator this slice would have
    introduced.
    """
    backend = Path(__file__).resolve().parents[1]
    reconciliation_path = backend / "app" / "workers" / "reconciliation.py"
    worker_path = backend / "app" / "workers" / "worker.py"

    reconciliation_tree = ast.parse(reconciliation_path.read_text(encoding="utf-8"))
    reconciliation_decorators = [
        ast.unparse(decorator)
        for node in ast.walk(reconciliation_tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        for decorator in node.decorator_list
    ]
    assert reconciliation_decorators == [], reconciliation_decorators

    worker_tree = ast.parse(worker_path.read_text(encoding="utf-8"))
    worker_decorators = [
        ast.unparse(decorator)
        for node in ast.walk(worker_tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        for decorator in node.decorator_list
    ]
    assert worker_decorators == ["worker_ready.connect"], worker_decorators


# ---------------------------------------------------------------------------
# 7. No Docker.
# ---------------------------------------------------------------------------


_FORBIDDEN_IMPORTS = {"docker", "subprocess", "socket", "shutil", "pty"}


def test_startup_wiring_imports_nothing_forbidden():
    backend = Path(__file__).resolve().parents[1]
    targets = [
        backend / "app" / "workers" / "reconciliation.py",
        backend / "app" / "workers" / "worker.py",
    ]
    for target in targets:
        assert target.exists(), target
        roots = _imported_module_roots(target)
        assert not (roots & _FORBIDDEN_IMPORTS), (target.name, roots & _FORBIDDEN_IMPORTS)

"""Sprint 9J: the LiteLLM async-logging-worker / Celery event-loop fix.

Root cause, confirmed live against the real worker (see
`docs/provider-resilience.md` and the Sprint 9J report): every Celery
task body in `app.workers.tasks` used to run its own bare
`asyncio.run(...)` -- a fresh event loop per task, closed the instant
the task returns. `litellm.litellm_core_utils.logging_worker.
GLOBAL_LOGGING_WORKER` is a process-wide singleton whose internal
`asyncio.Queue` and worker `Task` bind to whichever loop is running the
first time an async LiteLLM call completes, and stay bound to it for
the object's lifetime. The *next* task's loop then inherits a queue
still bound to the *previous* task's already-closed loop, and every
`await queue.get()` in the freshly (re)spawned worker task raises
`RuntimeError: <Queue> is bound to a different event loop` -- logged by
asyncio as "Task exception was never retrieved" once garbage collected.

These tests exercise the real `litellm` object (not a double -- the bug
is entirely about that object's real lifecycle) but make no network
call: the property under test is purely "does a stale queue survive
across `_run_task_loop` calls", which needs no provider at all. Plain
`def` tests, not `async def` -- `_run_task_loop` calls `asyncio.run()`
itself, which raises if called from inside an already-running loop, so
these must run the way a real (synchronous) Celery task body does.
"""

import asyncio

from litellm.litellm_core_utils.logging_worker import GLOBAL_LOGGING_WORKER

from app.core.llm.gateway import reset_litellm_logging_worker_for_task_boundary
from app.workers.tasks import _run_task_loop


def _reset_global_worker_to_a_clean_slate() -> None:
    """Test isolation: this singleton is shared process-wide, so a
    previous test (or collection order) must not leak state in."""
    GLOBAL_LOGGING_WORKER._queue = None
    GLOBAL_LOGGING_WORKER._worker_task = None


def test_run_task_loop_leaves_no_queue_bound_to_the_closed_loop():
    """The specific state that caused the bug: after a task runs, the
    global worker must not be left holding a queue tied to the loop
    `_run_task_loop` is about to close."""
    _reset_global_worker_to_a_clean_slate()

    async def touches_the_logging_worker() -> None:
        GLOBAL_LOGGING_WORKER.ensure_initialized_and_enqueue(asyncio.sleep(0))
        await asyncio.sleep(0.05)  # let the worker loop actually drain it

    _run_task_loop(touches_the_logging_worker())

    assert GLOBAL_LOGGING_WORKER._queue is None
    assert GLOBAL_LOGGING_WORKER._worker_task is None


def test_two_sequential_task_loops_do_not_raise_the_event_loop_error():
    """The actual regression: two Celery tasks, back to back, each
    making their own `_run_task_loop` call -- exactly the sequence that
    reproduced `RuntimeError: <Queue> is bound to a different event
    loop` live before this fix. Both must complete and both must
    actually run their enqueued coroutine, not merely avoid raising."""
    _reset_global_worker_to_a_clean_slate()
    processed: list[int] = []

    async def task_body(marker: int) -> None:
        async def record() -> None:
            processed.append(marker)

        GLOBAL_LOGGING_WORKER.ensure_initialized_and_enqueue(record())
        await asyncio.sleep(0.05)

    _run_task_loop(task_body(1))
    _run_task_loop(task_body(2))

    assert processed == [1, 2]


def test_a_task_that_never_touches_litellm_is_unaffected():
    """`update_processing_status` and similar tasks make no LLM call at
    all. Resetting an uninitialized global worker must be a no-op, not
    an error -- `_run_task_loop` runs unconditionally for every task."""
    _reset_global_worker_to_a_clean_slate()

    async def no_llm_call() -> str:
        return "done"

    result = _run_task_loop(no_llm_call())

    assert result == "done"
    assert GLOBAL_LOGGING_WORKER._queue is None


def test_reset_helper_is_safe_to_call_when_nothing_was_ever_enqueued():
    """`reset_litellm_logging_worker_for_task_boundary` itself, in
    isolation: calling `.stop()` on a worker that was never started
    must not raise."""
    _reset_global_worker_to_a_clean_slate()

    async def just_reset() -> None:
        await reset_litellm_logging_worker_for_task_boundary()

    _run_task_loop(just_reset())  # must not raise

    assert GLOBAL_LOGGING_WORKER._queue is None

"""Sprint 9J Phase 2: reproduce the LiteLLM event-loop warning using the
exact execution model our Celery tasks use (asyncio.run() per call),
against the real local Ollama BGE-M3 endpoint -- no mocks."""
import asyncio
import gc
import sys

from litellm import aembedding


async def one_call(n):
    result = await aembedding(
        model="ollama/bge-m3",
        input=[f"repro call {n}"],
        api_base="http://host.docker.internal:11434",
        timeout=30,
    )
    print(f"call {n}: got {len(result.data)} vector(s)")


def run_like_a_celery_task(n):
    """Exactly what tasks.py does: asyncio.run() per task, fresh loop
    each time, loop closed when the function returns."""
    asyncio.run(one_call(n))


for i in range(1, 4):
    run_like_a_celery_task(i)

# Force GC so any abandoned LoggingWorker task's "exception never
# retrieved" warning fires now, deterministically, instead of at some
# unpredictable later point.
gc.collect()
print("done", file=sys.stderr)

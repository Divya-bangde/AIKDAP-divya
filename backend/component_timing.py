"""Sprint 9I Phase 2/3: isolate /health component latency, run inside aikdap_backend."""
import asyncio
import time

from app.database.session import async_session_factory
from app.modules.health.service import HealthService


async def main():
    async with async_session_factory() as session:
        svc = HealthService(session)

        checks = {
            "postgres": svc._check_postgres,
            "redis": svc._check_redis,
            "worker": svc._check_worker,
            "reranker": svc._check_reranker,
        }

        for name, fn in checks.items():
            times = []
            for _ in range(5):
                t0 = time.perf_counter()
                await fn()
                times.append((time.perf_counter() - t0) * 1000)
            print(f"{name}: {[round(t,1) for t in times]} ms")

        # provider health (sync, not awaited in a check but called directly)
        from app.core.llm.health import describe_providers
        times = []
        for _ in range(5):
            t0 = time.perf_counter()
            describe_providers()
            times.append((time.perf_counter() - t0) * 1000)
        print(f"provider_health(describe_providers): {[round(t,1) for t in times]} ms")


asyncio.run(main())

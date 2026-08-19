"""Sprint 9I Phase 3: root-cause the ~2s Celery control.ping() cost.

Hypothesis: control.ping() is a broadcast that does not know in advance
how many workers exist, so it waits out the FULL timeout collecting
replies rather than returning as soon as the (single) worker answers.
Test this directly by varying the timeout and by asking how many
workers are actually registered.
"""
import time

from app.workers.celery_app import celery_app

print("--- registered worker names (control.inspect) ---")
t0 = time.perf_counter()
insp = celery_app.control.inspect(timeout=1.0)
active = insp.ping()
print(f"inspect().ping() -> {active} in {(time.perf_counter()-t0)*1000:.1f}ms")

for timeout in (2.0, 1.0, 0.5, 0.3, 0.1):
    t0 = time.perf_counter()
    replies = celery_app.control.ping(timeout=timeout)
    elapsed = (time.perf_counter() - t0) * 1000
    print(f"control.ping(timeout={timeout}) -> {replies} in {elapsed:.1f}ms")

print("--- destination-limited ping (tell it exactly which worker to expect) ---")
names = [name for reply in (celery_app.control.ping(timeout=1.0) or []) for name in reply]
print("known worker names:", names)
if names:
    t0 = time.perf_counter()
    replies = celery_app.control.ping(timeout=2.0, destination=names)
    print(f"control.ping(timeout=2.0, destination={names}) -> {replies} in {(time.perf_counter()-t0)*1000:.1f}ms")

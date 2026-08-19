"""Does a destination-limited ping to a NAME THAT DOESN'T EXIST still
wait out the full timeout, or fail fast? This determines whether a
stale-cache fallback is safe (i.e. whether it can ever under-report
without an equally long wait, and whether that wait is still bounded)."""
import time

from app.workers.celery_app import celery_app

t0 = time.perf_counter()
replies = celery_app.control.ping(timeout=2.0, destination=["celery@doesnotexist"])
print(f"ping to nonexistent destination -> {replies} in {(time.perf_counter()-t0)*1000:.1f}ms")

t0 = time.perf_counter()
replies = celery_app.control.ping(timeout=0.5, destination=["celery@doesnotexist"])
print(f"ping(timeout=0.5) to nonexistent destination -> {replies} in {(time.perf_counter()-t0)*1000:.1f}ms")

"""Sprint 9J: temporarily block Gemini and Groq via the real Redis
provider-health registry, so a real research run falls through to
OpenRouter -- exercising three real provider calls inside one Celery
task/event loop, the scenario most likely to stress the logging-worker
fix."""
from app.core.llm.errors import LLMQuotaExhaustedError
from app.core.llm.provider_health import RedisProviderHealthRegistry
from app.core.config import settings

registry = RedisProviderHealthRegistry(redis_url=settings.celery_broker_url)
registry.record_failure("gemini/gemini-flash-latest", error=LLMQuotaExhaustedError("simulated for Sprint 9J"))
registry.record_failure("groq/openai/gpt-oss-120b", error=LLMQuotaExhaustedError("simulated for Sprint 9J"))
print("blocked gemini + groq:")
print(" gemini:", registry.status("gemini/gemini-flash-latest"))
print(" groq:", registry.status("groq/openai/gpt-oss-120b"))

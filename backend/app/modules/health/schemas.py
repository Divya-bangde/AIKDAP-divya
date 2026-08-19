"""Response models for `GET /health` (Sprint 9G).

Two levels of status, and the distinction matters:

- **Component status** answers "what is wrong?" and is deliberately
  rich — `quota_exhausted` is not the same operational problem as
  `unavailable`, and an operator paged at 3am should not have to guess
  which one they have.
- **Overall status** answers "can the platform do its job?" and is
  deliberately blunt: three values, no nuance.

Nothing here can carry a credential. Component details are short
operator-facing strings assembled from already-scrubbed error text.
"""

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ComponentStatus(str, Enum):
    """How one dependency is doing.

    The set is a superset of what any single component uses — LLM
    providers can be `quota_exhausted`, a database cannot — because one
    vocabulary across the whole response is easier to read and to alert
    on than a different enum per component.
    """

    #: Verified working.
    HEALTHY = "healthy"
    #: Working, but with reduced capability (e.g. the primary model is
    #: blocked and a fallback is carrying traffic).
    DEGRADED = "degraded"
    #: Credentials or configuration are present; nothing has exercised
    #: it yet. Explicitly NOT a claim that it works.
    CONFIGURED = "configured"
    #: A long-window (typically daily) model quota is spent.
    QUOTA_EXHAUSTED = "quota_exhausted"
    #: A short-window rate limit is currently in effect.
    RATE_LIMITED = "rate_limited"
    #: Not reachable.
    UNAVAILABLE = "unavailable"
    #: Reachable but not ready — still starting or loading.
    LOADING = "loading"
    #: Switched off by configuration. Not a fault.
    DISABLED = "disabled"
    #: No credentials configured. Not a fault for an optional
    #: component; the point is to make its absence visible.
    NOT_CONFIGURED = "not_configured"
    #: Rejected credentials, an unknown model, or a request the
    #: provider refuses — a deployment problem, not an outage.
    CONFIGURATION_ERROR = "configuration_error"
    #: The check itself could not be performed.
    UNKNOWN = "unknown"


class OverallStatus(str, Enum):
    """Whether the platform as a whole can serve.

    `unhealthy` is reserved for losing something the API cannot work
    without at all. Everything else is `degraded`: an unconfigured
    optional fallback, a dead reranker, or a spent Gemini quota all
    reduce capability without stopping the platform, and reporting them
    as `unhealthy` would train operators to ignore the field.
    """

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


class ComponentHealth(BaseModel):
    """One dependency's state, plus whatever context helps diagnose it."""

    model_config = ConfigDict(use_enum_values=True)

    status: ComponentStatus
    #: One short operator-facing sentence. Never raw provider output,
    #: never a credential.
    detail: str | None = None
    #: How long the check took, when a check was actually performed.
    #: `None` for states read from cached knowledge rather than probed.
    latency_ms: int | None = None
    #: Component-specific context: model ids, endpoints, cooldowns.
    #: Free-form because a database and an LLM provider have nothing
    #: useful in common, and forcing them into one shape would mean
    #: dropping the parts that matter.
    meta: dict[str, Any] = Field(default_factory=dict)


class HealthResponse(BaseModel):
    """The full health report.

    Always served with HTTP 200, including when `status` is
    `unhealthy`. The endpoint's job is to *report* the state; using the
    HTTP status to encode it as well means an orchestrator's liveness
    probe would restart a container whose only problem is that a
    third-party model provider ran out of free quota.
    """

    model_config = ConfigDict(use_enum_values=True)

    status: OverallStatus
    app: str
    version: str
    environment: str
    #: Keyed by component name: `postgres`, `redis`, `worker`,
    #: `reranker`, and one entry per configured LLM provider.
    services: dict[str, ComponentHealth]

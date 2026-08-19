# LLM provider resilience

Sprint 9G/9H. What the AIKDAP LLM gateway does when a model provider
says no, and why it does that rather than something else.

All measurements below are live, taken against this deployment on
2026-08-16 and 2026-08-18 (Sprint 9G) and 2026-08-18 (Sprint 9H).

**Sprint 9H changed two things.** DeepSeek — this deployment's second
fallback, unusable since Sprint 9G because its account has zero balance
— was replaced by OpenRouter as the active `SECONDARY_FALLBACK_LLM`.
And provider health moved from one process's memory to Redis, so the
API and the Celery worker now see the same breaker state instead of
each discovering failures independently. Both changes are covered in
their own sections below; everything else on this page — the error
taxonomy, the retry policy, the fallback-chain mechanics — is Sprint
9G's design, unchanged, and still accurate.

---

## The problem this solves

Sprint 9F ended blocked. Gemini's free tier allows **20
`generateContent` requests per project per model per day**, that
allowance was spent, and two acceptance phases could not be completed.
Nothing in the platform noticed, adapted, or reported it usefully — a
research run simply failed with a provider error, and the only way to
learn why was to read the exception text.

The refusal itself is worth reading, because the whole design follows
from it:

```json
{"error": {"code": 429,
  "message": "You exceeded your current quota, please check your plan and
              billing details. ... limit: 20, model: gemini-3.7-flash
              Please retry in 35.081138648s.",
  "status": "RESOURCE_EXHAUSTED",
  "details": [
    {"@type": ".../QuotaFailure", "violations": [{
        "quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier",
        "quotaValue": "20"}]},
    {"@type": ".../RetryInfo", "retryDelay": "35s"}]}}
```

Two traps in one response:

1. **`retryDelay: "35s"` on a quota that resets once a day.** Any retry
   loop that honours the provider's own hint will retry politely,
   forever, and never succeed. The gateway therefore ignores
   provider-supplied retry hints entirely.
2. **The message text is identical to the per-minute rate limit.**
   Google uses the same "exceeded your current quota / check your plan
   and billing details" wording for both. Matching on it would classify
   every transient limit as a spent day and disable a working provider
   for an hour.

Only `quotaId` names the window. That is the discriminator.

---

## Error taxonomy

`app/core/llm/errors.py`. Every provider failure lands in exactly one
class, and the class determines the policy.

| Error | Typical cause | Retry? | Fall back? |
|---|---|---|---|
| `LLMConfigurationError` | no API key | no | no |
| `LLMAuthenticationError` | 401 / 403 | no | no |
| `LLMInvalidRequestError` | 400 malformed request | no | no |
| `LLMQuotaExhaustedError` | daily quota, spent balance | **no** | yes |
| `LLMRateLimitError` | per-minute / per-second limit | **yes** | yes |
| `LLMServiceUnavailableError` | 503, overloaded | yes | yes |
| `LLMTimeoutError` | no response in `LLM_TIMEOUT` | yes | yes |
| `LLMConnectionError` | host unreachable | yes | yes |
| `LLMModelNotFoundError` | 404 unknown model | no | yes |
| `LLMProviderError` | anything unrecognised | no | yes |

OpenRouter's failures (Sprint 9H) map onto the same taxonomy, not a
parallel one:

- a spent prepaid balance is HTTP 402 → `LLMQuotaExhaustedError`.
  **Documented by OpenRouter, not reproduced live** — the configured
  key is a fresh free-tier key with $0 usage, so it has never actually
  run out;
- upstream free-model congestion is HTTP 429 with a bare
  `"Provider returned error"` body — **observed live** on 2026-08-18
  while selecting the fallback model (`z-ai/glm-5.2:free`,
  `google/gemma-4-31b-it:free`). No quota metadata at all, so it falls
  through `_classify_rate_limit`'s ambiguous default and becomes
  `LLMRateLimitError` (retryable), not `LLMQuotaExhaustedError`;
- some free models return HTTP 200 with an **empty completion** —
  observed live for `openai/gpt-oss-20b:free` and
  `nvidia/nemotron-nano-9b-v2:free`, plausibly the same
  hidden-reasoning-budget failure documented for Qwen 3.5
  (`settings.qwen_think`). Not a classification question at all — the
  gateway's existing empty-content guard in `_to_response` catches it
  before any error-classification logic runs.

The top three are **terminal**: our request or our configuration is
wrong, every provider would reject it identically, and trying more of
them turns one clear error into three confusing ones.

### Quota vs rate limit — the 429 fork

Both arrive as HTTP 429 `RESOURCE_EXHAUSTED`. `_classify_rate_limit()`
decides, in strict order:

1. a **short window** in the quota id (`PerMinute`, `PerSecond`,
   `PerHour`) → `LLMRateLimitError`. Checked first because it is the
   only unambiguous signal, and Google attaches its billing boilerplate
   to these too.
2. a **long window** (`PerDay`, `daily`,
   `generate_content_free_tier_requests`) → `LLMQuotaExhaustedError`.
3. a **spent balance** (`Insufficient Balance`, `insufficient_quota`,
   `credit balance`) → `LLMQuotaExhaustedError`. Money does not appear
   during a backoff.
4. anything else → `LLMRateLimitError`.

Step 4 is where ambiguity lands, deliberately. Guessing "quota
exhausted" would disable a working provider for an hour on a phrase
match; guessing "rate limited" costs at most a few bounded retries
before the fallback runs anyway. **The recoverable mistake wins.**

---

## Retry policy

One policy, in the gateway, and nowhere else. Nodes, services and
routers must not add their own — layered retries multiply, and three
levels of "just three attempts" is twenty-seven calls to a provider
that already said no.

```
LLM_MAX_RETRIES=2          # retries, not attempts: up to 3 calls
LLM_RETRY_BASE_DELAY=1.0
LLM_RETRY_MAX_DELAY=8.0
```

Exponential with **equal jitter**: half the window fixed, half random,
so attempt *n* waits within `[w/2, w]` for `w = min(base·2ⁿ⁻¹, max)` —
roughly 0.5–1s, then 1–2s, then 2–4s. Equal rather than full jitter
because full jitter can produce a near-zero delay, turning the first
retry into an immediate repeat of a call the provider just rejected.

---

## Fallback chain

```
PRIMARY   DEFAULT_LLM             gemini/gemini-flash-latest
FALLBACK  FALLBACK_LLM            groq/openai/gpt-oss-120b
SECOND    SECONDARY_FALLBACK_LLM  openrouter/nvidia/nemotron-3-super-120b-a12b:free
```

### DeepSeek → OpenRouter (Sprint 9H)

DeepSeek was Sprint 9G's configured second fallback and was never
usable: this account has zero balance, and every real request returned
`"Insufficient Balance"`. Sprint 9H replaced it with OpenRouter, chosen
the same evidence-first way the Groq fallback was — not a "hello" round
trip, but the real grounded-synthesis prompt, sent live, twice.

**Selection process, in full:**

1. `GET openrouter.ai/api/v1/models` → 413 models, 19 on the free tier
   with plausible chat/instruct shape.
2. Five candidates tried against the real synthesis prompt through
   `LLMGateway` → LiteLLM → `openrouter/<model>`:

   | Model | Result |
   |---|---|
   | `openai/gpt-oss-20b:free` | empty completion (no error, no content) |
   | `z-ai/glm-5.2:free` | HTTP 429, upstream congestion |
   | `nvidia/nemotron-nano-9b-v2:free` | empty completion on the real prompt |
   | `google/gemma-4-31b-it:free` | HTTP 429, upstream congestion |
   | `nvidia/nemotron-3-super-120b-a12b:free` | **qualified** |

3. The qualifying model was confirmed twice more: correctly grounded
   answers citing only supplied evidence, and a correct
   `insufficient_evidence` response to a question the evidence could
   not answer — the same two-sided test Groq's fallback was held to.

**DeepSeek's credential plumbing was not deleted.** `DEEPSEEK_API_KEY`,
`settings.deepseek_api_key`, and the gateway's DeepSeek credential
branch all remain — inert, since nothing in the active chain names
`deepseek/*` any more, but usable again with one `.env` change if the
account is ever funded. Deleting working code to mark something
"deprecated" was judged worse than leaving a clearly-labelled, unused
path in place; see the comments in `.env` and `settings.py` for the
same reasoning inline.

**Model catalogues move.** Sprint 9G's Groq fallback,
`llama-3.3-70b-versatile`, was live-verified working and had vanished
from Groq's catalogue hours later. Sprint 9H's startup validation (see
below) exists specifically to catch this earlier than a failed research
run does.

The chain stops at the first success — a working primary never causes
a fallback call.

Fallbacks whose API key is missing are **skipped when the chain is
built**, so an unconfigured optional provider costs nothing. The
primary is never skipped that way: a missing primary key raises
`LLMConfigurationError` immediately, because an optional provider
without a key is a choice and the primary without one is a mistake
nobody would otherwise notice.

### A fallback answer is held to the same standard

Only the generation provider changes. Same evidence, same prompt, same
`response_format`, same citation validation, same relevance gate. The
tests assert the prompts sent to primary and fallback are byte
identical.

This is why the fallback was chosen by sending it the **real synthesis
prompt** and parsing the result with the production parser — not by
asking it to reply "OK". A fallback that answers fluently but invents
citation ids is worse than no fallback, because the validator strips
the citations and the run looks partially grounded for no reason.

---

## Provider health (the breaker)

`app/core/llm/provider_health.py`. Passive: state is a by-product of
real traffic, never a probe.

| State | Meaning | Blocks calls? |
|---|---|---|
| `healthy` | a real call succeeded | no |
| `configured` | key present, never exercised | no |
| `quota_exhausted` | long-window quota spent | **yes**, 1 h |
| `rate_limited` | short-window limit hit | **yes**, 60 s |
| `unavailable` | unreachable, timing out, 5xx | **yes**, 60 s |
| `configuration_error` | credentials rejected, model gone | no |
| `not_configured` | no API key | n/a |

`configured` is not `healthy`. A key on disk is not evidence that
anything works, and reporting it as healthy would be a guess dressed
up as a measurement.

`configuration_error` deliberately does **not** block: a dead
credential is terminal for the call anyway, and blocking would silently
reroute later traffic to a different provider instead of surfacing the
misconfiguration.

**Keyed by model, not provider.** Gemini's limit is
`...PerProjectPerModel` and the refusal names the model
(`quotaDimensions.model = gemini-3.7-flash`). Keying by provider would
let one exhausted model disable every other model that provider
serves, and would break the cheapest mitigation available — a second
model on the same provider, with its own separate daily allowance.
This was caught by a failing test, not by inspection.

### Why the quota cooldown is one hour

The quota resets at midnight Pacific, which this process cannot compute
reliably. Rather than guess the wall-clock boundary, the entry ages out
after `LLM_QUOTA_COOLDOWN_SECONDS`. Worst case: one wasted request per
hour re-confirms the quota is still spent and re-arms the cooldown. The
alternative — no cooldown — disables the provider until a restart.

### Shared via Redis (Sprint 9H)

Sprint 9G's limitation was exactly what it looked like: state lived in
one process's memory, so a quota exhaustion the **worker** discovered
mid-research-run was invisible to the **API**'s `/health` until the API
made its own failing call. `RedisProviderHealthRegistry`
(`app/core/llm/provider_health.py`) fixes that by writing every
observation to Redis — the same broker `CELERY_BROKER_URL` already
points at, no new service — keyed by model, exactly as the in-process
registry was.

**Verified live, across the real container topology, not asserted from
code reading:** a script run inside `aikdap_worker` recorded a Gemini
quota exhaustion; `curl http://localhost:8001/health` against
`aikdap_backend` — a separate process, separate memory — showed
`gemini: quota_exhausted` 2.6 seconds later. `redis-cli GET
aikdap:llm:health:gemini/gemini-flash-latest` showed the literal stored
value; `redis-cli TTL` showed 3585 seconds remaining, matching the
one-hour quota cooldown.

**Redis key:** `aikdap:llm:health:<model>` — the full LiteLLM
`provider/model` id, unescaped (Redis keys tolerate `/` and `:` fine).

**Stored value** (JSON, `SETEX`'d with a TTL equal to the status's
cooldown):

```json
{
  "status": "quota_exhausted",
  "provider": "gemini",
  "model": "gemini/gemini-flash-latest",
  "updated_at": 1787036220.47,
  "error_type": "LLMQuotaExhaustedError",
  "error_message": "daily quota spent (cross-process test)"
}
```

Never a credential, a prompt, an answer, or a citation —
`error_message` is sourced from `LLMError`, whose constructor already
ran `scrub_secrets`, the same guarantee every log line in this package
relies on. A live scan of every key currently in Redis confirmed this.

**TTL is a circuit-breaker cooldown, not a claim about Google's actual
reset time.** `LLM_QUOTA_COOLDOWN_SECONDS` (default 3600) still has
nothing to do with midnight Pacific — see above. A `healthy` or
`configured` entry, which has no cooldown of its own, still gets a
hygiene TTL (`LLM_HEALTH_STATE_TTL_SECONDS`, default 24h) so no key in
Redis is ever permanent.

**Redis, synchronously, on purpose.** Every provider-health method
(`record_success`, `record_failure`, `status`, `is_blocked`) is called
as an ordinary synchronous function from inside `LLMGateway`'s async
methods — the same calling convention Sprint 9G's in-process registry
always used. Rather than convert that whole call chain to `async def`
(the gateway, `/health`, and every test that constructs a registry),
this class uses the plain synchronous `redis` client, bounded by a
200ms timeout (`LLM_HEALTH_REDIS_TIMEOUT`) so a dead Redis fails fast
rather than blocking the event loop for long. The trade is real and
accepted, not hidden: a local Redis round trip measured well under 1ms
warm in this deployment (25ms on the very first call, which builds the
connection); see Performance below for the actual numbers behind
`/health`'s total latency, which is dominated by something else
entirely.

**Redis unreachable → in-process fallback, not a new outage.** Every
Redis operation is wrapped in `try/except`; on failure it logs
(`llm_provider_health_redis_degraded`, never the connection string) and
falls through to a private `ProviderHealthRegistry` instance that
`RedisProviderHealthRegistry` keeps for exactly this purpose. Writes go
to both unconditionally, so the local fallback is warm the instant
Redis becomes unavailable rather than starting empty; reads prefer
Redis and only consult local on a genuine Redis error, not on an empty
(but reachable) result.

---

## Startup model validation (Sprint 9H)

`app/core/llm/startup_validation.py`, run once from the FastAPI
lifespan. For each configured chain entry — primary, fallback,
secondary fallback — it asks the provider's own model-listing endpoint
whether the configured model still exists, and logs the result
(`llm_startup_validation`, one line per entry, plus a
`llm_startup_validation_summary`). It never raises and never blocks
startup: a problem it finds is visible in the logs and in `/health`,
which is the point, not a reason to refuse to boot.

This exists because of a real incident: Sprint 9G's fallback model,
`groq/llama-3.3-70b-versatile`, was live-verified working and had
vanished from Groq's catalogue by the time a research run needed it
hours later. A model-list call at startup — metadata only, never a
completion, the same kind of cheap probe `check_reranker_health` already
uses for the reranker — is the mechanism that would have caught it
first.

Confirmed live at container start, against the real deployed
configuration: all three configured models (`gemini-flash-latest`,
`groq/openai/gpt-oss-120b`, `openrouter/nvidia/nemotron-3-super-120b-a12b:free`)
reported `available` against their real, current catalogues.

---

## `GET /health`

Extended from a two-line liveness handler into a real report.
Unauthenticated, always HTTP 200, and **free**.

| Component | How it is checked |
|---|---|
| postgres | `SELECT 1` on the request's own pool |
| redis | `PING` on the broker connection |
| worker | Celery control ping, 2 s deadline |
| reranker | `GET /health` on llama-server — loads nothing, scores nothing |
| LLM providers (gemini, groq, openrouter) | **nothing is called**; read from the Redis-backed breaker |

Costing nothing is a hard requirement, not an optimisation. Anyone can
poll this endpoint; if it generated, a monitor on a 30-second interval
would exhaust a 20-request daily quota before breakfast. Two tests
assert it directly.

Always 200, even when `unhealthy`: encoding the state in the HTTP
status as well would mean a liveness probe restarting a healthy
container because a third-party provider ran out of free quota.

`unhealthy` is reserved for losing Postgres or Redis. A dead reranker,
a spent quota, or an unconfigured optional fallback are all `degraded`
— the platform is still serving projects, assets, the knowledge base
and search.

---

## Operator runbook

**`gemini: quota_exhausted`** — expected on the free tier after 20
requests. Traffic is already going to Groq. `meta.retry_after_seconds`
counts down to the next attempt. No action needed unless Groq is also
degraded.

**`groq: configuration_error` with `LLMModelNotFoundError`** — Groq
removed the configured model. This happened during Sprint 9G:
`llama-3.3-70b-versatile` was verified working and vanished from the
catalogue hours later. Startup validation (above) now catches this on
the next boot; to fix immediately, re-list
`https://api.groq.com/openai/v1/models`, pick a replacement, and
validate it against the real synthesis prompt before setting
`FALLBACK_LLM`.

**`openrouter: configuration_error` with `LLMModelNotFoundError`** —
same failure mode as Groq's, on OpenRouter's catalogue instead. Re-list
`https://openrouter.ai/api/v1/models` and re-validate against the real
synthesis prompt (see the DeepSeek → OpenRouter section above for the
exact method) before changing `SECONDARY_FALLBACK_LLM`.

**`openrouter: quota_exhausted` with "Insufficient credits" (HTTP
402)** — the OpenRouter account has spent its balance. Documented
OpenRouter behaviour; this deployment has not triggered it live (the
key has $0 usage recorded). The gateway classifies it as quota
exhaustion regardless, so it cannot abort a chain that still has Groq
or Gemini in it.

**`deepseek: quota_exhausted` with "Insufficient Balance"** — DeepSeek
is no longer in the active chain (see above), so this can only appear
if `SECONDARY_FALLBACK_LLM` is manually pointed back at
`deepseek/...`. The account has no credit. The key is fine. Note
DeepSeek reports this as HTTP 400; the gateway classifies it as quota
exhaustion so it cannot abort a chain that still has working providers.

**`reranker: unavailable`** — the host llama-server is down. Nothing
supervises it. Run `scripts/reranker.ps1 start`. Retrieval keeps
working meanwhile, degraded to stage-1 order with
`reranking_status=unavailable` and no fabricated scores.

**All providers blocked** — the gateway raises the *original* reason
(e.g. `LLMQuotaExhaustedError`), not a generic wrapper, and the message
says the provider was not called. No answer is ever invented.

**`/health` on the API shows a provider as `configured` when the worker
already knows it is `quota_exhausted`** — should not happen after
Sprint 9H (this is the exact scenario the Redis-backed registry fixes),
but if it does: check the API container can actually reach Redis
(`llm_provider_health_redis_degraded` in its logs means it can't, and
has silently fallen back to its own empty local state).

---

## Performance (Sprint 9H)

Measured live against this deployment:

| Operation | Latency |
|---|---|
| Redis provider-health write (`record_success`/`record_failure`) | 25ms first call (builds the client), <1ms warm |
| Redis provider-health read (`status`) | 0.25ms |
| `/health` — postgres | 13–19ms |
| `/health` — redis | 27–46ms |
| `/health` — reranker | 13–18ms |
| `/health` — provider health (all 3, Redis-backed) | 1.4–1.8ms |
| `/health` — **worker (Celery control ping)** | **2.4–2.6s** |
| `/health` total | ~2.1s, dominated entirely by the worker check |

The worker check dominates `/health`'s total latency, and Sprint 9H
did not cause it — isolating each subcheck (above) shows the
Redis-backed provider-health work costs under 2ms, while
`_check_worker`'s `celery_app.control.ping()` consistently costs
2.4–2.6s in this environment, unchanged Sprint 9G code. This looks like
Celery's broadcast ping waiting out its full collection window
(`WORKER_PING_TIMEOUT_SECONDS = 2.0`) rather than returning as soon as
the one worker replies — a known characteristic of Celery's broadcast
`control.ping`, not confirmed against a Sprint 9G baseline measurement
(none was recorded with this level of per-component detail). Flagged
here rather than silently reported as a "Sprint 9H regression" it is
not, and rather than silently omitted; see Sprint 9I recommendations.

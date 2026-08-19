# AIKDAP Frontend Foundation — Design Spec

Sprint 9K. Status: approved pending final review.

## 1. Purpose

Build the initial production-quality frontend for AIKDAP inside the
existing (currently empty) `frontend/` skeleton, wired to the real,
already-hardened backend (296 passing tests as of Sprint 9J). The
frontend is a pure client of the existing FastAPI backend: no new
backend logic, no duplicated business rules (grounding, reranking,
relevance, provider fallback all stay server-side), no fabricated
data.

## 2. Existing state

`frontend/` was committed once, in the initial project commit, and
never touched since — `package.json` and `Dockerfile` are both empty.
The folder tree itself is real prior intent and is honored rather than
replaced:

```
src/app/  src/components/  src/features/{assets,auth,business-analytics,
  command-center,knowledge-base,projects,reports,research,
  workflow-timeline}/  src/hooks/  src/layouts/  src/lib/  src/pages/
  src/services/  src/store/  src/types/
```

Feature-based, mirroring the backend's own `app/modules/*` convention.
No CI, no `docker-compose.yml` entry, and no other repo convention
constrains the choice further.

## 3. Stack

React 18, TypeScript, Vite, Tailwind CSS, shadcn/ui (installed via its
own CLI — generates `src/components/ui/*`, `components.json`, Tailwind
theme tokens), react-router-dom v6, TanStack Query, Zustand (auth
state only), openapi-typescript (generates `src/types/api.d.ts` from
the live `/openapi.json`), Vitest + React Testing Library, npm.

No Redux, no GraphQL, no generated API *client* (only generated
*types* — hand-written fetch functions stay explicit and readable per
Phase 6's "one centralized client" rule).

## 4. Structure

Only the folders Sprint 9K actually uses are filled in; the rest of
the pre-planned skeleton (`business-analytics`, `reports`,
`workflow-timeline`, `knowledge-base` as distinct from `research`)
stays empty — no backend exists for them yet, so no fake pages get
built.

```
frontend/
├── src/
│   ├── services/
│   │   ├── client.ts        # fetch wrapper: base URL, auth header,
│   │   │                     # 401->refresh->retry-once->logout,
│   │   │                     # typed JSON parse, ApiError normalization
│   │   ├── auth.ts
│   │   ├── projects.ts
│   │   ├── assets.ts
│   │   ├── research.ts
│   │   └── health.ts
│   ├── store/
│   │   └── auth-store.ts    # Zustand: {accessToken, refreshToken, user}
│   ├── features/
│   │   ├── auth/            # LoginForm
│   │   ├── command-center/  # Dashboard cards
│   │   ├── projects/        # ProjectCard, CreateProjectDialog
│   │   ├── assets/          # UploadDropzone, DocumentCard, AiProfilePanel
│   │   └── research/        # ResearchPrompt, ResearchProgress,
│   │                         # ResearchResult, CitationList, EvidencePanel
│   ├── pages/
│   │   ├── Login.tsx
│   │   ├── Dashboard.tsx
│   │   ├── Projects.tsx
│   │   ├── ProjectDetail.tsx
│   │   ├── Research.tsx
│   │   └── SystemHealth.tsx
│   ├── layouts/
│   │   └── AppShell.tsx     # sidebar + topbar, Phase 4 layout
│   ├── hooks/
│   │   ├── useAuth.ts
│   │   └── usePolling.ts    # thin wrapper: TanStack Query refetchInterval
│   ├── lib/
│   │   ├── api-error.ts     # ApiError parsing/formatting (Phase 31)
│   │   └── format.ts
│   ├── types/
│   │   └── api.d.ts         # generated, not hand-edited
│   ├── App.tsx               # router
│   └── main.tsx
├── .env.example               # VITE_API_BASE_URL=http://localhost:8001
├── package.json
├── vite.config.ts
├── tailwind.config.ts
└── Dockerfile                 # filled in; NOT added to docker-compose.yml
```

## 5. API integration

Confirmed against the real backend (not guessed):

- Auth: `POST /api/v1/auth/register {email,password,full_name?}`,
  `POST /api/v1/auth/login {email,password} -> {access_token,
  refresh_token, token_type}`, `POST /api/v1/auth/refresh
  {refresh_token}`, `GET /api/v1/auth/me -> UserRead`. Access token
  TTL 30 min, refresh TTL 7 days (`settings.py`) — long enough that a
  silent-refresh-on-401 is worth building for a seminar-length session.
- Projects: `POST/GET /api/v1/projects`, `GET/PATCH/DELETE
  /api/v1/projects/{id}`.
- Assets: `POST /api/v1/assets/upload` (multipart, fields `project_id`
  + `file`), `GET /api/v1/assets/{id}`, `POST
  /api/v1/assets/{id}/process`, `GET /api/v1/assets?project_id=`.
- Research: `POST /api/v1/research/run {project_id, query,
  include_web?}` (202, returns `run_id`), `GET
  /api/v1/research/runs/{id}` (poll this for status/steps/citations),
  `GET /api/v1/research/runs?project_id=`.
- Health: `GET /health` (no version prefix, unauthenticated).

`services/client.ts` is the only file that calls `fetch`. Every other
service module returns typed data or throws a typed `ApiError`.

## 6. Auth flow

Zustand store holds `{accessToken, refreshToken, user}`, persisted to
`localStorage` under one key (tokens only, never provider credentials
— enforced by the Phase 33/43 grep audit before calling this done).
`client.ts` attaches `Authorization: Bearer <accessToken>`; on a 401 it
attempts one `refresh` call, retries the original request once on
success, and clears the store + redirects to `/login` on failure. A
route guard component wraps every page except `/login`.

## 7. Routes

`/login` (public) · `/` Dashboard · `/projects` · `/projects/:id` ·
`/research` and `/research/:runId` · `/health`. No route is created
for a capability the backend doesn't expose.

## 8. Research UX (the seminar centerpiece)

Submit → `run_id` → TanStack Query polls `GET
/research/runs/{run_id}` on a configurable interval (default 1.5s,
capped, stops polling once `status` is `completed`/`failed`) →
`ResearchProgress` renders the real `steps[]` (status
completed/running/skipped/failed, never inferred) → on completion,
`ResearchResult` renders `grounding_status` verbatim (`grounded` /
`partially_grounded` / `insufficient_evidence`), the real
`final_answer`, and `CitationList`/`EvidencePanel` render exactly the
fields the API returns (title, source, snippet, `retrieval_rank` vs
`rerank_score` kept visually distinct, `simulated` flagged as
"Simulated evidence", never called a probability). Zero client-side
computation of any of these values.

## 9. Testing

Vitest + RTL: login render, protected-route redirect, project
creation, upload states, research submission + polling transitions,
grounded result render, insufficient-evidence render, API error
parsing, logout. `services/*` and `store/` get direct unit coverage;
pages get one smoke render each rather than exhaustive interaction
tests.

## 10. Explicitly out of scope

Business analytics, reports, workflow timeline, a knowledge-base UI
distinct from what research already surfaces, Docker Compose
integration, any new backend endpoint or schema change (a genuine
integration blocker would be raised and confirmed before touching the
backend, per the sprint's Core Rule).

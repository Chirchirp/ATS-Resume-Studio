# Routes and Runtime Contract

## Current processes

| Client | Current command | Current local address |
|---|---|---|
| Streamlit studio | `streamlit run app.py` | `http://127.0.0.1:8501/` |
| Platform API/studio | `uvicorn platform_api.main:create_app --factory` | `http://127.0.0.1:8000/` |
| External job worker | `python -m platform_api.worker` | No public listener |

The Cloudflare deployment may change how these processes are supervised, but not
their public behavior.

## Streamlit network contract

| Route family | Purpose |
|---|---|
| `/` | Studio document and Streamlit bootstrap |
| `/_stcore/health` | Streamlit readiness/health |
| `/_stcore/stream` | Stateful Streamlit WebSocket |
| `/_stcore/*` | Streamlit runtime assets and endpoints |

Cloudflare must preserve WebSocket upgrades, cookies, query strings, response
streaming, generated downloads, and session affinity. Interactive routes must not
be cached.

## Platform routes

| Method | Route | Authentication |
|---|---|---|
| GET | `/` | No; redirects to `/studio` |
| GET | `/studio` | No |
| GET | `/assets/*` | No |
| GET | `/health` | No |
| GET | `/api/docs` | No |
| POST | `/v1/auth/register` | No |
| POST | `/v1/auth/login` | No |
| GET | `/v1/me` | Bearer |
| GET/PUT | `/v1/profile` | Bearer |
| GET/POST | `/v1/applications` | Bearer |
| GET/PUT | `/v1/applications/{application_id}` | Bearer |
| GET/POST | `/v1/applications/{application_id}/versions` | Bearer |
| GET | `/v1/versions/{version_id}` | Bearer |
| POST | `/v1/jobs/alignment` | Bearer |
| POST | `/v1/jobs/truth-audit` | Bearer |
| GET | `/v1/jobs/{job_id}` | Bearer |
| PUT | `/v1/privacy/retention` | Bearer |
| GET | `/v1/privacy/export` | Bearer |
| DELETE | `/v1/privacy/account` | Bearer plus password confirmation |

## Environment contract

No secret values belong in source control or container images.

| Variable | Required by | Purpose |
|---|---|---|
| `ATS_AUTH_SECRET` | Platform API | Signs authentication tokens; minimum 32 characters |
| `ATS_DATA_SECRET` | Platform API/worker | Encrypts sensitive platform records; minimum 32 characters |
| `ATS_PLATFORM_DB` | Platform API/worker | Current SQLite database path |
| `ATS_ALLOWED_ORIGINS` | Platform API | Exact allowed browser origins |
| `ATS_INLINE_JOBS` | Platform API | Inline versus external worker execution |
| `ATS_JOB_WORKERS` | Platform API | Inline worker count |
| `GROQ_API_KEY` | Streamlit/provider gateway | Optional server-side Groq key |
| `GEMINI_API_KEY` | Streamlit/provider gateway | Optional server-side Gemini key |
| `OPENROUTER_API_KEY` | Streamlit/provider gateway | Optional server-side OpenRouter key |

The Streamlit client also reads the three provider keys from
`.streamlit/secrets.toml`, and accepts session-only keys through the sidebar.

## Current state and storage

| State | Current location | Required migration behavior |
|---|---|---|
| Streamlit inputs and generated outputs | Server-side `st.session_state` | Session isolation and WebSocket continuity |
| AI response cache and token usage | `st.session_state` | Same per-session semantics |
| Usage metadata | `usage_logs.csv` | Preserve metadata-only logging without resume/JD content |
| Platform data | SQLite at `ATS_PLATFORM_DB` | Durable across restarts and deployments |
| Sensitive documents | Encrypted before SQLite storage | Remain encrypted at rest |
| Background jobs | SQLite queue plus thread/external worker | Recover after process replacement |
| Uploaded PDF | Request/session memory | Parse successfully without permanent retention |
| Generated DOCX/Markdown | In-memory download bytes | Download successfully without permanent retention |

## Intended Cloudflare hostname

The Phase 0 working target is:

`https://resume.pharaohchirchir.com`

The final hostname is a cutover configuration value and does not require changes
to the product UI.

# ATS Resume Studio

An evidence-grounded resume analyzer and optimizer with two supported clients:

- the original Streamlit studio for the complete AI workflow;
- an authenticated FastAPI web platform for persistent applications, document
  versions, background analysis, and privacy controls.

It supports Groq, Google Gemini, and OpenRouter with controlled fallback.

## Folder Structure

```
ats_resume_studio/
├── app.py                    ← Entry point (run this)
├── requirements.txt
├── platform_api/
│   ├── main.py                 ← Authenticated API and browser editor
│   ├── storage.py              ← Encrypted, ownership-scoped persistence
│   ├── security.py             ← Password hashing, tokens, encryption
│   ├── jobs.py / worker.py     ← Inline or external background jobs
│   ├── migrations/             ← Versioned database schema
│   └── static/                 ← Responsive browser document studio
├── config/
│   └── settings.py           ← API key & model config (session-based)
├── components/
│   ├── sidebar.py            ← Sidebar with API key input
│   ├── tab_analyze.py        ← Analyze tab
│   ├── tab_evidence.py       ← Evidence and truth center
│   ├── tab_workspace.py      ← Positioning, versions, interviews, outcomes
│   └── tab_premium.py        ← Premium Solutions tab
├── prompts/
│   └── templates.py          ← All AI prompt templates
└── utils/
    ├── ai_client.py          ← Groq, Gemini, and OpenRouter gateway
    ├── ai_runtime.py         ← Task routing, budgets, fallback, telemetry
    ├── ats_engine.py         ← Deterministic alignment scoring
    ├── evidence_engine.py    ← Ledger, coverage matrix, clarification, truth audit
    ├── domain_profiles.py    ← Universal profiles and analytics specialization
    ├── workspace_engine.py   ← Strategies, versions, objections, comparison
    ├── docx_builder.py       ← DOCX export
    ├── logger.py             ← CSV usage logging
    └── text_processing.py    ← PDF extract, keyword match, sanitize
```

## Setup

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Run the app
streamlit run app.py
```

## Free deployment

The zero-budget production path keeps the complete application on Streamlit
Community Cloud and uses a Cloudflare Worker with Static Assets for the branded
`resume.pharaohchirchir.com` shell:

1. Deploy `app.py` from GitHub to Streamlit Community Cloud with Python 3.11.
2. Add provider keys through Streamlit Advanced settings, never Git.
3. Connect the repository to the `modern-resume-ai-agent` Cloudflare Worker and set
   `STREAMLIT_APP_URL` to the public `*.streamlit.app` URL.
4. Attach `resume.pharaohchirchir.com` to the Worker.

See [the Streamlit deployment guide](docs/deployment/STREAMLIT_COMMUNITY_CLOUD.md)
and [the phased Cloudflare plan](docs/deployment/CLOUDFLARE_PHASED_PLAN.md).

## Phase 4 platform

The platform API is separate from the Streamlit process. It provides authenticated
profiles, application workspaces, immutable document versions, asynchronous ATS
analysis and truth audits, account export, configurable result retention, and
verified account deletion.

### Local startup

Generate two different secrets. Do not reuse an AI provider key for either value:

```powershell
python -c "import secrets; print(secrets.token_urlsafe(48))"
python -c "import secrets; print(secrets.token_urlsafe(48))"

$env:ATS_AUTH_SECRET="<first generated value>"
$env:ATS_DATA_SECRET="<second generated value>"
$env:ATS_PLATFORM_DB="data/platform.db"

uvicorn platform_api.main:create_app --factory --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000/studio`. The service refuses to start when either
secret is missing or shorter than 32 characters.

`ATS_AUTH_SECRET` signs short-lived login tokens. `ATS_DATA_SECRET` encrypts
resume text, job descriptions, document versions, job inputs, and job results at
rest. Back up the data secret securely: encrypted records cannot be recovered if
it is lost.

### Durable worker mode

Inline jobs are convenient for local use. For a service process and worker that
can restart independently, configure the same database and data secret in both:

```powershell
$env:ATS_INLINE_JOBS="false"
uvicorn platform_api.main:create_app --factory --host 127.0.0.1 --port 8000
```

In a second terminal:

```powershell
$env:ATS_DATA_SECRET="<same data secret>"
$env:ATS_PLATFORM_DB="data/platform.db"
python -m platform_api.worker
```

SQLite is an intentional single-host starting point. Use one shared persistent
volume and one worker process. Before horizontal or multi-region scaling, replace
the repository/queue implementation with a managed transactional database and
queue; the API contracts can remain unchanged.

### Production checklist

- Put TLS and a trusted reverse proxy in front of the service.
- Store secrets in the host's secret manager, never in source control.
- Set `ATS_ALLOWED_ORIGINS` to the exact deployed web origins.
- Put registration behind the intended access policy before a public launch.
- Back up both the database and encryption secret, and test restoration.
- Run the external worker mode for restart-safe queued work.
- Add provider-specific data processing terms before enabling AI generation for
  other users.

## Provider configuration

Select a provider and enter its key in the sidebar, or copy
`.streamlit/secrets.toml.example` to `.streamlit/secrets.toml` and add one or
more keys. The real secrets file is ignored by Git.

- `GROQ_API_KEY`
- `GEMINI_API_KEY`
- `OPENROUTER_API_KEY`

Application code never writes keys to disk.

## Features

| Feature | Description |
|---|---|
| 🔍 Job Alignment Score | Explainable scoring across requirements, skills, responsibilities, experience, achievements, parseability, and placement |
| 🧠 Expert Analysis | AI strengths, weaknesses, rewrites, one-minute pitch |
| ⚡ Grounded Rewrites | Resume bullet rewrites tied to source evidence; missing metrics remain marked for verification |
| 📊 Alignment Breakdown | Transparent dimension scores and requirement gaps; does not claim to reproduce a specific ATS vendor |
| 🎯 Recruiter Feedback | Scored mock recruiter review with rubric |
| 📄 Resume Generation | Full ATS-optimized resume from your existing one |
| ✉️ Cover Letter | Tone-matched cover letter |
| 💬 Custom Query | Ask anything about your resume vs the JD |
| 📥 DOCX Export | Formatted Word document download |
| 🔐 Evidence Ledger | Stable evidence IDs and requirement-to-evidence coverage |
| ❓ Clarification Interview | Targeted questions for unresolved facts and outcomes |
| 🛡️ Truth Audit | Blocks downloads when unsupported metrics, skills, or credentials are detected |
| 🔀 Provider Routing | Groq, Gemini, OpenRouter, model discovery, and retryable fallback |
| 🪙 Token Controls | Task limits, response caching, session budgets, and usage telemetry |
| 🎯 Positioning Studio | Direct-fit, business-impact, and transferable-growth strategies |
| 🧾 Version & Impact Workspace | Deduplicated resume versions and explainable change reports |
| 🗣️ Interview Preparation | Recruiter objections and evidence-linked interview answer plans |
| 🕶️ Blind Comparison | Evaluate original and optimized versions without identity bias |
| 📈 Outcome Tracking | Associate application progress with the resume version used |
| 🌐 Universal Domains | Career-specific guidance with an enhanced Data Analytics profile and neutral fallback |
| 🩺 Resume Quality Review | Resume-first structure, grammar, chronology, possible gap, and ATS-readability feedback before any JD comparison |
| 👤 Authenticated Profiles | Persistent user-owned profiles with password hashing and expiring signed sessions |
| 🗂️ Application Workspaces | Server-side application records with strict ownership checks |
| 🕰️ Document History | Immutable resume and job-description versions |
| ⚙️ Background Analysis | Durable queued alignment and truth-audit jobs |
| 📝 Browser Studio | Responsive editor, ATS score breakdown, gaps, and version history |
| 🔒 Privacy Center | Encrypted content, export, retention controls, and verified account deletion |

## Data and privacy

Streamlit session data is normally held in the application server process, not only
in the browser. Resume and job-description text are sent to the selected provider
when an AI feature is used. The local `usage_logs.csv` contains action metadata, not resume or job-
description content. Review the retention and privacy settings of your hosting
environment and model provider before processing sensitive personal information.

The Phase 4 platform stores sensitive document content encrypted at rest. API
responses are scoped to the authenticated owner, and queued job inputs are not
echoed to clients. Users can export all stored account data, set automatic
completed-job retention from 1 to 365 days, and permanently delete their account
after re-entering their password. Audit entries contain action metadata, not
resume or job-description bodies.

## Default provider models

- Groq: `openai/gpt-oss-120b` (default quality),
  `qwen/qwen3.6-27b` (preview reasoning), and
  `openai/gpt-oss-20b` (fast/economical)
- Gemini: `gemini-2.5-flash`, `gemini-2.5-flash-lite`
- OpenRouter: `openrouter/free`

Use **Discover active models** in the sidebar or enter a custom provider model ID
to avoid coupling deployments to a stale static catalog.

The sidebar exposes model-compatible reasoning controls. GPT OSS supports
`low`, `medium`, and `high`; Qwen 3.6 supports `none` and `default`. Reasoning
content is hidden from generated documents.

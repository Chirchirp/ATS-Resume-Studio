# Frozen Feature Matrix

Status meanings:

- **Frozen**: must remain visually and functionally equivalent.
- **Runtime**: hosting may change, but the user-visible contract must remain.
- **Variable output**: validate structure and grounding rather than exact prose.

## Streamlit studio

| Area | Frozen contract | Status |
|---|---|---|
| Global shell | Header, badges, footer, five tabs, expanded/collapsed sidebar | Frozen |
| Sidebar providers | Groq, Google Gemini, OpenRouter, API-key input and model discovery | Frozen |
| Sidebar models | Curated model list, custom model ID, reasoning controls | Frozen |
| Routing | Task-based model routing and fallback provider/model | Frozen |
| Preferences | Target field, auto-inference, cover-letter tone, achievement count | Frozen |
| Token controls | Session token budget, input/output/cache telemetry, reset | Frozen |
| Analyze input | PDF upload, pasted resume, optional/pasted job description | Frozen |
| Resume Quality Review | Structure, grammar signals, dates, gaps, ATS readability | Frozen |
| Live Match Preview | Deterministic score, confidence, terms, provenance and gaps | Frozen |
| Expert Analysis | Strengths, weaknesses, rewrites and positioning | Variable output |
| Quick Fix Bullets | Resume-grounded, JD-linked bullet rewrites | Variable output |
| Evidence & Truth | Evidence ledger, coverage matrix, clarifications, truth audit | Frozen |
| Application Workspace | Positioning, versions, interviews, comparison and outcomes | Frozen |
| Premium tools | ATS match, recruiter feedback and custom question | Frozen |
| Resume generation | Evidence-grounded resume, self-review, claim validation | Variable output |
| Cover letter | Tone selection, grounded generation and validation | Variable output |
| Downloads | DOCX and Markdown generation, truth-audit gating | Frozen |
| DOCX verification | Round-trip extraction and parseability scoring | Frozen |
| Help | Provider, workflow, truth and privacy guidance | Frozen |

## Platform studio and API

| Area | Frozen contract | Status |
|---|---|---|
| Authentication | Registration, login, signed expiring bearer session, sign out | Frozen |
| Profiles | User-owned profile and encrypted master resume | Frozen |
| Applications | Create, list, read and update application workspaces | Frozen |
| Versions | Immutable resume and job-description versions | Frozen |
| Jobs | Alignment and truth-audit job submission and status polling | Runtime |
| Browser editor | Resume/JD editor, status, score panel, gaps and versions | Frozen |
| Privacy | Retention update, account export and verified account deletion | Frozen |
| Ownership | Cross-user access is denied | Frozen |
| Encryption | Sensitive content remains encrypted at rest | Runtime |
| Audit | Metadata-only audit events | Runtime |
| Static assets | `/studio` and `/assets/*` render without missing resources | Frozen |

## External dependencies

| Dependency | Contract |
|---|---|
| Groq | HTTPS model discovery and generation using supplied key |
| Google Gemini | HTTPS generation using supplied key |
| OpenRouter | HTTPS model discovery/generation using supplied key |
| Streamlit WebSocket | Session remains connected and isolated per browser session |
| Filesystem | PDF extraction and generated downloads work during the request/session |
| Persistent data | Platform users, applications, versions and jobs survive restarts |

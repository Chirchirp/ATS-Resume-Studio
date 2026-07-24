# Phase 0 Migration Baseline

This directory freezes the pre-migration behavior of ATS Resume Studio. It is the
reference contract for the Cloudflare migration: later phases may change hosting
and persistence, but must not silently change the user interface, routes, outputs,
or workflows recorded here.

## Capture record

- Captured: `2026-07-24T20:49:58+03:00`
- Host OS: Windows 11 (`Microsoft Windows NT 10.0.26100.0`)
- Python: `3.11.9`
- Streamlit: `1.60.0`
- FastAPI: `0.139.2`
- Uvicorn: `0.30.6`
- Automated baseline: `58 passed` in `10.53s`
- Baseline contract after adding the migration test: `60 passed`
- Streamlit health: `ok`
- Platform health: `ok` (`ats-platform`, version `1.0.0`)
- Repository metadata: no `.git` directory was present, so
  `source-manifest.sha256` is the immutable source fingerprint.

The only observed test warning is the existing `pytest-asyncio` warning about
`asyncio_default_fixture_loop_scope`. It is not a functional failure.

## Frozen behavior

- The Streamlit client remains the complete AI workflow.
- The FastAPI browser studio remains the authenticated, persistent workspace.
- Provider choices, model controls, reasoning controls, fallback routing,
  session token controls, and user-entered API keys remain available.
- Resume Quality Review remains the first quick action.
- ATS alignment remains deterministic and explainable.
- Generated claims remain evidence-grounded and subject to the truth audit.
- Existing PDF input and DOCX/Markdown output behavior remains in scope.
- The current dark left sidebar, blue application header, typography, navigation,
  and responsive behavior are the visual reference.

See:

- [feature-matrix.md](feature-matrix.md) for feature scope.
- [routes-and-runtime.md](routes-and-runtime.md) for deployment contracts.
- [acceptance-matrix.md](acceptance-matrix.md) for Cloudflare parity gates.
- [expected-results.json](expected-results.json) for deterministic sample results.
- [source-manifest.sha256](source-manifest.sha256) for pre-migration source hashes.
- [screenshots.sha256](screenshots.sha256) for screenshot hashes and dimensions.

## Reproducible fixtures

The sample data is synthetic and contains no real candidate information:

- `fixtures/sample_resume.txt`
- `fixtures/sample_job_description.txt`

With the captured source, the expected core results are:

| Result | Baseline |
|---|---:|
| Job Alignment Score | 52 |
| Confidence | High |
| Matched terms | 10 |
| Required requirement gaps | 7 |
| Parsed roles | 2 |
| Parsed role bullets | 7 |
| Declared skills | 9 |
| Resume Quality Score | 95 |
| Resume Quality Grade | Excellent |
| Extracted words | 150 |

Run the full contract with:

```powershell
python -m pytest -q
```

## Screenshot inventory

All screenshots are stored in `screenshots/`.

| File | Reference state |
|---|---|
| `streamlit-analyze-desktop-viewport.png` | Analyze page and expanded left sidebar |
| `streamlit-analyze-desktop.png` | Analyze full-page reference |
| `streamlit-evidence-desktop-viewport.png` | Evidence & Truth empty state |
| `streamlit-workspace-desktop-viewport.png` | Application Workspace empty state |
| `streamlit-premium-desktop-viewport.png` | Premium Solutions initial state |
| `streamlit-how-it-works-desktop-viewport.png` | How It Works page |
| `streamlit-analyze-mobile-390x844.png` | Mobile layout with sidebar open |
| `streamlit-analyze-mobile-collapsed-390x844.png` | Mobile layout with sidebar closed |
| `streamlit-analyze-sample-match-desktop.png` | Deterministic 52% sample alignment |
| `streamlit-resume-quality-sample-desktop.png` | Deterministic 95/100 quality review |
| `platform-sign-in-desktop-viewport.png` | Platform sign-in page |
| `platform-workspace-desktop-viewport.png` | Authenticated platform workspace |
| `platform-workspace-mobile-390x844.png` | Authenticated mobile platform workspace |

## Baseline boundaries

Live AI text is intentionally not frozen byte-for-byte because provider model
outputs can change independently of this codebase. AI migration parity will
instead require:

- the same prompt inputs and evidence payloads;
- the same provider/model selection and reasoning settings;
- equivalent truth-audit and validation behavior;
- valid, non-empty responses;
- no unsupported claims;
- token telemetry and failure handling.

No production API key, user resume, authentication secret, or platform database is
stored in this baseline.

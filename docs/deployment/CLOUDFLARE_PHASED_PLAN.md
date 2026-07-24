# Streamlit + Cloudflare phased rollout

Yes, this migration should be phased. Streamlit Community Cloud remains the
Python application host; Cloudflare Pages provides the branded subdomain and
wake-up shell. This avoids rewriting the working application while the budget is
zero.

## Phase 0 — Freeze and baseline

Status: complete.

- Preserve the feature matrix, reference fixtures, expected ATS results, source
  hashes, and desktop/mobile screenshots in `docs/baseline`.
- Keep `app.py` as the functional reference implementation.

Exit gate: baseline tests pass and the existing Streamlit interface is captured.

## Phase 1 — Streamlit deployment readiness

Status: implemented locally; GitHub and Community Cloud deployment remain.

- Pin the tested Python and direct dependency versions.
- Add Streamlit production configuration.
- keep real provider keys out of Git.
- Document deployment coordinates, secrets, and smoke tests.

Exit gate: clean GitHub checkout installs successfully, tests pass, and
`streamlit run app.py` returns a healthy status.

## Phase 2 — Streamlit staging deployment

- Push the repository to GitHub.
- Deploy `app.py` on Streamlit Community Cloud using Python 3.11.
- Configure provider secrets in Streamlit Advanced settings.
- Choose and record the stable public `*.streamlit.app` URL.
- Run the full smoke-test checklist directly on the Streamlit URL.

Exit gate: all current features work directly on the public Streamlit URL,
including AI calls and DOCX downloads.

## Phase 3 — Cloudflare Pages wrapper

Status: source implementation complete; final URL and deployment remain.

- Create a Cloudflare Pages project from the same GitHub repository.
- Set root directory to `cloudflare-wrapper`.
- Set build command to `npm run build` and output directory to `dist`.
- Set `STREAMLIT_APP_URL` to the Phase 2 public URL.
- Deploy the wake-up animation and embedded Streamlit app.
- Add the custom domain `resume.pharaohchirchir.com`.

Exit gate: the Cloudflare URL shows the requested cold-boot copy and then exposes
the complete Streamlit app without navigation or styling loss.

## Phase 4 — Parity and resilience validation

- Test desktop and mobile browsers on the Cloudflare subdomain.
- Test both an awake app and a sleeping app that displays
  **Get this app back up**.
- Verify PDF upload, provider calls, clipboard actions, sidebar navigation, and
  DOCX download through the iframe.
- Verify direct-link fallback and reduced-motion behavior.
- Confirm no provider key appears in the GitHub repository, Pages assets, browser
  source, or Cloudflare environment.

Exit gate: every item in the baseline acceptance matrix is either passed or has a
documented Community Cloud limitation.

## Phase 5 — Go-live and maintenance

- Point the public portfolio link to `resume.pharaohchirchir.com`.
- Keep the raw Streamlit URL available as a fallback.
- Review Streamlit and Cloudflare logs after launch.
- Upgrade pinned dependencies deliberately, rerunning tests before each release.
- Revisit a persistent application host only when accounts, durable storage, or
  always-on service becomes a funded requirement.

Exit gate: the custom subdomain is the primary link and rollback to the direct
Streamlit URL is documented.

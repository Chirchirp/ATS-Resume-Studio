# Streamlit Community Cloud deployment

## Deployment coordinates

- GitHub repository: the repository containing this project
- Branch: `main` (recommended)
- Entrypoint: `app.py`
- Python: `3.11`
- Suggested app subdomain: `ats-resume-studio`

Python 3.11 matches the captured and tested local baseline. The direct Python
dependencies are pinned in `requirements.txt`; the project does not currently
need a Debian `packages.txt` file.

## Secrets

In **Advanced settings → Secrets**, add only the provider keys you intend the
public deployment to use:

```toml
GROQ_API_KEY = ""
GEMINI_API_KEY = ""
OPENROUTER_API_KEY = ""
APP_SESSION_SECRET = "replace-with-at-least-32-random-characters"
```

Do not commit `.streamlit/secrets.toml`. It is ignored by Git. If no shared key is
configured, visitors can still enter their own provider key in the application
sidebar for their current Streamlit session.

## Studio login

The Streamlit entry point is protected by the shared **Modern Resume AI Agent**
account. Only a PBKDF2 password verifier is committed; the plaintext password is
not stored in the repository. A signed browser token keeps the account open for
seven days and the Cloudflare shell relays that opaque token when an embedded
Streamlit session reconnects. The token contains no password or provider key.

The app also keeps a small encrypted recovery snapshot for each signed browser
workspace. It includes the resume, JD, clarification answers, and useful generated
documents, but explicitly excludes API keys and credentials. **Sign out** removes
the browser token; **Clear current and saved workspace** removes the snapshot.

The optional `APP_LOGIN_USERNAME`, `APP_LOGIN_PASSWORD_SALT`, and
`APP_LOGIN_PASSWORD_HASH` secrets can replace the shared credential later
without a code change. Set `APP_SESSION_SECRET` to a stable random value of at
least 32 characters so signed sessions survive application redeployments. Leave
the login overrides blank to retain the built-in account.

## Deploy

1. Push the repository to GitHub.
2. Open `share.streamlit.io` and choose **Create app**.
3. Select the repository and branch, then set the entrypoint to `app.py`.
4. Open **Advanced settings**, select Python `3.11`, and paste the required
   provider secrets.
5. Choose a stable `streamlit.app` subdomain and deploy.
6. Record the final public URL. It becomes `STREAMLIT_APP_URL` for the Cloudflare
   Worker wrapper.

## Smoke-test checklist

- The application opens with the existing left navigation expanded.
- Unauthenticated visitors see only the login screen.
- The shared account opens the studio, and **Sign out** returns to the gate.
- Analyze, Evidence, Workspace, Premium Solutions, and How It Works open.
- Resume PDF upload and pasted resume text both work.
- Resume Quality Review runs without a job description.
- Deterministic ATS alignment gives the same score everywhere it is displayed.
- Each configured AI provider completes one low-cost request.
- Grounded achievement, ideal resume, cover letter, and custom query actions run.
- Truth audit blocks unsupported claims before DOCX download.
- DOCX generation and browser download work through the Cloudflare iframe.
- Mobile layout exposes the Streamlit sidebar control and remains usable.

## Community Cloud boundaries

- The Streamlit process may sleep after inactivity; the wrapper cannot prevent
  that on the free tier.
- Live Session State and `usage_logs.csv` are ephemeral. The encrypted workspace
  snapshot recovers ordinary browser disconnects and app sleeps, but Community
  Cloud's local disk can still be replaced during a redeploy or infrastructure restart.
- The separate FastAPI platform is not started by `streamlit run app.py` and
  requires a different host if persistent accounts and background jobs are
  exposed later.
- Public embedding is supported; private Streamlit Community Cloud apps are not
  officially supported in an iframe.

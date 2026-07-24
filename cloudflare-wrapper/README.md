# Cloudflare wrapper

This directory contains the static shell for `resume.pharaohchirchir.com`. It
preserves the full Streamlit application inside a supported public iframe and
shows the branded wake-up animation while the iframe starts. The repository
supports both Cloudflare Workers Static Assets and Cloudflare Pages.

## Cloudflare Worker settings

The current `modern-resume-ai-agent` Cloudflare project uses Workers Builds.
Configure it from the repository root:

- Path / root directory: `/`
- Build command: `npm run build`
- Deploy command: `npx wrangler deploy`
- Non-production deploy command: `npx wrangler versions upload`
- Build variable:
  - `STREAMLIT_APP_URL=https://modernresumescanapp.streamlit.app`

The root `package.json` builds these assets into `/dist`, and `wrangler.jsonc`
deploys that directory using the `modern-resume-ai-agent` Worker name. Security
and cache headers are applied by `cloudflare-worker.mjs`.

## Cloudflare Pages settings

If a separate Pages project is used later:

- Root directory: `cloudflare-wrapper`
- Build command: `npm run build`
- Build output directory: `dist`
- Environment variable:
  - `STREAMLIT_APP_URL=https://<your-streamlit-subdomain>.streamlit.app`

Both build paths intentionally fail when the URL is absent or is not a public
HTTPS `streamlit.app` URL. No AI-provider API key belongs in this Cloudflare
project.

## Local validation

From this directory:

```powershell
$env:STREAMLIT_APP_URL="https://your-app.streamlit.app"
npm run check
npm run build
```

Serve `dist` with any static HTTP server. The generated directory is ignored by
Git because Cloudflare creates it during each deployment.

From the repository root, reproduce the Worker build with:

```powershell
$env:STREAMLIT_APP_URL="https://modernresumescanapp.streamlit.app"
npm install
npm run build
npx wrangler deploy --dry-run
```

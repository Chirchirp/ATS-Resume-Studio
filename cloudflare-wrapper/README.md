# Cloudflare Pages wrapper

This directory contains the static shell for `resume.pharaohchirchir.com`. It
preserves the full Streamlit application inside a supported public iframe and
shows the branded wake-up animation while the iframe starts.

## Cloudflare Pages settings

- Root directory: `cloudflare-wrapper`
- Build command: `npm run build`
- Build output directory: `dist`
- Environment variable:
  - `STREAMLIT_APP_URL=https://<your-streamlit-subdomain>.streamlit.app`

The build intentionally fails when the URL is absent or is not a public HTTPS
`streamlit.app` URL. No API key belongs in this Cloudflare project.

## Local validation

From this directory:

```powershell
$env:STREAMLIT_APP_URL="https://your-app.streamlit.app"
npm run check
npm run build
```

Serve `dist` with any static HTTP server. The generated directory is ignored by
Git because Cloudflare creates it during each deployment.

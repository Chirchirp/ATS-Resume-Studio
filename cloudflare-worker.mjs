const SECURITY_HEADERS = Object.freeze({
  "Content-Security-Policy":
    "default-src 'self'; script-src 'self'; style-src 'self'; " +
    "frame-src https://*.streamlit.app; img-src 'self' data:; " +
    "connect-src 'self'; object-src 'none'; base-uri 'none'; " +
    "form-action 'none'; frame-ancestors 'none'",
  "Permissions-Policy":
    "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
  "Referrer-Policy": "strict-origin-when-cross-origin",
  "X-Content-Type-Options": "nosniff",
  "X-Frame-Options": "DENY",
});

function cachePolicy(pathname) {
  if (pathname === "/" || pathname === "/index.html") {
    return "no-cache";
  }
  if (
    pathname === "/config.js" ||
    pathname === "/app.js" ||
    pathname === "/styles.css"
  ) {
    return "public, max-age=300, must-revalidate";
  }
  return "";
}

export default {
  async fetch(request, environment) {
    const assetResponse = await environment.ASSETS.fetch(request);
    const response = new Response(assetResponse.body, assetResponse);

    for (const [name, value] of Object.entries(SECURITY_HEADERS)) {
      response.headers.set(name, value);
    }

    const policy = cachePolicy(new URL(request.url).pathname);
    if (policy) {
      response.headers.set("Cache-Control", policy);
    }

    return response;
  },
};

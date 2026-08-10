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

const STATUS_PATH = "/api/streamlit-status";

function jsonResponse(payload, status = 200) {
  const response = Response.json(payload, { status });
  response.headers.set("Cache-Control", "no-store, max-age=0");
  for (const [name, value] of Object.entries(SECURITY_HEADERS)) {
    response.headers.set(name, value);
  }
  return response;
}

function validatedStreamlitUrl(value) {
  if (!value) {
    return null;
  }

  let target;
  try {
    target = new URL(value);
  } catch {
    return null;
  }

  const validHostname =
    target.hostname === "streamlit.app" ||
    target.hostname.endsWith(".streamlit.app");
  if (
    target.protocol !== "https:" ||
    !validHostname ||
    target.username ||
    target.password
  ) {
    return null;
  }

  target.search = "";
  target.hash = "";
  target.pathname = `${target.pathname.replace(/\/+$/, "")}/_stcore/health`;
  return target;
}

async function streamlitStatus(requestUrl) {
  const healthUrl = validatedStreamlitUrl(requestUrl.searchParams.get("url"));
  if (!healthUrl) {
    return jsonResponse(
      { status: "invalid", message: "A valid streamlit.app URL is required." },
      400
    );
  }

  try {
    const upstream = await fetch(healthUrl, {
      headers: {
        Accept: "text/plain",
        "User-Agent": "ATS-Resume-Studio-Readiness/1.0",
      },
      // A sleeping Community Cloud app redirects this private health route to
      // Streamlit's hosting shell. Following that redirect can loop, so the
      // redirect itself is intentionally treated as a non-ready signal.
      redirect: "manual",
      cf: { cacheTtl: 0, cacheEverything: false },
    });
    const contentType = upstream.headers.get("content-type") || "";
    const body = (await upstream.text()).trim().toLowerCase();
    const ready =
      upstream.ok &&
      contentType.includes("text/plain") &&
      (body === "ok" || body.startsWith("ok\n"));

    return jsonResponse({
      status: ready ? "ready" : "sleeping",
      upstreamStatus: upstream.status,
      checkedAt: new Date().toISOString(),
    });
  } catch {
    return jsonResponse(
      {
        status: "unavailable",
        message: "Streamlit readiness could not be checked.",
      },
      502
    );
  }
}

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
    const requestUrl = new URL(request.url);
    if (requestUrl.pathname === STATUS_PATH) {
      if (request.method !== "GET") {
        return jsonResponse({ status: "invalid", message: "Method not allowed." }, 405);
      }
      return streamlitStatus(requestUrl);
    }

    const assetResponse = await environment.ASSETS.fetch(request);
    const response = new Response(assetResponse.body, assetResponse);

    for (const [name, value] of Object.entries(SECURITY_HEADERS)) {
      response.headers.set(name, value);
    }

    const policy = cachePolicy(requestUrl.pathname);
    if (policy) {
      response.headers.set("Cache-Control", policy);
    }

    return response;
  },
};

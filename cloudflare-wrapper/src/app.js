const stage = document.querySelector(".app-stage");
const frame = document.querySelector("#studio-frame");
const directLink = document.querySelector("#direct-link");
const helperDirectLink = document.querySelector("#helper-direct-link");
const retryButton = document.querySelector("#retry-button");
const dismissHelper = document.querySelector("#dismiss-helper");
const wakeHelper = document.querySelector(".wake-helper");
const helperMessage = document.querySelector("#wake-helper-message");
const progressText = document.querySelector("#wake-progress");
const errorPanel = document.querySelector(".configuration-error");
const errorMessage = document.querySelector("#configuration-message");
const configuration = window.ATS_STUDIO_CONFIG;
const WAKE_ATTEMPT_KEY = "atsStudioWakeAttempt";
const STATUS_ENDPOINT = "/api/streamlit-status";
const POLL_INTERVAL_MS = 5000;
const STATUS_TIMEOUT_MS = 12000;
const FRAME_REVEAL_FALLBACK_MS = 6500;

const progressMessages = [
  "Preparing your workspace…",
  "Reconnecting resume intelligence…",
  "Loading analysis and document tools…",
  "Almost ready…",
];

function showConfigurationError(message) {
  stage.dataset.state = "error";
  document.querySelector(".wake-screen").hidden = true;
  errorMessage.textContent = message;
  errorPanel.hidden = false;
}

function buildEmbedUrl(value) {
  const url = new URL(value);
  // Once readiness is confirmed, embed Streamlit's actual runtime directly.
  // Embedding the public root adds another cross-origin hosting iframe whose
  // load event is not reliable across browsers after a Community Cloud wake.
  url.pathname = `${url.pathname.replace(/\/+$/, "")}/~/+/`;
  url.searchParams.set("embed", "true");
  url.searchParams.append("embed_options", "hide_loading_screen");
  return url.toString();
}

function setFrameSource(publicUrl, reason = "") {
  const embedUrl = new URL(buildEmbedUrl(publicUrl));
  if (reason) {
    embedUrl.searchParams.set("wake_retry", Date.now().toString());
  }
  frame.src = embedUrl.toString();
}

function setWakeState(state, progress, guidance) {
  stage.dataset.state = state;
  progressText.textContent = progress;
  if (guidance) {
    helperMessage.textContent = guidance;
  }
}

function recordWakeAttempt() {
  window.sessionStorage.setItem(WAKE_ATTEMPT_KEY, Date.now().toString());
  setWakeState(
    "waiting",
    "Wake page opened — waiting for Streamlit to start…",
    "Click “Yes, get this app back up!” in the new tab. This page reconnects automatically."
  );
}

function recentlyAttemptedWake() {
  const attemptedAt = Number(window.sessionStorage.getItem(WAKE_ATTEMPT_KEY));
  return Number.isFinite(attemptedAt) && Date.now() - attemptedAt < 5 * 60 * 1000;
}

function startStudio() {
  if (!configuration || !configuration.streamlitUrl) {
    showConfigurationError(
      "The Cloudflare build is missing STREAMLIT_APP_URL."
    );
    return;
  }

  let publicUrl;
  try {
    publicUrl = new URL(configuration.streamlitUrl);
  } catch {
    showConfigurationError("The configured Streamlit application URL is invalid.");
    return;
  }

  directLink.href = publicUrl.toString();
  helperDirectLink.href = publicUrl.toString();
  directLink.addEventListener("click", recordWakeAttempt);
  helperDirectLink.addEventListener("click", recordWakeAttempt);
  dismissHelper.addEventListener("click", () => {
    wakeHelper.dataset.dismissed = "true";
  });

  let messageIndex = 0;
  const progressTimer = window.setInterval(() => {
    if (stage.dataset.state === "sleeping") {
      return;
    }
    messageIndex = Math.min(messageIndex + 1, progressMessages.length - 1);
    progressText.textContent = progressMessages[messageIndex];
  }, 1250);

  let revealed = false;
  let frameStarted = false;
  let pollTimer;
  let frameFallbackTimer;
  let checking = false;

  const revealStudio = () => {
    if (revealed) {
      return;
    }
    revealed = true;
    window.clearInterval(progressTimer);
    window.clearTimeout(frameFallbackTimer);
    stage.dataset.state = "ready";
    document.querySelector(".wake-screen").setAttribute("aria-hidden", "true");
  };

  const loadReadyStudio = (reason) => {
    if (frameStarted) {
      return;
    }
    frameStarted = true;
    setWakeState(
      "connecting",
      "Streamlit is awake. Opening your workspace…",
      "The application is awake and reconnecting."
    );
    frame.addEventListener(
      "load",
      () => window.setTimeout(revealStudio, 450),
      { once: true }
    );
    setFrameSource(publicUrl.toString(), reason);
    frameFallbackTimer = window.setTimeout(() => {
      if (!revealed) {
        helperMessage.textContent =
          "Streamlit confirmed the runtime is ready. Displaying it now.";
        revealStudio();
      }
    }, FRAME_REVEAL_FALLBACK_MS);
  };

  const scheduleCheck = (delay = POLL_INTERVAL_MS) => {
    window.clearTimeout(pollTimer);
    pollTimer = window.setTimeout(checkReadiness, delay);
  };

  const checkReadiness = async () => {
    if (checking || revealed || frameStarted) {
      return;
    }
    checking = true;
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), STATUS_TIMEOUT_MS);

    try {
      const statusUrl = new URL(STATUS_ENDPOINT, window.location.origin);
      statusUrl.searchParams.set("url", publicUrl.toString());
      statusUrl.searchParams.set("check", Date.now().toString());
      const response = await fetch(statusUrl, {
        cache: "no-store",
        headers: { Accept: "application/json" },
        signal: controller.signal,
      });
      const result = await response.json();

      if (response.ok && result.status === "ready") {
        loadReadyStudio(recentlyAttemptedWake() ? "woken" : "ready");
        return;
      }

      if (result.status === "sleeping") {
        setWakeState(
          "sleeping",
          recentlyAttemptedWake()
            ? "Waiting for Streamlit to finish waking…"
            : "Streamlit is paused. Use the button below to wake it.",
          "The embedded app stays hidden until Streamlit confirms it is running."
        );
      } else {
        setWakeState(
          "waiting",
          "Checking Streamlit again…",
          "The readiness check is temporarily unavailable. You can still use the direct wake page."
        );
      }
    } catch {
      setWakeState(
        "waiting",
        "Connection check timed out. Retrying…",
        "You can open the direct wake page while this page keeps checking."
      );
    } finally {
      checking = false;
      window.clearTimeout(timeout);
      if (!revealed && !frameStarted) {
        scheduleCheck();
      }
    }
  };

  retryButton.addEventListener("click", () => {
    setWakeState("checking", "Checking Streamlit now…");
    void checkReadiness();
  });

  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") {
      setWakeState(
        "checking",
        recentlyAttemptedWake()
          ? "Welcome back. Checking whether Streamlit is ready…"
          : "Checking Streamlit…"
      );
      void checkReadiness();
    }
  });

  window.addEventListener("focus", () => void checkReadiness());
  window.addEventListener("pageshow", () => void checkReadiness());
  window.addEventListener("online", () => void checkReadiness());
  void checkReadiness();
}

startStudio();

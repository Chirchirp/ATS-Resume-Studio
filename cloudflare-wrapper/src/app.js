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

function recordWakeAttempt() {
  window.sessionStorage.setItem(WAKE_ATTEMPT_KEY, Date.now().toString());
  progressText.textContent =
    "Wake page opened. Click Streamlit’s wake button, then return here.";
  helperMessage.textContent =
    "After Streamlit reports that the app is waking, return here and reload the embedded app.";
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
  retryButton.addEventListener("click", () => {
    helperMessage.textContent = "Reloading the embedded Streamlit application…";
    setFrameSource(publicUrl.toString(), "manual");
  });
  dismissHelper.addEventListener("click", () => {
    wakeHelper.dataset.dismissed = "true";
  });
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible" && recentlyAttemptedWake()) {
      helperMessage.textContent =
        "Welcome back. Reloading the app after the Streamlit wake attempt…";
      window.setTimeout(
        () => setFrameSource(publicUrl.toString(), "return"),
        750
      );
    }
  });

  setFrameSource(
    publicUrl.toString(),
    recentlyAttemptedWake() ? "recent-attempt" : ""
  );

  const startedAt = performance.now();
  let messageIndex = 0;
  const progressTimer = window.setInterval(() => {
    messageIndex = Math.min(messageIndex + 1, progressMessages.length - 1);
    progressText.textContent = progressMessages[messageIndex];
  }, 1250);

  let revealed = false;
  const revealStudio = () => {
    if (revealed) {
      return;
    }
    revealed = true;
    window.clearInterval(progressTimer);
    stage.dataset.state = "ready";
    document.querySelector(".wake-screen").setAttribute("aria-hidden", "true");
  };

  frame.addEventListener(
    "load",
    () => {
      const elapsed = performance.now() - startedAt;
      window.setTimeout(revealStudio, Math.max(0, 3200 - elapsed));
    },
    { once: true }
  );
}

startStudio();

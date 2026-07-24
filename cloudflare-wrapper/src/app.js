const stage = document.querySelector(".app-stage");
const frame = document.querySelector("#studio-frame");
const directLink = document.querySelector("#direct-link");
const progressText = document.querySelector("#wake-progress");
const errorPanel = document.querySelector(".configuration-error");
const errorMessage = document.querySelector("#configuration-message");
const configuration = window.ATS_STUDIO_CONFIG;

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
  frame.src = buildEmbedUrl(publicUrl.toString());

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

  window.setTimeout(revealStudio, 6500);
}

startStudio();

from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def test_streamlit_cloud_files_are_present_and_pinned():
    requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    config = (ROOT / ".streamlit" / "config.toml").read_text(encoding="utf-8")
    python_version = (ROOT / ".python-version").read_text(encoding="utf-8").strip()

    assert "streamlit==1.60.0" in requirements
    assert "groq==1.5.0" in requirements
    assert "protobuf>=3.20,<6.0" in requirements
    assert python_version == "3.11"
    assert "headless = true" in config
    assert "gatherUsageStats = false" in config


def test_real_streamlit_secrets_are_ignored():
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert ".streamlit/secrets.toml" in gitignore
    assert not (ROOT / ".streamlit" / "secrets.toml").exists()


def test_cloudflare_wrapper_contains_required_cold_boot_copy():
    markup = (
        ROOT / "cloudflare-wrapper" / "src" / "index.html"
    ).read_text(encoding="utf-8")

    assert "Starting ATS Resume Studio" in markup
    assert (
        "Application paused due to inactivity. click “Get this app back up.” "
        "Initial startup may take a short time."
    ) in markup
    assert "Wake ATS Resume Studio" in markup
    assert 'id="helper-direct-link"' in markup
    assert 'id="retry-button"' in markup


def test_cloudflare_wrapper_has_recoverable_wake_flow_and_fresh_assets():
    markup = (
        ROOT / "cloudflare-wrapper" / "src" / "index.html"
    ).read_text(encoding="utf-8")
    script = (
        ROOT / "cloudflare-wrapper" / "src" / "app.js"
    ).read_text(encoding="utf-8")
    worker = (ROOT / "cloudflare-worker.mjs").read_text(encoding="utf-8")
    headers = (
        ROOT / "cloudflare-wrapper" / "src" / "_headers"
    ).read_text(encoding="utf-8")
    browser_storage = (
        ROOT / "utils" / "browser_storage.py"
    ).read_text(encoding="utf-8")

    assert "visibilitychange" in script
    assert "atsStudioWakeAttempt" in script
    assert "wake_retry" in script
    assert "setFrameSource" in script
    assert 'STATUS_ENDPOINT = "/api/streamlit-status"' in script
    assert 'result.status === "ready"' in script
    assert "loadReadyStudio" in script
    assert '/~/+/' in script
    assert "FRAME_REVEAL_FALLBACK_MS" in script
    assert 'window.addEventListener("pageshow"' in script
    assert 'window.addEventListener("online"' in script
    assert "atsResumeStudioSignedSession" in script
    assert 'type === "ats-session-request"' in script
    assert 'type === "ats-session-save"' in script
    assert 'type === "ats-session-clear"' in script
    assert 'type: "ats-session-request"' in browser_storage
    assert 'type: "ats-session-save"' in browser_storage
    assert 'type: "ats-session-clear"' in browser_storage
    assert 'stage.dataset.state = "ready"' in script
    assert 'frame.addEventListener(\n      "load"' in script
    assert "setTimeout(revealStudio, 6500)" not in script
    assert 'const STATUS_PATH = "/api/streamlit-status"' in worker
    assert 'contentType.includes("text/plain")' in worker
    assert 'body === "ok"' in worker
    assert 'target.hostname.endsWith(".streamlit.app")' in worker
    assert '/~/+/_stcore/health' in worker
    assert 'pathname === "/app.js"' in worker
    assert 'pathname === "/styles.css"' in worker
    assert "max-age=604800, immutable" not in worker
    assert "max-age=604800, immutable" not in headers
    assert 'href="./styles.css?v=20260811-session-bridge"' in markup
    assert 'src="./app.js?v=20260811-session-bridge"' in markup


def test_cloudflare_wrapper_requires_runtime_streamlit_url():
    build_script = (
        ROOT / "cloudflare-wrapper" / "build.mjs"
    ).read_text(encoding="utf-8")
    headers = (
        ROOT / "cloudflare-wrapper" / "src" / "_headers"
    ).read_text(encoding="utf-8")
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()

    assert "STREAMLIT_APP_URL is required" in build_script
    assert "https://*.streamlit.app" in headers
    assert "cloudflare-wrapper/dist/" in gitignore


def test_cloudflare_worker_builds_from_repository_root():
    package = (ROOT / "package.json").read_text(encoding="utf-8")
    wrangler = (ROOT / "wrangler.jsonc").read_text(encoding="utf-8")
    worker = (ROOT / "cloudflare-worker.mjs").read_text(encoding="utf-8")

    assert "--output-directory=dist" in package
    assert '"wrangler": "4.114.0"' in package
    assert '"name": "modern-resume-ai-agent"' in wrangler
    assert '"directory": "./dist"' in wrangler
    assert '"binding": "ASSETS"' in wrangler
    assert "Content-Security-Policy" in worker
    assert "environment.ASSETS.fetch(request)" in worker


def test_resume_generation_has_adaptive_capacity_recovery_and_page_range():
    source = (ROOT / "components" / "tab_premium.py").read_text(encoding="utf-8")
    assert "options=[1, 2, 3, 4]" in source
    assert "attempt_specs" in source
    assert source.count('"evidence_chars":') >= 3
    assert "build_safe_evidence_resume" in source
    assert "deterministic_capacity_recovery" in source

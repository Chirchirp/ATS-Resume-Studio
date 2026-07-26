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
    assert "Wake app directly" in markup
    assert 'id="helper-direct-link"' in markup
    assert 'id="retry-button"' in markup


def test_cloudflare_wrapper_has_recoverable_wake_flow_and_fresh_assets():
    script = (
        ROOT / "cloudflare-wrapper" / "src" / "app.js"
    ).read_text(encoding="utf-8")
    worker = (ROOT / "cloudflare-worker.mjs").read_text(encoding="utf-8")
    headers = (
        ROOT / "cloudflare-wrapper" / "src" / "_headers"
    ).read_text(encoding="utf-8")

    assert "visibilitychange" in script
    assert "atsStudioWakeAttempt" in script
    assert "wake_retry" in script
    assert "setFrameSource" in script
    assert "setTimeout(revealStudio, 6500)" not in script
    assert 'pathname === "/app.js"' in worker
    assert 'pathname === "/styles.css"' in worker
    assert "max-age=604800, immutable" not in worker
    assert "max-age=604800, immutable" not in headers


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

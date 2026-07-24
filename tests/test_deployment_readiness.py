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

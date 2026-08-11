"""Shared-account authentication for the Streamlit studio.

The repository contains a slow password verifier, never the plaintext password.
A signed browser token restores authentication after Streamlit replaces its
WebSocket session; the token contains no password or provider credential.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import time
import uuid

import streamlit as st

from platform_api.security import TokenSigner
from utils.browser_storage import browser_storage
from utils.session_store import session_secret


DEFAULT_LOGIN_USERNAME = "Modern Resume AI Agent"
DEFAULT_PASSWORD_SALT = "c51114b0b6814091eed4dd9b6d330b56"
DEFAULT_PASSWORD_HASH = (
    "d0e03debb19e472eb3d087ebd7fb8f724b04d5077339595ab535f508be8480e8"
)
PASSWORD_ITERATIONS = 600_000
MAX_FAILED_ATTEMPTS = 5
LOCKOUT_SECONDS = 60
AUTH_STORAGE_KEY = "ats_resume_studio_session"
AUTH_SESSION_TTL_SECONDS = 7 * 24 * 60 * 60


def _setting(name: str, fallback: str) -> str:
    """Resolve an optional authentication override without exposing it in UI."""
    try:
        secret_value = st.secrets.get(name, "")
    except (FileNotFoundError, KeyError):
        secret_value = ""
    return str(secret_value or os.environ.get(name, "") or fallback).strip()


def _password_digest(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        PASSWORD_ITERATIONS,
    ).hex()


def password_matches(
    password: str,
    *,
    salt: str = DEFAULT_PASSWORD_SALT,
    expected_hash: str = DEFAULT_PASSWORD_HASH,
) -> bool:
    """Compare a candidate password to a PBKDF2 verifier in constant time."""
    candidate_hash = _password_digest(password, salt)
    return hmac.compare_digest(candidate_hash, expected_hash)


def credentials_are_valid(username: str, password: str) -> bool:
    expected_username = _setting("APP_LOGIN_USERNAME", DEFAULT_LOGIN_USERNAME)
    expected_salt = _setting("APP_LOGIN_PASSWORD_SALT", DEFAULT_PASSWORD_SALT)
    expected_hash = _setting("APP_LOGIN_PASSWORD_HASH", DEFAULT_PASSWORD_HASH)
    username_matches = hmac.compare_digest(
        username.strip().casefold(),
        expected_username.casefold(),
    )
    return username_matches and password_matches(
        password,
        salt=expected_salt,
        expected_hash=expected_hash,
    )


def _token_signer() -> TokenSigner:
    return TokenSigner(session_secret(), ttl_seconds=AUTH_SESSION_TTL_SECONDS)


def issue_persistent_login(workspace_id: str | None = None) -> tuple[str, str]:
    """Issue a signed token and its opaque per-browser workspace identifier."""
    workspace_id = workspace_id or uuid.uuid4().hex
    token = _token_signer().issue(workspace_id, DEFAULT_LOGIN_USERNAME)
    return token, workspace_id


def verify_persistent_login(token: str) -> str | None:
    """Return the signed workspace ID or ``None`` for an invalid/expired token."""
    try:
        claims = _token_signer().verify(token)
    except ValueError:
        return None
    if not hmac.compare_digest(claims.email, DEFAULT_LOGIN_USERNAME):
        return None
    return claims.user_id


def _restore_browser_login() -> bool:
    try:
        token = browser_storage(
            "get",
            AUTH_STORAGE_KEY,
            key="auth_browser_token_reader",
        )
    except Exception:
        return False
    workspace_id = verify_persistent_login(str(token or ""))
    if not workspace_id:
        return False
    st.session_state["auth_authenticated"] = True
    st.session_state["auth_workspace_id"] = workspace_id
    st.session_state["auth_restored_from_browser"] = True
    return True


def _remember_login() -> None:
    token, workspace_id = issue_persistent_login()
    st.session_state["auth_workspace_id"] = workspace_id
    try:
        browser_storage(
            "set",
            AUTH_STORAGE_KEY,
            token,
            key="auth_browser_token_writer",
        )
    except Exception:
        # The current Streamlit session still remains authenticated. The login
        # form can be used again if a browser blocks all embedded storage.
        st.session_state["auth_storage_warning"] = True


def _render_login_styles() -> None:
    st.markdown(
        """
        <style>
        body:has(#ats-login-marker) .stApp {
            background:
                radial-gradient(circle at 18% 20%, rgba(37,99,235,.26), transparent 34rem),
                radial-gradient(circle at 82% 82%, rgba(6,182,212,.15), transparent 30rem),
                #07111f !important;
        }
        body:has(#ats-login-marker) section[data-testid="stSidebar"],
        body:has(#ats-login-marker) [data-testid="stSidebarCollapsedControl"] {
            display: none !important;
        }
        body:has(#ats-login-marker) [data-testid="stMainBlockContainer"] {
            width: min(100%, 1080px);
            max-width: 1080px;
            padding-top: clamp(3rem, 9vh, 7rem);
            padding-bottom: 3rem;
        }
        body:has(#ats-login-marker) header[data-testid="stHeader"] {
            background: transparent !important;
        }
        .login-brand {
            padding: clamp(1rem, 3vw, 2.5rem) 0;
        }
        .login-kicker {
            display: inline-flex;
            align-items: center;
            gap: .5rem;
            margin-bottom: 1.25rem;
            padding: .42rem .78rem;
            border: 1px solid rgba(125,169,255,.28);
            border-radius: 999px;
            background: rgba(23,47,80,.56);
            color: #8fdfff;
            font-size: .73rem;
            font-weight: 800;
            letter-spacing: .12em;
            text-transform: uppercase;
        }
        .login-kicker::before {
            width: .48rem;
            height: .48rem;
            border-radius: 50%;
            background: #42d3ff;
            box-shadow: 0 0 16px rgba(66,211,255,.9);
            content: "";
        }
        .login-brand h1 {
            max-width: 10ch;
            margin: 0;
            color: #fff;
            font-family: 'DM Serif Display', serif;
            font-size: clamp(3rem, 7vw, 5.8rem);
            line-height: .94;
            letter-spacing: -.045em;
        }
        .login-brand > p {
            max-width: 35rem;
            margin: 1.35rem 0 0;
            color: #9fb1c8;
            font-size: clamp(1rem, 1.6vw, 1.12rem);
            line-height: 1.7;
        }
        .login-feature-row {
            display: flex;
            flex-wrap: wrap;
            gap: .55rem;
            margin-top: 1.8rem;
        }
        .login-feature-row span {
            padding: .48rem .72rem;
            border: 1px solid rgba(151,187,232,.17);
            border-radius: .62rem;
            background: rgba(11,27,47,.72);
            color: #c6d7eb;
            font-size: .76rem;
        }
        body:has(#ats-login-marker) div[data-testid="stForm"] {
            margin-top: .6rem;
            padding: clamp(1.35rem, 4vw, 2.25rem);
            border: 1px solid rgba(140,177,224,.22);
            border-radius: 1.1rem;
            background: rgba(11,26,45,.88);
            box-shadow: 0 1.7rem 5rem rgba(0,0,0,.32);
            backdrop-filter: blur(16px);
        }
        body:has(#ats-login-marker) div[data-testid="stForm"] label,
        body:has(#ats-login-marker) div[data-testid="stForm"] p {
            color: #cad9eb !important;
        }
        body:has(#ats-login-marker) div[data-testid="stForm"] input {
            border: 1px solid #304866 !important;
            background: #111f32 !important;
            color: #f4f8ff !important;
        }
        body:has(#ats-login-marker) div[data-testid="stForm"] input:focus {
            border-color: #4f8cff !important;
            box-shadow: 0 0 0 3px rgba(79,140,255,.2) !important;
        }
        body:has(#ats-login-marker) div[data-testid="stFormSubmitButton"] button {
            min-height: 2.85rem;
            border: 0 !important;
            background: linear-gradient(110deg, #2563eb, #147ee8) !important;
            color: #fff !important;
            box-shadow: 0 .7rem 1.8rem rgba(37,99,235,.24);
        }
        .login-card-heading {
            margin-bottom: 1rem;
        }
        .login-card-heading h2 {
            margin: 0 0 .4rem;
            color: #fff;
            font-size: 1.55rem;
        }
        .login-card-heading p {
            margin: 0;
            color: #8fa5be;
            font-size: .88rem;
            line-height: 1.55;
        }
        .login-account {
            display: flex;
            align-items: center;
            gap: .8rem;
            margin: 0 0 1rem;
            padding: .75rem .85rem;
            border: 1px solid rgba(151,187,232,.14);
            border-radius: .75rem;
            background: rgba(25,47,74,.54);
        }
        .login-account-mark {
            display: grid;
            place-items: center;
            width: 2.15rem;
            height: 2.15rem;
            border-radius: .65rem;
            background: linear-gradient(135deg, #2563eb, #06b6d4);
            color: #fff;
            font-size: .77rem;
            font-weight: 900;
            letter-spacing: .06em;
        }
        .login-account strong {
            display: block;
            color: #eef6ff;
            font-size: .86rem;
        }
        .login-account small {
            color: #8fa5be;
        }
        .login-security-note {
            margin-top: .8rem;
            color: #7088a3;
            font-size: .73rem;
            text-align: center;
        }
        @media (max-width: 768px) {
            body:has(#ats-login-marker) [data-testid="stMainBlockContainer"] {
                padding-top: 1rem;
            }
            .login-brand {
                padding-bottom: .35rem;
                text-align: center;
            }
            .login-brand h1,
            .login-brand > p {
                margin-inline: auto;
            }
            .login-feature-row {
                justify-content: center;
                margin-top: 1.1rem;
            }
        }
        </style>
        <div id="ats-login-marker"></div>
        """,
        unsafe_allow_html=True,
    )


def render_login_gate() -> bool:
    """Render the login screen and return whether the session is authenticated."""
    if st.session_state.get("auth_authenticated", False):
        st.session_state.pop("auth_login_pending", None)
        return True
    if _restore_browser_login():
        return True

    _render_login_styles()
    brand_column, form_column = st.columns([1.15, 0.85], gap="large")

    with brand_column:
        st.markdown(
            """
            <section class="login-brand">
                <div class="login-kicker">Protected AI workspace</div>
                <h1>Build a resume that earns attention.</h1>
                <p>
                    Evidence-grounded analysis, transparent ATS alignment, and
                    document generation designed around the candidate's real story.
                </p>
                <div class="login-feature-row">
                    <span>Explainable ATS</span>
                    <span>Truth-audited claims</span>
                    <span>Multi-provider AI</span>
                </div>
            </section>
            """,
            unsafe_allow_html=True,
        )

    with form_column:
        with st.form("studio_login_form", clear_on_submit=False):
            st.markdown(
                f"""
                <div class="login-card-heading">
                    <h2>Welcome back</h2>
                    <p>Sign in to open ATS Resume Studio.</p>
                </div>
                <div class="login-account">
                    <span class="login-account-mark">MR</span>
                    <span>
                        <strong>{DEFAULT_LOGIN_USERNAME}</strong>
                        <small>Studio account</small>
                    </span>
                </div>
                """,
                unsafe_allow_html=True,
            )
            username = st.text_input(
                "Username",
                value=DEFAULT_LOGIN_USERNAME,
                autocomplete="username",
            )
            password = st.text_input(
                "Password",
                type="password",
                autocomplete="current-password",
            )
            submitted = st.form_submit_button(
                "Open ATS Resume Studio",
                type="primary",
                width="stretch",
            )

        lockout_until = float(st.session_state.get("auth_lockout_until", 0.0))
        seconds_remaining = max(0, int(lockout_until - time.time()))

        if submitted:
            if seconds_remaining > 0:
                st.error(
                    f"Too many unsuccessful attempts. Try again in "
                    f"{seconds_remaining + 1} seconds."
                )
            elif credentials_are_valid(username, password):
                st.session_state["auth_authenticated"] = True
                st.session_state["auth_failed_attempts"] = 0
                st.session_state["auth_lockout_until"] = 0.0
                _remember_login()
                st.session_state["auth_login_pending"] = True
            else:
                failed_attempts = int(
                    st.session_state.get("auth_failed_attempts", 0)
                ) + 1
                if failed_attempts >= MAX_FAILED_ATTEMPTS:
                    st.session_state["auth_failed_attempts"] = 0
                    st.session_state["auth_lockout_until"] = (
                        time.time() + LOCKOUT_SECONDS
                    )
                    st.error(
                        "Too many unsuccessful attempts. Sign-in is paused for "
                        f"{LOCKOUT_SECONDS} seconds."
                    )
                else:
                    st.session_state["auth_failed_attempts"] = failed_attempts
                    attempts_left = MAX_FAILED_ATTEMPTS - failed_attempts
                    st.error(
                        "The username or password is incorrect. "
                        f"{attempts_left} attempt"
                        f"{'s' if attempts_left != 1 else ''} remaining."
                    )

        st.markdown(
            '<p class="login-security-note">Protected access · Stay signed in for 7 days</p>',
            unsafe_allow_html=True,
        )

    # The storage component triggers the next rerun after it commits the token.
    # Until then, keep document content behind the login gate.
    return bool(
        st.session_state.get("auth_authenticated")
        and not st.session_state.get("auth_login_pending")
    )


def logout() -> None:
    """Clear sensitive session values and return to the login screen."""
    try:
        browser_storage(
            "remove",
            AUTH_STORAGE_KEY,
            key="auth_browser_token_remover",
        )
    except Exception:
        pass
    for key in list(st.session_state.keys()):
        st.session_state.pop(key, None)
    st.session_state["auth_authenticated"] = False

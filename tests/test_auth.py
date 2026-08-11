import hashlib

from utils.auth import (
    DEFAULT_LOGIN_USERNAME,
    PASSWORD_ITERATIONS,
    issue_persistent_login,
    password_matches,
    verify_persistent_login,
)


def test_default_account_name_is_stable():
    assert DEFAULT_LOGIN_USERNAME == "Modern Resume AI Agent"


def test_password_verifier_accepts_only_matching_digest():
    test_salt = "unit-test-salt"
    expected = hashlib.pbkdf2_hmac(
        "sha256",
        b"correct test password",
        test_salt.encode("utf-8"),
        PASSWORD_ITERATIONS,
    ).hex()

    assert password_matches(
        "correct test password",
        salt=test_salt,
        expected_hash=expected,
    )
    assert not password_matches(
        "incorrect test password",
        salt=test_salt,
        expected_hash=expected,
    )


def test_persistent_login_token_is_signed_and_workspace_scoped():
    token, workspace_id = issue_persistent_login("browser-workspace-123")
    assert workspace_id == "browser-workspace-123"
    assert verify_persistent_login(token) == workspace_id
    assert verify_persistent_login(token + "tampered") is None

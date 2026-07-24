import hashlib

from utils.auth import (
    DEFAULT_LOGIN_USERNAME,
    PASSWORD_ITERATIONS,
    password_matches,
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

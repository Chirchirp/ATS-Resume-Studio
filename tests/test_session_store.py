from pathlib import Path

from utils.session_store import (
    WorkspaceStore,
    build_snapshot,
    clear_saved_workspace,
    restore_workspace,
    save_workspace,
)


def test_snapshot_excludes_all_credentials():
    snapshot = build_snapshot(
        {
            "resume": "Candidate resume",
            "jd": "Target role",
            "groq_api_key": "gsk_must_not_be_saved",
            "provider_api_keys": {"groq": "gsk_must_not_be_saved"},
            "premium_resume_output": {
                "resume": "Generated resume",
                "alignment_gate": {
                    "original_score": 72,
                    "accepted_score": 76,
                    "delta": 4,
                    "passed": True,
                },
                "validation": {"token": "not persisted"},
            },
        }
    )
    serialized = str(snapshot)
    assert "Candidate resume" in serialized
    assert "Generated resume" in serialized
    assert snapshot["state"]["premium_resume_output"]["alignment_gate"]["passed"]
    assert "gsk_must_not_be_saved" not in serialized
    assert "validation" not in snapshot["state"]["premium_resume_output"]


def test_encrypted_workspace_roundtrip_and_clear(tmp_path: Path):
    store = WorkspaceStore(tmp_path / "recovery.db", "x" * 64)
    state = {
        "auth_authenticated": True,
        "auth_workspace_id": "browser-123",
        "resume": "Private resume",
        "jd": "Private JD",
        "clarification_answers": {"E1": "Verified answer"},
    }
    assert save_workspace(state, store)

    restored = {
        "auth_authenticated": True,
        "auth_workspace_id": "browser-123",
    }
    assert restore_workspace(restored, store)
    assert restored["resume"] == "Private resume"
    assert restored["jd"] == "Private JD"
    assert restored["resume_raw"] == "Private resume"
    assert restored["jd_raw"] == "Private JD"

    clear_saved_workspace(restored, store)
    fresh = {
        "auth_authenticated": True,
        "auth_workspace_id": "browser-123",
    }
    assert not restore_workspace(fresh, store)


def test_browser_grant_is_scoped_expires_and_can_be_revoked(tmp_path: Path):
    store = WorkspaceStore(tmp_path / "recovery.db", "x" * 64)
    store.save_browser_grant("fingerprint-a", "workspace-a", expires_at=200)
    store.save_browser_grant("fingerprint-b", "workspace-b", expires_at=300)

    assert store.load_browser_grant("fingerprint-a", now=100) == "workspace-a"
    assert store.load_browser_grant("fingerprint-b", now=100) == "workspace-b"
    assert store.load_browser_grant("fingerprint-a", now=201) is None
    assert store.load_browser_grant("fingerprint-b", now=201) == "workspace-b"

    store.revoke_browser_grant("fingerprint-b")
    assert store.load_browser_grant("fingerprint-b", now=201) is None

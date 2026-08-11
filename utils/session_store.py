"""Encrypted recovery snapshots for Streamlit browser workspaces.

Streamlit session state disappears when a browser/WebSocket session is replaced.
This module stores a deliberately small, JSON-safe subset of the user's work on
the app instance. Provider credentials and authentication widgets are never
included.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import os
import sqlite3
import time
from pathlib import Path
from typing import Any, Mapping, MutableMapping

from platform_api.security import DocumentCipher


RUNTIME_DIR = Path(__file__).resolve().parents[1] / ".runtime"
DEFAULT_DB_PATH = RUNTIME_DIR / "workspace_recovery.db"
MAX_SNAPSHOT_BYTES = 3_000_000

# Only user-authored inputs and useful generated artifacts are recoverable.
# API keys, credential validation, auth tokens, widget passwords, and AI request
# internals are intentionally absent.
RECOVERABLE_KEYS = (
    "jd",
    "resume",
    "jd_raw",
    "resume_raw",
    "inferred_field",
    "last_analysis",
    "premium_tools_output",
    "premium_resume_output",
    "premium_cover_output",
    "premium_custom_output",
    "ideal_resume",
    "key_reqs",
    "clarification_answers",
    "selected_strategy_id",
    "last_resume_request",
)

OUTPUT_STRING_KEYS = {
    "job_title",
    "fields",
    "achievements",
    "resume",
    "annotated_resume",
    "candidate_name",
    "validation_mode",
    "review_pass",
    "source_hash",
    "strategy_id",
    "strategy_name",
    "domain",
    "letter",
    "answer",
    "tone",
}
OUTPUT_PRIMITIVE_KEYS = {"used_resume", "target_pages"}


def _runtime_secret(path: Path | None = None) -> str:
    """Resolve a production override or create an instance-local random secret."""
    try:
        import streamlit as st

        streamlit_secret = str(st.secrets.get("APP_SESSION_SECRET", "") or "").strip()
    except (FileNotFoundError, KeyError, RuntimeError):
        streamlit_secret = ""
    configured = str(
        streamlit_secret
        or os.environ.get("APP_SESSION_SECRET")
        or os.environ.get("ATS_DATA_SECRET")
        or ""
    ).strip()
    if configured:
        return configured
    secret_path = path or (RUNTIME_DIR / "session_secret")
    secret_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        existing = secret_path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        existing = ""
    if len(existing) >= 32:
        return existing
    generated = os.urandom(48).hex()
    secret_path.write_text(generated, encoding="utf-8")
    return generated


def session_secret() -> str:
    """Return the shared instance secret used for signed auth and encryption."""
    return _runtime_secret()


def _safe_value(value: Any, *, depth: int = 0) -> Any:
    if depth > 6:
        return None
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if dataclasses.is_dataclass(value):
        value = dataclasses.asdict(value)
    if isinstance(value, Mapping):
        return {
            str(key): _safe_value(item, depth=depth + 1)
            for key, item in value.items()
            if not _looks_sensitive(str(key))
        }
    if isinstance(value, (list, tuple)):
        return [_safe_value(item, depth=depth + 1) for item in value]
    return str(value)


def _looks_sensitive(key: str) -> bool:
    lowered = key.casefold()
    return any(
        marker in lowered
        for marker in ("api_key", "apikey", "password", "credential", "token", "secret")
    )


def _safe_generated_output(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    safe: dict[str, Any] = {}
    for key in OUTPUT_STRING_KEYS:
        item = value.get(key)
        if isinstance(item, str):
            safe[key] = item
    for key in OUTPUT_PRIMITIVE_KEYS:
        item = value.get(key)
        if isinstance(item, (str, int, float, bool)):
            safe[key] = item
    # Typed validation/role-plan objects are rebuilt deterministically on restore.
    safe["role_bullet_plan"] = []
    return safe


def build_snapshot(state: Mapping[str, Any]) -> dict[str, Any]:
    """Create a bounded, credential-free snapshot from Streamlit state."""
    payload: dict[str, Any] = {"schema": 1, "saved_at": int(time.time()), "state": {}}
    output_keys = {"premium_resume_output", "premium_cover_output"}
    for key in RECOVERABLE_KEYS:
        if key not in state or _looks_sensitive(key):
            continue
        value = state[key]
        if key in output_keys:
            safe = _safe_generated_output(value)
        else:
            safe = _safe_value(value)
        payload["state"][key] = safe
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(encoded) > MAX_SNAPSHOT_BYTES:
        # Generated artifacts are reproducible; preserve authored inputs first.
        for key in ("premium_tools_output", "premium_cover_output", "premium_resume_output"):
            payload["state"].pop(key, None)
            encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            if len(encoded) <= MAX_SNAPSHOT_BYTES:
                break
    if len(encoded) > MAX_SNAPSHOT_BYTES:
        raise ValueError("Workspace is too large for automatic recovery.")
    return payload


class WorkspaceStore:
    """Small encrypted SQLite repository keyed by signed browser workspace ID."""

    def __init__(self, db_path: str | Path = DEFAULT_DB_PATH, secret: str | None = None):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.cipher = DocumentCipher(secret or session_secret())
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS workspace_snapshots (
                    workspace_id TEXT PRIMARY KEY,
                    payload BLOB NOT NULL,
                    updated_at INTEGER NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS browser_grants (
                    browser_fingerprint TEXT PRIMARY KEY,
                    workspace_id TEXT NOT NULL,
                    expires_at INTEGER NOT NULL
                )
                """
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, timeout=5)
        connection.execute("PRAGMA journal_mode=WAL")
        return connection

    def save(self, workspace_id: str, snapshot: Mapping[str, Any]) -> int:
        encoded = json.dumps(snapshot, ensure_ascii=False, separators=(",", ":"))
        encrypted = self.cipher.encrypt(encoded)
        saved_at = int(snapshot.get("saved_at", time.time()))
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO workspace_snapshots(workspace_id, payload, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(workspace_id) DO UPDATE SET
                    payload=excluded.payload,
                    updated_at=excluded.updated_at
                """,
                (workspace_id, encrypted, saved_at),
            )
        return saved_at

    def load(self, workspace_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload FROM workspace_snapshots WHERE workspace_id = ?",
                (workspace_id,),
            ).fetchone()
        if not row:
            return None
        return json.loads(self.cipher.decrypt(row[0]))

    def clear(self, workspace_id: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM workspace_snapshots WHERE workspace_id = ?",
                (workspace_id,),
            )

    def save_browser_grant(
        self,
        browser_fingerprint: str,
        workspace_id: str,
        expires_at: int,
    ) -> None:
        if not browser_fingerprint or not workspace_id:
            return
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO browser_grants(browser_fingerprint, workspace_id, expires_at)
                VALUES (?, ?, ?)
                ON CONFLICT(browser_fingerprint) DO UPDATE SET
                    workspace_id=excluded.workspace_id,
                    expires_at=excluded.expires_at
                """,
                (browser_fingerprint, workspace_id, int(expires_at)),
            )

    def load_browser_grant(
        self,
        browser_fingerprint: str,
        *,
        now: int | None = None,
    ) -> str | None:
        if not browser_fingerprint:
            return None
        current = int(time.time()) if now is None else int(now)
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM browser_grants WHERE expires_at < ?",
                (current,),
            )
            row = connection.execute(
                """
                SELECT workspace_id FROM browser_grants
                WHERE browser_fingerprint = ? AND expires_at >= ?
                """,
                (browser_fingerprint, current),
            ).fetchone()
        return str(row[0]) if row else None

    def revoke_browser_grant(self, browser_fingerprint: str) -> None:
        if not browser_fingerprint:
            return
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM browser_grants WHERE browser_fingerprint = ?",
                (browser_fingerprint,),
            )


def restore_workspace(state: MutableMapping[str, Any], store: WorkspaceStore | None = None) -> bool:
    """Restore once per Streamlit session without overwriting active widget state."""
    if state.get("_workspace_restore_checked"):
        return bool(state.get("_workspace_restored"))
    state["_workspace_restore_checked"] = True
    workspace_id = str(state.get("auth_workspace_id", "")).strip()
    if not workspace_id:
        return False
    snapshot = (store or WorkspaceStore()).load(workspace_id)
    if not snapshot or not isinstance(snapshot.get("state"), dict):
        return False
    for key, value in snapshot["state"].items():
        if key in RECOVERABLE_KEYS and key not in state:
            state[key] = value
    # Streamlit widgets own their keyed values. Hydrate those keys before the
    # Analyze tab renders, otherwise blank widgets overwrite the restored
    # canonical resume/JD values during the same rerun.
    for canonical_key, widget_key in (("resume", "resume_raw"), ("jd", "jd_raw")):
        if widget_key not in state and canonical_key in state:
            state[widget_key] = state[canonical_key]
    state["_workspace_restored"] = True
    state["workspace_last_saved_at"] = int(snapshot.get("saved_at", 0))
    return True


def save_workspace(state: MutableMapping[str, Any], store: WorkspaceStore | None = None) -> bool:
    workspace_id = str(state.get("auth_workspace_id", "")).strip()
    if not workspace_id or not state.get("auth_authenticated"):
        return False
    snapshot = build_snapshot(state)
    digest = hashlib.sha256(
        json.dumps(snapshot["state"], ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    if digest == state.get("_workspace_snapshot_hash"):
        return False
    saved_at = (store or WorkspaceStore()).save(workspace_id, snapshot)
    state["_workspace_snapshot_hash"] = digest
    state["workspace_last_saved_at"] = saved_at
    return True


def clear_saved_workspace(state: MutableMapping[str, Any], store: WorkspaceStore | None = None) -> None:
    workspace_id = str(state.get("auth_workspace_id", "")).strip()
    if workspace_id:
        (store or WorkspaceStore()).clear(workspace_id)
    state.pop("_workspace_snapshot_hash", None)
    state.pop("workspace_last_saved_at", None)

"""SQLite repository with ownership checks and encrypted sensitive fields."""

from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

from platform_api.security import DocumentCipher


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class PlatformRepository:
    def __init__(self, db_path: str | Path, cipher: DocumentCipher):
        self.db_path = str(db_path)
        self.cipher = cipher
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.db_path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self):
        with self.connect() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version TEXT PRIMARY KEY,
                    applied_at TEXT NOT NULL
                )
                """
            )
            migrations_dir = Path(__file__).resolve().parent / "migrations"
            applied = {
                row["version"]
                for row in connection.execute(
                    "SELECT version FROM schema_migrations"
                ).fetchall()
            }
            for migration in sorted(migrations_dir.glob("*.sql")):
                if migration.name in applied:
                    continue
                connection.executescript(migration.read_text(encoding="utf-8"))
                connection.execute(
                    "INSERT INTO schema_migrations(version,applied_at) VALUES(?,?)",
                    (migration.name, utc_now()),
                )

    def audit(self, user_id: str | None, event: str, details: dict | None = None):
        safe_details = {
            key: value
            for key, value in (details or {}).items()
            if key not in {"password", "token", "content", "resume", "job_description"}
        }
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO audit_events(user_id,event,details_json,created_at) VALUES(?,?,?,?)",
                (user_id, event, json.dumps(safe_details), utc_now()),
            )

    def create_user(
        self, email: str, password_salt: str, password_hash: str
    ) -> dict[str, Any]:
        user_id = str(uuid.uuid4())
        now = utc_now()
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO users(id,email,password_salt,password_hash,created_at,updated_at)
                VALUES(?,?,?,?,?,?)
                """,
                (user_id, email.lower(), password_salt, password_hash, now, now),
            )
            connection.execute(
                "INSERT INTO profiles(user_id,created_at,updated_at) VALUES(?,?,?)",
                (user_id, now, now),
            )
        self.audit(user_id, "account.created")
        return {"id": user_id, "email": email.lower(), "retention_days": 90}

    def get_user_by_email(self, email: str, include_secret: bool = False) -> dict | None:
        columns = (
            "id,email,retention_days,created_at,password_salt,password_hash"
            if include_secret
            else "id,email,retention_days,created_at"
        )
        with self.connect() as connection:
            row = connection.execute(
                f"SELECT {columns} FROM users WHERE email=? AND deleted_at IS NULL",
                (email.lower(),),
            ).fetchone()
        return dict(row) if row else None

    def get_user(self, user_id: str) -> dict | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT id,email,retention_days,created_at
                FROM users WHERE id=? AND deleted_at IS NULL
                """,
                (user_id,),
            ).fetchone()
        return dict(row) if row else None

    def get_profile(self, user_id: str) -> dict:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM profiles WHERE user_id=?", (user_id,)
            ).fetchone()
        if not row:
            raise KeyError("Profile not found.")
        result = dict(row)
        result["master_resume"] = self.cipher.decrypt(result.pop("master_resume"))
        result["preferences"] = json.loads(result.pop("preferences_json") or "{}")
        return result

    def update_profile(
        self,
        user_id: str,
        *,
        display_name: str,
        headline: str,
        master_resume: str,
        preferences: dict,
    ) -> dict:
        now = utc_now()
        with self.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE profiles SET display_name=?,headline=?,master_resume=?,
                    preferences_json=?,updated_at=? WHERE user_id=?
                """,
                (
                    display_name,
                    headline,
                    self.cipher.encrypt(master_resume),
                    json.dumps(preferences),
                    now,
                    user_id,
                ),
            )
            if cursor.rowcount != 1:
                raise KeyError("Profile not found.")
        self.audit(user_id, "profile.updated")
        return self.get_profile(user_id)

    def create_application(
        self, user_id: str, company: str, role: str, job_description: str
    ) -> dict:
        app_id = str(uuid.uuid4())
        now = utc_now()
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO applications(
                    id,user_id,company,role,job_description,created_at,updated_at
                ) VALUES(?,?,?,?,?,?,?)
                """,
                (
                    app_id,
                    user_id,
                    company,
                    role,
                    self.cipher.encrypt(job_description),
                    now,
                    now,
                ),
            )
        self.audit(user_id, "application.created", {"application_id": app_id})
        return self.get_application(user_id, app_id)

    def get_application(self, user_id: str, app_id: str) -> dict:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM applications
                WHERE id=? AND user_id=? AND deleted_at IS NULL
                """,
                (app_id, user_id),
            ).fetchone()
        if not row:
            raise KeyError("Application not found.")
        result = dict(row)
        result["job_description"] = self.cipher.decrypt(result["job_description"])
        return result

    def list_applications(self, user_id: str) -> list[dict]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT id,company,role,status,created_at,updated_at
                FROM applications WHERE user_id=? AND deleted_at IS NULL
                ORDER BY updated_at DESC
                """,
                (user_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def update_application(
        self,
        user_id: str,
        app_id: str,
        *,
        company: str,
        role: str,
        status: str,
        job_description: str,
    ) -> dict:
        with self.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE applications SET company=?,role=?,status=?,
                    job_description=?,updated_at=?
                WHERE id=? AND user_id=? AND deleted_at IS NULL
                """,
                (
                    company,
                    role,
                    status,
                    self.cipher.encrypt(job_description),
                    utc_now(),
                    app_id,
                    user_id,
                ),
            )
            if cursor.rowcount != 1:
                raise KeyError("Application not found.")
        self.audit(user_id, "application.updated", {"application_id": app_id})
        return self.get_application(user_id, app_id)

    def create_version(
        self,
        user_id: str,
        app_id: str,
        kind: str,
        label: str,
        content: str,
        metadata: dict,
    ) -> dict:
        self.get_application(user_id, app_id)
        version_id = str(uuid.uuid4())
        now = utc_now()
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO document_versions(
                    id,user_id,application_id,kind,label,content,metadata_json,created_at
                ) VALUES(?,?,?,?,?,?,?,?)
                """,
                (
                    version_id,
                    user_id,
                    app_id,
                    kind,
                    label,
                    self.cipher.encrypt(content),
                    json.dumps(metadata),
                    now,
                ),
            )
        self.audit(
            user_id,
            "document.version_created",
            {"application_id": app_id, "version_id": version_id, "kind": kind},
        )
        return self.get_version(user_id, version_id)

    def get_version(self, user_id: str, version_id: str) -> dict:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM document_versions WHERE id=? AND user_id=?",
                (version_id, user_id),
            ).fetchone()
        if not row:
            raise KeyError("Document version not found.")
        result = dict(row)
        result["content"] = self.cipher.decrypt(result["content"])
        result["metadata"] = json.loads(result.pop("metadata_json") or "{}")
        return result

    def list_versions(self, user_id: str, app_id: str) -> list[dict]:
        self.get_application(user_id, app_id)
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT id,application_id,kind,label,metadata_json,created_at
                FROM document_versions WHERE user_id=? AND application_id=?
                ORDER BY created_at DESC
                """,
                (user_id, app_id),
            ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["metadata"] = json.loads(item.pop("metadata_json") or "{}")
            result.append(item)
        return result

    def create_job(
        self, user_id: str, app_id: str | None, kind: str, payload: dict
    ) -> dict:
        if app_id:
            self.get_application(user_id, app_id)
        job_id = str(uuid.uuid4())
        now = utc_now()
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO jobs(
                    id,user_id,application_id,kind,status,payload,created_at,updated_at
                ) VALUES(?,?,?,?,?,?,?,?)
                """,
                (
                    job_id,
                    user_id,
                    app_id,
                    kind,
                    "queued",
                    self.cipher.encrypt(json.dumps(payload)),
                    now,
                    now,
                ),
            )
        # Inputs can contain an applicant's full resume and job description.
        # Keep them encrypted server-side instead of echoing them in the
        # public job response.
        return self.get_job(user_id, job_id, include_payload=False)

    def get_job(
        self, user_id: str, job_id: str, include_payload: bool = False
    ) -> dict:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM jobs WHERE id=? AND user_id=?", (job_id, user_id)
            ).fetchone()
        if not row:
            raise KeyError("Job not found.")
        result = dict(row)
        payload = json.loads(self.cipher.decrypt(result.pop("payload")))
        result["payload"] = payload if include_payload else None
        result["result"] = (
            json.loads(self.cipher.decrypt(result["result"]))
            if result.get("result")
            else None
        )
        return result

    def update_job(
        self, job_id: str, status: str, result: dict | None = None, error: str = ""
    ):
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE jobs SET status=?,result=?,error=?,updated_at=? WHERE id=?
                """,
                (
                    status,
                    self.cipher.encrypt(json.dumps(result)) if result is not None else None,
                    error[:500],
                    utc_now(),
                    job_id,
                ),
            )

    def claim_next_job(self) -> dict | None:
        """Atomically claim one queued job for an external worker."""
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            # Recover work abandoned by a worker that terminated after claiming
            # it. Deterministic ATS jobs are short, so a 15-minute lease leaves
            # ample room while preventing jobs from remaining stuck forever.
            stale_before = (
                datetime.now(timezone.utc) - timedelta(minutes=15)
            ).isoformat()
            connection.execute(
                """
                UPDATE jobs SET status='queued',updated_at=?
                WHERE status='running' AND updated_at<?
                """,
                (utc_now(), stale_before),
            )
            row = connection.execute(
                """
                SELECT id,user_id,application_id,kind,payload
                FROM jobs WHERE status='queued'
                ORDER BY created_at ASC LIMIT 1
                """
            ).fetchone()
            if not row:
                return None
            cursor = connection.execute(
                """
                UPDATE jobs SET status='running',updated_at=?
                WHERE id=? AND status='queued'
                """,
                (utc_now(), row["id"]),
            )
            if cursor.rowcount != 1:
                return None
            result = dict(row)
            result["payload"] = json.loads(self.cipher.decrypt(result["payload"]))
            return result

    def update_retention(self, user_id: str, days: int):
        with self.connect() as connection:
            connection.execute(
                "UPDATE users SET retention_days=?,updated_at=? WHERE id=?",
                (days, utc_now(), user_id),
            )
        self.audit(user_id, "privacy.retention_updated", {"days": days})

    def export_user_data(self, user_id: str) -> dict:
        user = self.get_user(user_id)
        if not user:
            raise KeyError("User not found.")
        profile = self.get_profile(user_id)
        applications = self.list_applications(user_id)
        for application in applications:
            full = self.get_application(user_id, application["id"])
            application["job_description"] = full["job_description"]
            application["versions"] = [
                self.get_version(user_id, item["id"])
                for item in self.list_versions(user_id, application["id"])
            ]
        self.audit(user_id, "privacy.exported")
        return {
            "exported_at": utc_now(),
            "user": user,
            "profile": profile,
            "applications": applications,
        }

    def delete_account(self, user_id: str):
        with self.connect() as connection:
            connection.execute("DELETE FROM users WHERE id=?", (user_id,))

    def enforce_retention(self) -> int:
        now = datetime.now(timezone.utc)
        removed = 0
        with self.connect() as connection:
            users = connection.execute(
                "SELECT id,retention_days FROM users WHERE deleted_at IS NULL"
            ).fetchall()
            for user in users:
                cutoff = (now - timedelta(days=int(user["retention_days"]))).isoformat()
                cursor = connection.execute(
                    """
                    DELETE FROM jobs
                    WHERE user_id=? AND created_at<? AND status IN ('complete','failed')
                    """,
                    (user["id"], cutoff),
                )
                removed += cursor.rowcount
        return removed

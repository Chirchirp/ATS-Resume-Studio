import sqlite3
import tempfile
import time
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from platform_api.jobs import JobRunner
from platform_api.main import create_app


AUTH_SECRET = "auth-secret-for-tests-" + "a" * 40
DATA_SECRET = "data-secret-for-tests-" + "b" * 40
PASSWORD = "Correct-Horse-Battery-42"

JD = """\
Data Analyst
Requirements:
- SQL and Excel are required.
- Smartsheet is preferred.
Responsibilities:
- Build management reports and validate data quality.
"""

RESUME = """\
Jane Doe
jane@example.com
SKILLS
SQL, Excel
EXPERIENCE
Analyst | Acme | 2022 - Present
- Built 8 SQL management reports and reduced preparation time by 30%.
EDUCATION
BSc Statistics | University | 2021
"""


class PlatformApiTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.temp_dir.name) / "platform.db")
        self.app = create_app(
            db_path=self.db_path,
            auth_secret=AUTH_SECRET,
            data_secret=DATA_SECRET,
        )
        self.client_context = TestClient(self.app)
        self.client = self.client_context.__enter__()
        response = self.client.post(
            "/v1/auth/register",
            json={"email": "jane@example.com", "password": PASSWORD},
        )
        self.assertEqual(response.status_code, 201)
        self.token = response.json()["access_token"]
        self.headers = {"Authorization": f"Bearer {self.token}"}

    def tearDown(self):
        self.client_context.__exit__(None, None, None)
        self.temp_dir.cleanup()

    def _application(self):
        response = self.client.post(
            "/v1/applications",
            headers=self.headers,
            json={
                "company": "GrowCo",
                "role": "Data Analyst",
                "job_description": JD,
            },
        )
        self.assertEqual(response.status_code, 201)
        return response.json()

    def test_profile_and_application_content_is_encrypted_at_rest(self):
        profile = self.client.put(
            "/v1/profile",
            headers=self.headers,
            json={
                "display_name": "Jane Doe",
                "headline": "Data Analyst",
                "master_resume": RESUME,
                "preferences": {"domain": "data_analytics"},
            },
        )
        self.assertEqual(profile.status_code, 200)
        application = self._application()
        self.assertEqual(application["job_description"], JD)

        connection = sqlite3.connect(self.db_path)
        raw_resume = connection.execute(
            "SELECT master_resume FROM profiles"
        ).fetchone()[0]
        raw_jd = connection.execute(
            "SELECT job_description FROM applications"
        ).fetchone()[0]
        connection.close()
        self.assertNotIn(b"Jane Doe", raw_resume)
        self.assertNotIn(b"Smartsheet", raw_jd)

    def test_ownership_blocks_cross_account_access(self):
        application = self._application()
        other = self.client.post(
            "/v1/auth/register",
            json={"email": "other@example.com", "password": PASSWORD},
        )
        other_headers = {
            "Authorization": f"Bearer {other.json()['access_token']}"
        }
        response = self.client.get(
            f"/v1/applications/{application['id']}",
            headers=other_headers,
        )
        self.assertEqual(response.status_code, 404)

    def test_versioning_and_background_alignment_job(self):
        application = self._application()
        version = self.client.post(
            f"/v1/applications/{application['id']}/versions",
            headers=self.headers,
            json={
                "kind": "resume",
                "label": "Data analytics version",
                "content": RESUME,
                "metadata": {"strategy": "direct_fit"},
            },
        )
        self.assertEqual(version.status_code, 201)
        versions = self.client.get(
            f"/v1/applications/{application['id']}/versions",
            headers=self.headers,
        ).json()
        self.assertEqual(len(versions), 1)

        queued = self.client.post(
            "/v1/jobs/alignment",
            headers=self.headers,
            json={
                "application_id": application["id"],
                "job_description": JD,
                "resume": RESUME,
            },
        )
        self.assertEqual(queued.status_code, 202)
        self.assertIsNone(queued.json()["payload"])
        job_id = queued.json()["id"]
        job = None
        for _ in range(60):
            job = self.client.get(
                f"/v1/jobs/{job_id}", headers=self.headers
            ).json()
            if job["status"] in {"complete", "failed"}:
                break
            time.sleep(0.03)
        self.assertEqual(job["status"], "complete")
        self.assertIn("alignment", job["result"])
        self.assertIn("evidence", job["result"])

    def test_studio_and_database_migrations_are_available(self):
        studio = self.client.get("/studio")
        self.assertEqual(studio.status_code, 200)
        self.assertIn("ATS Resume Studio", studio.text)
        self.assertEqual(
            self.client.get("/v1/me").status_code,
            401,
        )

        connection = sqlite3.connect(self.db_path)
        migrations = connection.execute(
            "SELECT version FROM schema_migrations ORDER BY version"
        ).fetchall()
        connection.close()
        self.assertEqual(migrations, [("001_initial.sql",)])

    def test_external_worker_can_claim_and_complete_queued_work(self):
        user_id = self.client.get("/v1/me", headers=self.headers).json()["id"]
        repository = self.app.state.repository
        queued = repository.create_job(
            user_id,
            None,
            "alignment",
            {"job_description": JD, "resume": RESUME},
        )
        claimed = repository.claim_next_job()
        self.assertEqual(claimed["id"], queued["id"])
        self.assertEqual(claimed["payload"]["resume"], RESUME)

        worker = JobRunner(repository, workers=1, inline=False)
        try:
            worker.execute_claimed(claimed)
        finally:
            worker.shutdown()
        completed = repository.get_job(user_id, queued["id"])
        self.assertEqual(completed["status"], "complete")

    def test_privacy_export_retention_and_account_deletion(self):
        self._application()
        retention = self.client.put(
            "/v1/privacy/retention",
            headers=self.headers,
            json={"retention_days": 30},
        )
        self.assertEqual(retention.json()["retention_days"], 30)
        exported = self.client.get(
            "/v1/privacy/export", headers=self.headers
        )
        self.assertEqual(exported.status_code, 200)
        self.assertEqual(len(exported.json()["applications"]), 1)

        deleted = self.client.request(
            "DELETE",
            "/v1/privacy/account",
            headers=self.headers,
            json={
                "password": PASSWORD,
                "confirmation": "DELETE MY ACCOUNT",
            },
        )
        self.assertEqual(deleted.status_code, 204)
        self.assertEqual(
            self.client.get("/v1/me", headers=self.headers).status_code,
            401,
        )


if __name__ == "__main__":
    unittest.main()

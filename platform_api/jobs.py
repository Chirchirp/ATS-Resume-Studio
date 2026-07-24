"""Persistent asynchronous execution for deterministic analysis jobs."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict

from platform_api.storage import PlatformRepository
from utils.ats_engine import analyze_alignment
from utils.evidence_engine import (
    build_evidence_ledger,
    build_evidence_matrix,
    validate_generated_claims,
)


class JobRunner:
    def __init__(
        self,
        repository: PlatformRepository,
        workers: int = 2,
        inline: bool = True,
    ):
        self.repository = repository
        self.inline = inline
        self.executor = ThreadPoolExecutor(
            max_workers=max(1, workers),
            thread_name_prefix="ats-platform-job",
        )

    def submit(
        self,
        user_id: str,
        kind: str,
        payload: dict,
        application_id: str | None = None,
    ) -> dict:
        job = self.repository.create_job(
            user_id, application_id, kind, payload
        )
        if self.inline:
            self.executor.submit(self._execute, user_id, job["id"], kind, payload)
        return job

    def _execute(self, user_id: str, job_id: str, kind: str, payload: dict):
        if self.inline:
            self.repository.update_job(job_id, "running")
        try:
            jd = payload["job_description"]
            resume = payload["resume"]
            if kind == "alignment":
                report = analyze_alignment(jd, resume)
                ledger = build_evidence_ledger(resume)
                matrix = build_evidence_matrix(jd, ledger)
                result = {
                    "alignment": asdict(report),
                    "evidence": {
                        "source_hash": ledger.source_hash,
                        "items": [asdict(item) for item in ledger.items],
                        "matrix": [asdict(row) for row in matrix.rows],
                    },
                }
            elif kind == "truth_audit":
                ledger = build_evidence_ledger(resume)
                validation = validate_generated_claims(
                    payload["generated_document"], ledger, jd
                )
                result = asdict(validation)
                result["is_download_safe"] = validation.is_download_safe
                result["support_rate"] = validation.support_rate
            else:
                raise ValueError("Unsupported job type.")
            self.repository.update_job(job_id, "complete", result=result)
            self.repository.audit(
                user_id, "job.completed", {"job_id": job_id, "kind": kind}
            )
        except Exception as exc:
            self.repository.update_job(
                job_id, "failed", error=f"{type(exc).__name__}: {str(exc)[:350]}"
            )

    def execute_claimed(self, job: dict):
        self._execute(job["user_id"], job["id"], job["kind"], job["payload"])

    def shutdown(self):
        self.executor.shutdown(wait=True, cancel_futures=False)

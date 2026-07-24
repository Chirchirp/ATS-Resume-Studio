"""External durable-job worker for multi-process deployments."""

from __future__ import annotations

import os
import signal
import time
from pathlib import Path

from platform_api.jobs import JobRunner
from platform_api.security import DocumentCipher, SecurityConfigurationError
from platform_api.storage import PlatformRepository


def run_worker():
    data_secret = os.environ.get("ATS_DATA_SECRET", "")
    if not data_secret:
        raise SecurityConfigurationError("ATS_DATA_SECRET is required.")
    repository = PlatformRepository(
        os.environ.get(
            "ATS_PLATFORM_DB",
            str(Path(__file__).resolve().parent.parent / "data" / "platform.db"),
        ),
        DocumentCipher(data_secret),
    )
    runner = JobRunner(repository, workers=1, inline=False)
    active = True

    def stop(*_):
        nonlocal active
        active = False

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    try:
        while active:
            job = repository.claim_next_job()
            if job:
                runner.execute_claimed(job)
            else:
                time.sleep(0.5)
    finally:
        runner.shutdown()


if __name__ == "__main__":
    run_worker()


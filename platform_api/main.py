"""FastAPI service for authenticated, persistent ATS Resume Studio workflows."""

from __future__ import annotations

import os
import sqlite3
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.staticfiles import StaticFiles

from platform_api.jobs import JobRunner
from platform_api.schemas import (
    AnalysisJobCreate,
    ApplicationCreate,
    ApplicationUpdate,
    DeleteAccountRequest,
    LoginRequest,
    ProfileUpdate,
    RegisterRequest,
    RetentionUpdate,
    TokenResponse,
    TruthAuditJobCreate,
    VersionCreate,
)
from platform_api.security import (
    DocumentCipher,
    SecurityConfigurationError,
    TokenClaims,
    TokenSigner,
    hash_password,
    verify_password,
)
from platform_api.storage import PlatformRepository


class LoginRateLimiter:
    def __init__(self, limit: int = 8, window_seconds: int = 15 * 60):
        self.limit = limit
        self.window_seconds = window_seconds
        self._attempts: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def check(self, key: str):
        now = time.time()
        with self._lock:
            attempts = [
                value
                for value in self._attempts.get(key, [])
                if value > now - self.window_seconds
            ]
            if len(attempts) >= self.limit:
                raise HTTPException(
                    status_code=429,
                    detail="Too many authentication attempts. Try again later.",
                )
            attempts.append(now)
            self._attempts[key] = attempts

    def clear(self, key: str):
        with self._lock:
            self._attempts.pop(key, None)


def create_app(
    *,
    db_path: str | None = None,
    auth_secret: str | None = None,
    data_secret: str | None = None,
) -> FastAPI:
    auth_secret = auth_secret or os.environ.get("ATS_AUTH_SECRET", "")
    data_secret = data_secret or os.environ.get("ATS_DATA_SECRET", "")
    if not auth_secret or not data_secret:
        raise SecurityConfigurationError(
            "ATS_AUTH_SECRET and ATS_DATA_SECRET are required."
        )

    repository = PlatformRepository(
        db_path
        or os.environ.get(
            "ATS_PLATFORM_DB",
            str(Path(__file__).resolve().parent.parent / "data" / "platform.db"),
        ),
        DocumentCipher(data_secret),
    )
    repository.enforce_retention()
    signer = TokenSigner(auth_secret)
    runner = JobRunner(
        repository,
        workers=int(os.environ.get("ATS_JOB_WORKERS", "2")),
        inline=os.environ.get("ATS_INLINE_JOBS", "true").lower()
        in {"1", "true", "yes"},
    )
    limiter = LoginRateLimiter()
    bearer = HTTPBearer(auto_error=False)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        yield
        runner.shutdown()

    app = FastAPI(
        title="ATS Resume Studio Platform API",
        version="1.0.0",
        docs_url="/api/docs",
        redoc_url=None,
        lifespan=lifespan,
    )
    app.state.repository = repository
    app.state.signer = signer
    app.state.runner = runner

    origins = [
        value.strip()
        for value in os.environ.get(
            "ATS_ALLOWED_ORIGINS", "http://localhost:8000,http://127.0.0.1:8000"
        ).split(",")
        if value.strip()
    ]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=["Authorization", "Content-Type"],
    )

    static_dir = Path(__file__).resolve().parent / "static"
    app.mount("/assets", StaticFiles(directory=static_dir), name="assets")

    def current_user(
        credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    ) -> TokenClaims:
        if not credentials or credentials.scheme.lower() != "bearer":
            raise HTTPException(status_code=401, detail="Authentication required.")
        try:
            claims = signer.verify(credentials.credentials)
        except ValueError as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc
        if not repository.get_user(claims.user_id):
            raise HTTPException(status_code=401, detail="Account is unavailable.")
        return claims

    @app.get("/", include_in_schema=False)
    def root():
        return RedirectResponse("/studio")

    @app.get("/studio", include_in_schema=False)
    def studio():
        return FileResponse(static_dir / "index.html")

    @app.get("/health")
    def health():
        return {"status": "ok", "service": "ats-platform", "version": "1.0.0"}

    @app.post("/v1/auth/register", response_model=TokenResponse, status_code=201)
    def register(payload: RegisterRequest, request: Request):
        key = f"{request.client.host if request.client else 'unknown'}:{payload.email.lower()}"
        limiter.check(key)
        try:
            salt, digest = hash_password(payload.password)
            user = repository.create_user(payload.email, salt, digest)
        except sqlite3.IntegrityError as exc:
            raise HTTPException(status_code=409, detail="Account already exists.") from exc
        limiter.clear(key)
        token = signer.issue(user["id"], user["email"])
        claims = signer.verify(token)
        return TokenResponse(access_token=token, expires_at=claims.expires_at)

    @app.post("/v1/auth/login", response_model=TokenResponse)
    def login(payload: LoginRequest, request: Request):
        key = f"{request.client.host if request.client else 'unknown'}:{payload.email.lower()}"
        limiter.check(key)
        user = repository.get_user_by_email(payload.email, include_secret=True)
        if not user or not verify_password(
            payload.password, user["password_salt"], user["password_hash"]
        ):
            raise HTTPException(status_code=401, detail="Invalid credentials.")
        limiter.clear(key)
        token = signer.issue(user["id"], user["email"])
        claims = signer.verify(token)
        repository.audit(user["id"], "auth.login")
        return TokenResponse(access_token=token, expires_at=claims.expires_at)

    @app.get("/v1/me")
    def me(user: TokenClaims = Depends(current_user)):
        return repository.get_user(user.user_id)

    @app.get("/v1/profile")
    def get_profile(user: TokenClaims = Depends(current_user)):
        return repository.get_profile(user.user_id)

    @app.put("/v1/profile")
    def update_profile(
        payload: ProfileUpdate, user: TokenClaims = Depends(current_user)
    ):
        return repository.update_profile(
            user.user_id,
            display_name=payload.display_name,
            headline=payload.headline,
            master_resume=payload.master_resume,
            preferences=payload.preferences,
        )

    @app.get("/v1/applications")
    def list_applications(user: TokenClaims = Depends(current_user)):
        return repository.list_applications(user.user_id)

    @app.post("/v1/applications", status_code=201)
    def create_application(
        payload: ApplicationCreate, user: TokenClaims = Depends(current_user)
    ):
        return repository.create_application(
            user.user_id,
            payload.company,
            payload.role,
            payload.job_description,
        )

    @app.get("/v1/applications/{application_id}")
    def get_application(
        application_id: str, user: TokenClaims = Depends(current_user)
    ):
        try:
            return repository.get_application(user.user_id, application_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.put("/v1/applications/{application_id}")
    def update_application(
        application_id: str,
        payload: ApplicationUpdate,
        user: TokenClaims = Depends(current_user),
    ):
        try:
            return repository.update_application(
                user.user_id,
                application_id,
                company=payload.company,
                role=payload.role,
                status=payload.status,
                job_description=payload.job_description,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/v1/applications/{application_id}/versions")
    def list_versions(
        application_id: str, user: TokenClaims = Depends(current_user)
    ):
        try:
            return repository.list_versions(user.user_id, application_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/v1/applications/{application_id}/versions", status_code=201)
    def create_version(
        application_id: str,
        payload: VersionCreate,
        user: TokenClaims = Depends(current_user),
    ):
        try:
            return repository.create_version(
                user.user_id,
                application_id,
                payload.kind,
                payload.label,
                payload.content,
                payload.metadata,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/v1/versions/{version_id}")
    def get_version(
        version_id: str, user: TokenClaims = Depends(current_user)
    ):
        try:
            return repository.get_version(user.user_id, version_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/v1/jobs/alignment", status_code=202)
    def alignment_job(
        payload: AnalysisJobCreate, user: TokenClaims = Depends(current_user)
    ):
        return runner.submit(
            user.user_id,
            "alignment",
            payload.model_dump(exclude={"application_id"}),
            payload.application_id,
        )

    @app.post("/v1/jobs/truth-audit", status_code=202)
    def truth_audit_job(
        payload: TruthAuditJobCreate, user: TokenClaims = Depends(current_user)
    ):
        return runner.submit(
            user.user_id,
            "truth_audit",
            payload.model_dump(exclude={"application_id"}),
            payload.application_id,
        )

    @app.get("/v1/jobs/{job_id}")
    def get_job(job_id: str, user: TokenClaims = Depends(current_user)):
        try:
            return repository.get_job(user.user_id, job_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.put("/v1/privacy/retention")
    def update_retention(
        payload: RetentionUpdate, user: TokenClaims = Depends(current_user)
    ):
        repository.update_retention(user.user_id, payload.retention_days)
        return {"retention_days": payload.retention_days}

    @app.get("/v1/privacy/export")
    def privacy_export(user: TokenClaims = Depends(current_user)):
        return repository.export_user_data(user.user_id)

    @app.delete("/v1/privacy/account", status_code=status.HTTP_204_NO_CONTENT)
    def delete_account(
        payload: DeleteAccountRequest, user: TokenClaims = Depends(current_user)
    ):
        account = repository.get_user_by_email(user.email, include_secret=True)
        if not account or not verify_password(
            payload.password, account["password_salt"], account["password_hash"]
        ):
            raise HTTPException(status_code=401, detail="Password confirmation failed.")
        repository.delete_account(user.user_id)
        return None

    return app

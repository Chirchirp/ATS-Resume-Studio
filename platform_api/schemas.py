"""Validated API request contracts."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, EmailStr, Field


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=10, max_length=200)


class LoginRequest(RegisterRequest):
    pass


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_at: int


class ProfileUpdate(BaseModel):
    display_name: str = Field(default="", max_length=120)
    headline: str = Field(default="", max_length=240)
    master_resume: str = Field(default="", max_length=100_000)
    preferences: dict[str, Any] = Field(default_factory=dict)


class ApplicationCreate(BaseModel):
    company: str = Field(default="", max_length=200)
    role: str = Field(min_length=1, max_length=200)
    job_description: str = Field(min_length=20, max_length=100_000)


class ApplicationUpdate(ApplicationCreate):
    status: Literal[
        "draft",
        "applied",
        "screening",
        "interview",
        "offer",
        "rejected",
        "withdrawn",
    ] = "draft"


class VersionCreate(BaseModel):
    kind: Literal["resume", "cover_letter", "notes"] = "resume"
    label: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1, max_length=150_000)
    metadata: dict[str, Any] = Field(default_factory=dict)


class AnalysisJobCreate(BaseModel):
    application_id: str | None = None
    job_description: str = Field(min_length=20, max_length=100_000)
    resume: str = Field(min_length=20, max_length=150_000)


class TruthAuditJobCreate(AnalysisJobCreate):
    generated_document: str = Field(min_length=20, max_length=150_000)


class RetentionUpdate(BaseModel):
    retention_days: int = Field(ge=7, le=3650)


class DeleteAccountRequest(BaseModel):
    password: str = Field(min_length=10, max_length=200)
    confirmation: Literal["DELETE MY ACCOUNT"]


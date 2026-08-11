"""Deterministic recruiter-readability and keyword X-ray checks.

These checks do not ask an LLM to guess whether a resume is good. They inspect
the same parsed resume and job profile used by the single alignment scorer.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from utils.ats_engine import AlignmentReport, METRIC_RE, analyze_alignment


GENERIC_PHRASES = (
    "results-driven",
    "dynamic professional",
    "proven track record",
    "seasoned professional",
    "highly motivated",
    "proven ability",
    "professional strengths include",
    "selected contributions include",
    "career evidence shows",
    "demonstrated expertise in",
)


@dataclass(frozen=True)
class KeywordBucket:
    label: str
    supported: tuple[str, ...]
    gaps: tuple[str, ...]


@dataclass(frozen=True)
class KeywordXRayReport:
    buckets: tuple[KeywordBucket, ...]
    exact_phrases: tuple[str, ...]
    placement_sections: tuple[str, ...]

    @property
    def supported_count(self) -> int:
        return sum(len(bucket.supported) for bucket in self.buckets)

    @property
    def gap_count(self) -> int:
        return sum(len(bucket.gaps) for bucket in self.buckets)


@dataclass(frozen=True)
class ReadStage:
    name: str
    timebox: str
    score: int
    passed: bool
    strengths: tuple[str, ...]
    fixes: tuple[str, ...]


@dataclass(frozen=True)
class ThreeStageAudit:
    stages: tuple[ReadStage, ...]
    overall_score: int
    generic_phrases: tuple[str, ...]

    @property
    def passed(self) -> bool:
        return all(stage.passed for stage in self.stages)


def _requirement_bucket(label: str, requirements, missing: list[str]) -> KeywordBucket:
    missing_keys = {value.strip().casefold() for value in missing}
    supported: list[str] = []
    gaps: list[str] = []
    for requirement in requirements:
        target = gaps if requirement.text.strip().casefold() in missing_keys else supported
        target.append(requirement.text)
    return KeywordBucket(label, tuple(supported), tuple(gaps))


def build_keyword_xray(alignment: AlignmentReport) -> KeywordXRayReport:
    """Separate preferred, required, and technical signals with source status."""
    preferred = _requirement_bucket(
        "1 · Preferred qualifications",
        alignment.job.preferred,
        alignment.missing_preferred,
    )
    required = _requirement_bucket(
        "2 · Hard requirements",
        alignment.job.required,
        alignment.missing_required,
    )
    matched_keys = {value.casefold() for value in alignment.matched_terms}
    technical_terms = list(dict.fromkeys(alignment.job.skills + alignment.job.phrases))
    supported_technical = tuple(
        term for term in technical_terms if term.casefold() in matched_keys
    )
    missing_keys = {value.casefold() for value in alignment.missing_terms}
    missing_technical = tuple(
        term for term in technical_terms if term.casefold() in missing_keys
    )
    technical = KeywordBucket(
        "3 · Technical responsibilities",
        supported_technical,
        missing_technical,
    )
    return KeywordXRayReport(
        buckets=(preferred, required, technical),
        exact_phrases=tuple(alignment.matched_phrases),
        placement_sections=tuple(
            section
            for section, values in alignment.section_matches.items()
            if values
        ),
    )


def _summary_text(report: AlignmentReport) -> str:
    return report.resume.sections.get("summary", "").strip()


def _bullet_lines(text: str) -> list[str]:
    return [
        line.strip()
        for line in text.splitlines()
        if re.match(r"^\s*(?:[-*•▪◦●]\s+)", line)
    ]


def build_three_stage_audit(
    jd_text: str,
    resume_text: str,
    *,
    truth_validation: Any = None,
) -> ThreeStageAudit:
    """Score the 2-second skim, 10-second scan, and evidence-led study."""
    report = analyze_alignment(jd_text, resume_text)
    profile = report.resume
    upper = resume_text.upper()
    lines = [line.strip() for line in resume_text.splitlines() if line.strip()]
    summary = _summary_text(report)
    summary_sentences = len(
        [part for part in re.split(r"(?<=[.!?])\s+", summary) if part.strip()]
    )
    generic = tuple(
        phrase
        for phrase in GENERIC_PHRASES
        if re.search(r"\b" + re.escape(phrase) + r"\b", resume_text, re.I)
    )

    skim_strengths: list[str] = []
    skim_fixes: list[str] = []
    if profile.candidate_name:
        skim_strengths.append("Candidate identity leads the page.")
    else:
        skim_fixes.append("Put the candidate name first.")
    if profile.has_contact:
        skim_strengths.append("Contact details are visible in the document body.")
    else:
        skim_fixes.append("Add parseable contact details below the name.")
    if "PROFESSIONAL SUMMARY" in upper and "CORE SKILLS" in upper:
        skim_strengths.append("Summary and skills establish fit before experience detail.")
    else:
        skim_fixes.append("Place Professional Summary and Core Skills near the top.")
    first_experience = next(
        (index for index, line in enumerate(lines) if "EXPERIENCE" in line.upper()),
        10_000,
    )
    if first_experience <= 20:
        skim_strengths.append("Experience is reachable without searching the page.")
    else:
        skim_fixes.append("Move experience higher for the F-pattern skim.")
    skim_score = round(100 * len(skim_strengths) / 4)

    scan_strengths: list[str] = []
    scan_fixes: list[str] = []
    required_total = len(report.job.required)
    preferred_total = len(report.job.preferred)
    required_match = required_total - len(report.missing_required)
    preferred_match = preferred_total - len(report.missing_preferred)
    if not required_total or required_match / required_total >= 0.7:
        scan_strengths.append("Most hard requirements have visible candidate evidence.")
    else:
        scan_fixes.append("Surface supported hard-requirement evidence earlier.")
    if not preferred_total or preferred_match / preferred_total >= 0.5:
        scan_strengths.append("Preferred qualifications are visible where supported.")
    else:
        scan_fixes.append("Lead with supported preferred qualifications before duties.")
    placement = next(
        (dimension.score / dimension.maximum for dimension in report.dimensions if dimension.key == "placement"),
        0.0,
    )
    if placement >= 0.65:
        scan_strengths.append("Keywords are distributed across summary, skills, and experience.")
    else:
        scan_fixes.append("Move supported keywords into summary, skills, and role bullets.")
    bullets = _bullet_lines(resume_text)
    if len(bullets) >= max(3, len(profile.roles) * 2):
        scan_strengths.append("Responsibilities and skills are separated into scan-friendly bullets.")
    else:
        scan_fixes.append("Separate skills and role contributions into physical bullet lines.")
    scan_score = round(100 * len(scan_strengths) / 4)

    study_strengths: list[str] = []
    study_fixes: list[str] = []
    truth_safe = bool(getattr(truth_validation, "is_download_safe", False))
    if truth_validation is None:
        study_fixes.append("Run the deterministic truth audit before submission.")
    elif truth_safe:
        study_strengths.append("Candidate claims passed the deterministic truth audit.")
    else:
        study_fixes.append("Repair or verify unsupported claims before submission.")
    if summary_sentences >= 3:
        study_strengths.append("The summary provides a substantive professional narrative.")
    else:
        study_fixes.append("Build a 3–5 sentence source-backed professional narrative.")
    output_roles = len(profile.roles)
    if output_roles:
        study_strengths.append(f"The document preserves {output_roles} traceable role record(s).")
    else:
        study_fixes.append("Restore recognizable role, employer, and date records.")
    if not generic:
        study_strengths.append("No common AI-resume clichés were detected.")
    else:
        study_fixes.append("Replace generic AI phrases with observed candidate evidence.")
    metric_bullets = sum(bool(METRIC_RE.search(line)) for line in bullets)
    if metric_bullets <= max(1, output_roles * 2):
        study_strengths.append("Quantified evidence is selective rather than overused.")
    else:
        study_fixes.append("Use one verified metric-led hook per role, then vary the evidence pattern.")
    study_score = round(100 * len(study_strengths) / 5)

    stages = (
        ReadStage("Skim", "< 2 seconds", skim_score, skim_score >= 75, tuple(skim_strengths), tuple(skim_fixes)),
        ReadStage("Scan", "< 10 seconds", scan_score, scan_score >= 75, tuple(scan_strengths), tuple(scan_fixes)),
        ReadStage("Study", "> 10 seconds", study_score, study_score >= 80, tuple(study_strengths), tuple(study_fixes)),
    )
    return ThreeStageAudit(
        stages=stages,
        overall_score=round(sum(stage.score for stage in stages) / len(stages)),
        generic_phrases=generic,
    )


"""
Evidence ledger, requirement coverage, clarification, and claim validation.

The language model is never treated as the source of truth. This module builds
stable evidence IDs from candidate-provided text and uses those IDs to ground
generation and audit generated documents.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Mapping

from utils.ats_engine import (
    METRIC_RE,
    Requirement,
    ResumeProfile,
    SKILL_PHRASES,
    _content_terms,
    _normalize_term,
    _tokens,
    extract_job_profile,
    extract_resume_profile,
)


BULLET_RE = re.compile(r"^\s*[•*\-–—]\s+")
ROLE_RE = re.compile(
    r"(?:\||\b(?:19\d{2}|20\d{2})\b\s*(?:-|–|—|to)\s*"
    r"(?:present|current|19\d{2}|20\d{2})\b)",
    re.I,
)
NUMBER_RE = re.compile(r"(?:[$£€]\s*)?\b\d[\d,.]*(?:\s?%|\+)?", re.I)
CREDENTIAL_RE = re.compile(
    r"\b(?:bachelor(?:'s)?|master(?:'s)?|b\.?\s?sc|m\.?\s?sc|"
    r"b\.?\s?a|m\.?\s?a|btech|mtech|mba|phd|doctorate|diploma|degree|"
    r"certified|certification|license[sd]?)\b",
    re.I,
)


@dataclass(frozen=True)
class EvidenceItem:
    id: str
    section: str
    role: str
    text: str
    terms: tuple[str, ...]
    metrics: tuple[str, ...]
    source: str = "resume"
    verification: str = "source_explicit"
    role_id: str = ""
    item_type: str = "statement"
    source_line: int = 0


@dataclass
class EvidenceLedger:
    candidate_name: str
    items: list[EvidenceItem]
    source_hash: str
    profile: ResumeProfile | None = None

    def by_id(self) -> dict[str, EvidenceItem]:
        return {item.id: item for item in self.items}


@dataclass(frozen=True)
class RequirementEvidence:
    id: str
    requirement: str
    priority: str
    status: str
    evidence_ids: tuple[str, ...]
    matched_terms: tuple[str, ...]
    missing_terms: tuple[str, ...]
    explanation: str


@dataclass
class EvidenceMatrix:
    rows: list[RequirementEvidence]

    @property
    def covered_count(self) -> int:
        return sum(row.status in {"direct", "equivalent"} for row in self.rows)

    @property
    def missing_count(self) -> int:
        return sum(row.status == "missing" for row in self.rows)


@dataclass(frozen=True)
class ClarificationQuestion:
    id: str
    requirement_id: str
    prompt: str
    reason: str
    answer_type: str = "evidence"


@dataclass(frozen=True)
class ClaimIssue:
    claim_id: str
    severity: str
    issue_type: str
    claim: str
    detail: str


@dataclass
class ClaimValidationReport:
    claims_checked: int
    supported_claims: int
    issues: list[ClaimIssue] = field(default_factory=list)

    @property
    def is_download_safe(self) -> bool:
        return not any(issue.severity == "high" for issue in self.issues)

    @property
    def support_rate(self) -> int:
        if not self.claims_checked:
            return 0
        return round(self.supported_claims / self.claims_checked * 100)


@dataclass(frozen=True)
class RoleBulletPlan:
    """A deterministic, evidence-bounded bullet target for one source role."""

    role_id: str
    role_header: str
    target: int
    available: int
    relevance_hits: int


def _section_heading(line: str) -> str | None:
    cleaned = re.sub(r"[^a-z ]", "", line.lower()).strip()
    aliases = {
        "summary": ("summary", "profile", "objective"),
        "skills": ("skills", "competencies", "expertise", "technologies"),
        "experience": ("experience", "employment", "work history", "career history"),
        "education": ("education", "academic"),
        "certifications": ("certifications", "certificates", "licenses"),
        "projects": ("projects",),
    }
    for section, names in aliases.items():
        if any(
            cleaned == name
            or cleaned.startswith(name + " ")
            or cleaned.endswith(" " + name)
            for name in names
        ):
            return section
    return None


def _clean_evidence_line(line: str) -> str:
    return re.sub(r"\s+", " ", BULLET_RE.sub("", line)).strip()


def build_evidence_ledger(
    resume_text: str,
    clarification_answers: Mapping[str, str] | None = None,
) -> EvidenceLedger:
    """Create stable evidence from the canonical structured resume profile."""
    profile = extract_resume_profile(resume_text)
    items: list[EvidenceItem] = []

    def add_item(
        *,
        section: str,
        text: str,
        role: str = "",
        role_id: str = "",
        item_type: str = "statement",
        source_line: int = 0,
        source: str = "resume",
        verification: str = "source_explicit",
    ):
        clean = _clean_evidence_line(text)
        if len(clean) < 3:
            return
        item_id = f"E{len(items) + 1:03d}"
        items.append(
            EvidenceItem(
                id=item_id,
                section=section,
                role=role,
                text=clean,
                terms=tuple(sorted(_content_terms(clean))),
                metrics=tuple(METRIC_RE.findall(clean)),
                source=source,
                verification=verification,
                role_id=role_id,
                item_type=item_type,
                source_line=source_line,
            )
        )

    for source_line, raw_line in enumerate(
        profile.sections.get("other", "").splitlines(), start=1
    ):
        if _clean_evidence_line(raw_line) != profile.candidate_name:
            add_item(
                section="other",
                text=raw_line,
                item_type="contact_or_header",
                source_line=source_line,
            )
    for line in profile.summary_lines:
        add_item(section="summary", text=line, item_type="summary")
    for line in profile.sections.get("skills", "").splitlines():
        add_item(section="skills", text=line, item_type="skill_group")

    if profile.roles:
        represented_experience = {
            _clean_evidence_line(detail).lower()
            for role in profile.roles
            for detail in role.details
        } | {
            _clean_evidence_line(bullet.text).lower()
            for role in profile.roles
            for bullet in role.bullets
        }
        for role in profile.roles:
            for detail in role.details:
                add_item(
                    section="experience",
                    role=role.header,
                    role_id=role.id,
                    text=detail,
                    item_type="role_detail",
                    source_line=role.source_line,
                )
            for bullet in role.bullets:
                add_item(
                    section="experience",
                    role=role.header,
                    role_id=role.id,
                    text=bullet.text,
                    item_type="bullet",
                    source_line=bullet.source_line,
                )
        for line in profile.sections.get("experience", "").splitlines():
            clean = _clean_evidence_line(line)
            if not clean or clean.lower() in represented_experience:
                continue
            if any(clean.lower() in role.header.lower() for role in profile.roles):
                continue
            add_item(
                section="experience",
                text=clean,
                item_type="unassigned_experience",
            )
    else:
        for line in profile.sections.get("experience", "").splitlines():
            add_item(
                section="experience",
                text=line,
                item_type="unassigned_experience",
            )

    for project in profile.projects:
        for detail in project.details:
            add_item(
                section="projects",
                role=project.title,
                role_id=project.id,
                text=detail,
                item_type="project_detail",
                source_line=project.source_line,
            )
        for bullet in project.bullets:
            add_item(
                section="projects",
                role=project.title,
                role_id=project.id,
                text=bullet.text,
                item_type="bullet",
                source_line=bullet.source_line,
            )
    for record in profile.education_records:
        add_item(
            section="education",
            text=record.text,
            item_type="education_record",
            source_line=record.source_line,
        )
    for record in profile.certification_records:
        add_item(
            section="certifications",
            text=record.text,
            item_type="certification_record",
            source_line=record.source_line,
        )

    for question_id, answer in sorted((clarification_answers or {}).items()):
        clean = re.sub(r"\s+", " ", answer).strip()
        if not clean:
            continue
        role_id_match = re.search(r"\bROLE\d{3}\b", question_id)
        target_role = next(
            (
                role
                for role in profile.roles
                if role_id_match and role.id == role_id_match.group(0)
            ),
            None,
        )
        add_item(
            section="experience" if target_role else "clarification",
            role=target_role.header if target_role else "Candidate clarification",
            role_id=target_role.id if target_role else "",
            text=clean,
            source=question_id,
            verification="user_confirmed",
            item_type="user_confirmed",
        )

    source_material = resume_text + "\n" + "\n".join(
        f"{key}:{value}" for key, value in sorted((clarification_answers or {}).items())
    )
    return EvidenceLedger(
        candidate_name=profile.candidate_name,
        items=items,
        source_hash=hashlib.sha256(source_material.encode("utf-8")).hexdigest()[:16],
        profile=profile,
    )


def _match_requirement(requirement: Requirement, ledger: EvidenceLedger, row_id: str) -> RequirementEvidence:
    required_terms = {_normalize_term(term) for term in requirement.terms}
    ranked: list[tuple[float, EvidenceItem, set[str]]] = []
    for item in ledger.items:
        item_terms = {_normalize_term(term) for term in item.terms}
        matched = required_terms & item_terms
        ratio = len(matched) / len(required_terms) if required_terms else 0.0
        if matched:
            ranked.append((ratio, item, matched))
    demonstrated_sections = {
        "experience",
        "projects",
        "clarification",
        "education",
        "certifications",
    }
    ranked.sort(
        key=lambda value: (
            -value[0],
            0 if value[1].section in demonstrated_sections else 1,
            value[1].id,
        )
    )

    if not required_terms:
        status = "missing"
        selected: list[tuple[float, EvidenceItem, set[str]]] = []
    else:
        selected = ranked[:3]
        best = selected[0][0] if selected else 0.0
        aggregate_matched = (
            set().union(*(entry[2] for entry in selected))
            if selected
            else set()
        )
        demonstrated_matched = (
            set().union(
                *(
                    entry[2]
                    for entry in selected
                    if entry[1].section in demonstrated_sections
                )
            )
            if any(
                entry[1].section in demonstrated_sections
                for entry in selected
            )
            else set()
        )
        demonstrated_ratio = len(demonstrated_matched) / len(required_terms)
        aggregate_ratio = len(aggregate_matched) / len(required_terms)
        if demonstrated_ratio >= 0.8:
            status = "direct"
        elif aggregate_ratio >= 0.8 or best >= 0.8:
            status = "equivalent"
        elif aggregate_ratio >= 0.35 or best >= 0.35:
            status = "transferable"
        elif best > 0:
            status = "mention_only"
        else:
            status = "missing"

    matched_terms = set().union(*(entry[2] for entry in selected)) if selected else set()
    missing_terms = required_terms - matched_terms
    explanations = {
        "direct": "Strong contextual evidence appears in experience, projects, or confirmed answers.",
        "equivalent": "The terminology is present, but evidence is concentrated in a skills or general section.",
        "transferable": "Some relevant evidence exists, but it does not cover most of the requirement.",
        "mention_only": "A related term is mentioned without enough contextual proof.",
        "missing": "No supporting candidate evidence was found.",
    }
    return RequirementEvidence(
        id=row_id,
        requirement=requirement.text,
        priority=requirement.priority,
        status=status,
        evidence_ids=tuple(entry[1].id for entry in selected),
        matched_terms=tuple(sorted(matched_terms)),
        missing_terms=tuple(sorted(missing_terms)),
        explanation=explanations[status],
    )


def build_evidence_matrix(jd_text: str, ledger: EvidenceLedger) -> EvidenceMatrix:
    """Connect each extracted requirement to candidate evidence IDs."""
    job = extract_job_profile(jd_text)
    requirements = job.required + job.preferred
    seen: set[str] = set()
    rows: list[RequirementEvidence] = []
    for requirement in requirements:
        key = requirement.text.lower()
        if key in seen:
            continue
        seen.add(key)
        rows.append(_match_requirement(requirement, ledger, f"R{len(rows) + 1:03d}"))
    return EvidenceMatrix(rows=rows)


def generate_clarification_questions(
    matrix: EvidenceMatrix,
    ledger: EvidenceLedger,
    limit: int = 6,
) -> list[ClarificationQuestion]:
    """Ask only questions that can resolve high-value evidence gaps."""
    questions: list[ClarificationQuestion] = []
    weak_rows = sorted(
        (
            row for row in matrix.rows
            if row.status in {"missing", "mention_only", "transferable"}
        ),
        key=lambda row: (
            0 if row.priority == "required" else 1,
            {"missing": 0, "mention_only": 1, "transferable": 2}[row.status],
        ),
    )
    for row in weak_rows:
        terms = ", ".join(row.missing_terms[:4]) or row.requirement
        questions.append(
            ClarificationQuestion(
                id=f"Q-{row.id}",
                requirement_id=row.id,
                prompt=(
                    f"Do you have verified experience relevant to “{row.requirement}”? "
                    "If yes, state where you used it, what you personally did, and the outcome. "
                    "Leave blank if you do not have this experience."
                ),
                reason=f"Coverage is {row.status}; unresolved terms: {terms}.",
            )
        )
        if len(questions) >= limit:
            return questions

    unquantified = [
        item for item in ledger.items
        if item.section in {"experience", "projects"} and not item.metrics and len(item.text.split()) >= 5
    ]
    for item in unquantified:
        questions.append(
            ClarificationQuestion(
                id=f"Q-{item.id}",
                requirement_id="",
                prompt=(
                    f"For evidence {item.id} (“{item.text[:100]}”), was there a verified change "
                    "in time, cost, revenue, quality, volume, users, or risk? Provide the measured "
                    "result and how it was measured, or leave blank."
                ),
                reason="A verified outcome could strengthen an existing claim without fabrication.",
                answer_type="metric",
            )
        )
        if len(questions) >= limit:
            break
    return questions


def compact_grounding_context(
    ledger: EvidenceLedger,
    matrix: EvidenceMatrix,
    max_chars: int = 12_000,
) -> str:
    """Serialize one canonical candidate story plus requirement coverage."""
    profile = ledger.profile
    lines = [
        "STRUCTURED CANDIDATE PROFILE",
        "CANDIDATE EVIDENCE LEDGER (the only allowed factual source):",
    ]
    if profile:
        lines.extend(
            [
                f"source_hash={profile.source_hash}",
                f"candidate_name={profile.candidate_name or 'not detected'}",
                "section_order="
                + (", ".join(profile.section_order) or "not detected"),
                "contact="
                + "; ".join(
                    profile.contact.emails
                    + profile.contact.phones
                    + profile.contact.links
                ),
                "declared_skills="
                + (", ".join(profile.declared_skills) or "not detected"),
                "estimated_experience_years="
                + (
                    str(profile.estimated_years)
                    if profile.estimated_years is not None
                    else "not reliably calculated"
                ),
                "",
                "CAREER STORY (source order; preserve role boundaries):",
            ]
        )

    included_ids: set[str] = set()

    def append_item(item: EvidenceItem, indent: str = ""):
        if item.id in included_ids:
            return
        lines.append(
            f"{indent}[{item.id}] type={item.item_type} | "
            f"verification={item.verification} | {item.text}"
        )
        included_ids.add(item.id)

    if profile and profile.roles:
        for role in profile.roles:
            lines.append(
                f"[{role.id}] title={role.title or 'not separated'} | "
                f"employer={role.employer or 'not separated'} | "
                f"location={role.location or 'not supplied'} | "
                f"dates={role.date_text or 'not supplied'} | "
                f'exact_header="{role.header}"'
            )
            for item in ledger.items:
                if item.role_id == role.id:
                    append_item(item, "  ")
            if sum(len(line) + 1 for line in lines) >= max_chars:
                lines.append(
                    "[Additional lower-priority evidence omitted for token efficiency.]"
                )
                break
    elif profile:
        lines.append("[No reliable role hierarchy detected; inspect unassigned evidence.]")

    if profile and profile.projects:
        lines.append("\nPROJECTS:")
        for project in profile.projects:
            lines.append(f'[{project.id}] exact_title="{project.title}"')
            for item in ledger.items:
                if item.role_id == project.id:
                    append_item(item, "  ")

    section_labels = (
        ("summary", "SUMMARY"),
        ("skills", "SKILLS"),
        ("education", "EDUCATION"),
        ("certifications", "CERTIFICATIONS"),
        ("clarification", "USER-CONFIRMED CLARIFICATIONS"),
        ("other", "CONTACT / OTHER SOURCE LINES"),
    )
    for section, label in section_labels:
        section_items = [
            item
            for item in ledger.items
            if item.section == section and item.id not in included_ids
        ]
        if not section_items:
            continue
        lines.append(f"\n{label}:")
        for item in section_items:
            append_item(item, "  ")
            if sum(len(line) + 1 for line in lines) >= max_chars:
                lines.append(
                    "[Additional lower-priority evidence omitted for token efficiency.]"
                )
                break
        if sum(len(line) + 1 for line in lines) >= max_chars:
            break

    for item in ledger.items:
        if item.id not in included_ids and sum(len(line) + 1 for line in lines) < max_chars:
            append_item(item, "  ")

    lines.append("\nREQUIREMENT COVERAGE:")
    for row in matrix.rows[:15]:
        evidence = ", ".join(row.evidence_ids) or "none"
        lines.append(f"[{row.id}] {row.priority} | {row.status} | evidence={evidence} | {row.requirement}")
    return "\n".join(lines)


def achievement_grounding_context(
    ledger: EvidenceLedger,
    matrix: EvidenceMatrix,
    max_items: int = 14,
    max_chars: int = 8_000,
) -> str:
    """Return only evidence that can legitimately support achievement bullets.

    Skills lists, education entries, contact details, and requirements without
    candidate evidence are deliberately excluded. This prevents a target
    requirement from becoming a fabricated candidate accomplishment.
    """
    eligible_sections = {"experience", "projects", "clarification"}
    eligible = [
        item
        for item in ledger.items
        if item.section in eligible_sections and len(item.text.split()) >= 4
    ]
    if not eligible:
        return ""

    relevant_ids = {
        evidence_id
        for row in matrix.rows
        if row.status in {"direct", "equivalent", "transferable"}
        for evidence_id in row.evidence_ids
    }
    eligible.sort(
        key=lambda item: (
            0 if item.id in relevant_ids else 1,
            0 if item.metrics else 1,
            item.id,
        )
    )
    lines = [
        "STRUCTURED VERIFIED ACHIEVEMENT EVIDENCE "
        "(the only facts allowed in generated bullets):"
    ]
    current_role = ""
    for item in eligible[: max(1, max_items)]:
        if item.role and item.role != current_role:
            current_role = item.role
            role_id = item.role_id or "UNASSIGNED"
            lines.append(f'[{role_id}] exact_role_header="{item.role}"')
        lines.append(
            f"[{item.id}] section={item.section} | role_id={item.role_id or 'none'} | "
            f"verification={item.verification} | {item.text}"
        )
        if sum(len(line) + 1 for line in lines) >= max_chars:
            lines.append("[Additional evidence omitted for token efficiency.]")
            break
    return "\n".join(lines)


def _normalized_numbers(text: str) -> set[str]:
    return {
        re.sub(r"[\s,]", "", match.group(0)).lower()
        for match in NUMBER_RE.finditer(text)
    }


def _known_skills(text: str) -> set[str]:
    lowered = text.lower()
    return {
        _normalize_term(skill)
        for skill in SKILL_PHRASES
        if re.search(r"(?<!\w)" + re.escape(skill) + r"(?!\w)", lowered)
    }


def _ledger_source_text(ledger: EvidenceLedger) -> str:
    """Return candidate facts, including role headers stored as provenance."""
    parts = [ledger.candidate_name]
    if ledger.profile:
        parts.extend(role.header for role in ledger.profile.roles)
        parts.extend(
            record.text for record in ledger.profile.education_records
        )
        parts.extend(
            record.text for record in ledger.profile.certification_records
        )
    for item in ledger.items:
        if item.role:
            parts.append(item.role)
        parts.append(item.text)
    return "\n".join(dict.fromkeys(part for part in parts if part))


def _normalized_fact_line(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def validate_generated_claims(
    generated_text: str,
    ledger: EvidenceLedger,
    jd_text: str = "",
) -> ClaimValidationReport:
    """Flag unsupported numbers, skills, and credentials in generated output."""
    source_text = _ledger_source_text(ledger)
    source_numbers = _normalized_numbers(source_text)
    source_skills = _known_skills(source_text)
    jd_skills = _known_skills(jd_text)
    unsupported_job_skills = jd_skills - source_skills
    source_lower = source_text.lower()

    claims = [
        _clean_evidence_line(line)
        for line in generated_text.splitlines()
        if BULLET_RE.match(line) and len(_clean_evidence_line(line).split()) >= 4
    ]
    if not claims:
        claims = [
            sentence.strip()
            for sentence in re.split(r"(?<=[.!?])\s+", generated_text)
            if len(sentence.strip().split()) >= 8
        ]

    issues: list[ClaimIssue] = []
    supported = 0
    for index, claim in enumerate(claims, start=1):
        claim_id = f"C{index:03d}"
        claim_issues = 0
        for number in sorted(_normalized_numbers(claim) - source_numbers):
            issues.append(
                ClaimIssue(
                    claim_id, "high", "unsupported_metric", claim,
                    f"The number {number!r} does not appear in candidate evidence.",
                )
            )
            claim_issues += 1

        claim_skills = _known_skills(claim)
        introduced_skills = sorted(claim_skills & unsupported_job_skills)
        if introduced_skills:
            issues.append(
                ClaimIssue(
                    claim_id, "high", "unsupported_skill", claim,
                    "These JD terms are not supported by candidate evidence: "
                    + ", ".join(introduced_skills[:8]),
                )
            )
            claim_issues += 1

        credential = CREDENTIAL_RE.search(claim)
        if credential and credential.group(0).lower() not in source_lower:
            issues.append(
                ClaimIssue(
                    claim_id, "high", "unsupported_credential", claim,
                    f"Credential term {credential.group(0)!r} is absent from candidate evidence.",
                )
            )
            claim_issues += 1

        if "[metric needed:" in claim.lower():
            issues.append(
                ClaimIssue(
                    claim_id, "medium", "verification_placeholder", claim,
                    "Candidate verification is required before this placeholder can be removed.",
                )
            )
            claim_issues += 1
        if not claim_issues:
            supported += 1

    return ClaimValidationReport(
        claims_checked=len(claims),
        supported_claims=supported,
        issues=issues,
    )


def validate_achievement_claims(
    generated_text: str,
    ledger: EvidenceLedger,
    jd_text: str = "",
) -> ClaimValidationReport:
    """Validate both factual claims and required evidence citations."""
    report = validate_generated_claims(generated_text, ledger, jd_text)
    evidence_by_id = ledger.by_id()
    lines = generated_text.splitlines()
    bullet_positions = [
        index
        for index, line in enumerate(lines)
        if BULLET_RE.match(line) and len(_clean_evidence_line(line).split()) >= 4
    ]

    for claim_index, position in enumerate(bullet_positions, start=1):
        claim_id = f"C{claim_index:03d}"
        claim = _clean_evidence_line(lines[position])
        end = (
            bullet_positions[claim_index]
            if claim_index < len(bullet_positions)
            else len(lines)
        )
        citation_lines = [
            line.strip()
            for line in lines[position + 1 : end]
            if line.strip().lower().startswith(("evidence:", "source:"))
        ]
        if not citation_lines:
            report.issues.append(
                ClaimIssue(
                    claim_id,
                    "high",
                    "missing_evidence_citation",
                    claim,
                    "Every achievement must cite a stable resume evidence ID.",
                )
            )
            continue

        citation = " ".join(citation_lines)
        cited_ids = tuple(dict.fromkeys(re.findall(r"\bE\d{3}\b", citation)))
        if not cited_ids:
            report.issues.append(
                ClaimIssue(
                    claim_id,
                    "high",
                    "missing_evidence_id",
                    claim,
                    "The evidence line does not contain an E### source identifier.",
                )
            )
            continue

        unknown_ids = [item_id for item_id in cited_ids if item_id not in evidence_by_id]
        if unknown_ids:
            report.issues.append(
                ClaimIssue(
                    claim_id,
                    "high",
                    "unknown_evidence_id",
                    claim,
                    "These evidence IDs do not exist in the candidate ledger: "
                    + ", ".join(unknown_ids),
                )
            )

        phrase_match = re.search(r'[“"]([^"”]{3,})[”"]', citation)
        if not phrase_match:
            report.issues.append(
                ClaimIssue(
                    claim_id,
                    "high",
                    "missing_source_quote",
                    claim,
                    "The citation must include a short exact phrase from the resume.",
                )
            )
            continue
        quoted = re.sub(r"\s+", " ", phrase_match.group(1)).strip().lower()
        known_items = [
            evidence_by_id[item_id]
            for item_id in cited_ids
            if item_id in evidence_by_id
        ]
        if known_items and not any(
            quoted in re.sub(r"\s+", " ", item.text).lower()
            for item in known_items
        ):
            report.issues.append(
                ClaimIssue(
                    claim_id,
                    "high",
                    "source_quote_mismatch",
                    claim,
                    "The quoted source phrase does not occur in the cited evidence item.",
                )
            )

    issue_claim_ids = {issue.claim_id for issue in report.issues}
    report.supported_claims = max(
        0,
        report.claims_checked
        - sum(
            f"C{index:03d}" in issue_claim_ids
            for index in range(1, report.claims_checked + 1)
        ),
    )
    return report


def strip_generation_annotations(generated_text: str) -> str:
    """Remove internal evidence lines before presenting a generated document."""
    kept = [
        line
        for line in generated_text.splitlines()
        if not line.strip().lower().startswith(
            ("evidence:", "status:", "jd match:")
        )
    ]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(kept)).strip()


def allocate_role_bullet_targets(
    ledger: EvidenceLedger,
    matrix: EvidenceMatrix,
    *,
    preferred_per_role: int = 4,
    minimum_per_role: int = 1,
    maximum_per_role: int = 6,
) -> tuple[RoleBulletPlan, ...]:
    """Distribute a finite bullet budget fairly across parsed source roles.

    Every role with usable evidence receives a baseline allocation before extra
    bullets are assigned. Remaining capacity is distributed in round-robin
    order, prioritising roles with stronger JD coverage without starving older
    or less directly aligned roles.
    """
    if not ledger.profile or not ledger.profile.roles:
        return ()

    preferred = max(1, min(maximum_per_role, int(preferred_per_role)))
    role_items = {
        role.id: [
            item
            for item in ledger.items
            if item.role_id == role.id
            and item.section == "experience"
            and item.item_type in {"bullet", "role_detail", "user_confirmed"}
        ]
        for role in ledger.profile.roles
    }
    relevant_ids = {
        evidence_id
        for row in matrix.rows
        if row.status in {"direct", "equivalent", "transferable"}
        for evidence_id in row.evidence_ids
    }
    roles = [
        role
        for role in ledger.profile.roles
        if role_items.get(role.id)
    ]
    if not roles:
        return ()

    allocations = {
        role.id: min(len(role_items[role.id]), max(1, minimum_per_role))
        for role in roles
    }
    total_available = sum(len(role_items[role.id]) for role in roles)
    total_budget = min(total_available, preferred * len(roles))
    relevance = {
        role.id: sum(item.id in relevant_ids for item in role_items[role.id])
        for role in roles
    }

    # First pass is deliberately fair; relevance changes ordering, not eligibility.
    ordered = sorted(
        enumerate(roles),
        key=lambda pair: (-relevance[pair[1].id], pair[0]),
    )
    while sum(allocations.values()) < total_budget:
        progressed = False
        for _, role in ordered:
            cap = min(maximum_per_role, len(role_items[role.id]))
            if allocations[role.id] >= cap:
                continue
            allocations[role.id] += 1
            progressed = True
            if sum(allocations.values()) >= total_budget:
                break
        if not progressed:
            break

    return tuple(
        RoleBulletPlan(
            role_id=role.id,
            role_header=role.header,
            target=allocations[role.id],
            available=len(role_items[role.id]),
            relevance_hits=relevance[role.id],
        )
        for role in roles
    )


def role_bullet_plan_context(plans: tuple[RoleBulletPlan, ...]) -> str:
    """Return prompt-safe role targets with exact source headers."""
    if not plans:
        return "No reliably parsed role records; preserve the source structure."
    return "\n".join(
        f"- {plan.role_id}: {plan.target} bullet(s) | exact_header="
        f'"{plan.role_header}" | available_evidence={plan.available}'
        for plan in plans
    )


def _best_evidence_for_claim(
    claim: str,
    ledger: EvidenceLedger,
    *,
    preferred_role_id: str = "",
) -> EvidenceItem | None:
    candidates = [
        item
        for item in ledger.items
        if item.section in {"experience", "projects"}
        and item.item_type
        in {
            "bullet",
            "role_detail",
            "project_detail",
            "unassigned_experience",
            "user_confirmed",
        }
    ]
    if not candidates:
        return None
    claim_terms = _content_terms(claim)

    def rank(item: EvidenceItem) -> tuple[int, int, int, int]:
        overlap = len(claim_terms.intersection(item.terms))
        role_bonus = int(bool(preferred_role_id) and item.role_id == preferred_role_id)
        type_bonus = int(item.item_type == "bullet")
        return overlap, role_bonus, type_bonus, -item.source_line

    return max(candidates, key=rank)


def _requirement_for_evidence(
    evidence_id: str,
    matrix: EvidenceMatrix,
) -> RequirementEvidence | None:
    priority_rank = {"required": 3, "responsibility": 2, "preferred": 1}
    candidates = [
        row
        for row in matrix.rows
        if evidence_id in row.evidence_ids
        and row.status in {"direct", "equivalent", "transferable"}
    ]
    if not candidates:
        return None
    return max(
        candidates,
        key=lambda row: (
            priority_rank.get(row.priority, 0),
            len(row.matched_terms),
            -int(row.id[1:]),
        ),
    )


def _canonical_bullet_block(
    claim: str,
    evidence: EvidenceItem,
    matrix: EvidenceMatrix,
    *,
    use_source_wording: bool = False,
) -> list[str]:
    visible_claim = evidence.text if use_source_wording else _clean_evidence_line(claim)
    requirement = _requirement_for_evidence(evidence.id, matrix)
    block = [
        f"- {visible_claim}",
        f'  Evidence: {evidence.id} — "{evidence.text}"',
    ]
    if requirement:
        block.append(
            f'  JD Match: {requirement.id} — "{requirement.requirement}"'
        )
    else:
        block.append("  JD Match: none — retained candidate value")
    return block


def _canonicalize_bullet_blocks(
    generated_text: str,
    ledger: EvidenceLedger,
    matrix: EvidenceMatrix,
    jd_text: str,
) -> str:
    """Rebuild hidden citations and replace only factually unsafe bullet wording."""
    evidence_by_id = ledger.by_id()
    lines = generated_text.splitlines()
    output: list[str] = []
    current_role_id = ""
    source_headers = {
        _normalized_fact_line(role.header): role.id
        for role in (ledger.profile.roles if ledger.profile else ())
    }
    index = 0
    while index < len(lines):
        raw = lines[index]
        clean = raw.strip()
        normalized = _normalized_fact_line(clean)
        if normalized in source_headers:
            current_role_id = source_headers[normalized]
        if not BULLET_RE.match(raw) or len(_clean_evidence_line(raw).split()) < 4:
            if not clean.lower().startswith(("evidence:", "status:", "jd match:")):
                output.append(raw)
            index += 1
            continue

        end = index + 1
        while end < len(lines) and not BULLET_RE.match(lines[end]):
            next_clean = lines[end].strip()
            if _section_heading(next_clean) or (
                ROLE_RE.search(next_clean)
                and not next_clean.lower().startswith(
                    ("evidence:", "status:", "jd match:")
                )
            ):
                break
            end += 1
        citation_text = " ".join(lines[index + 1 : end])
        cited = [
            evidence_by_id[item_id]
            for item_id in re.findall(r"\bE\d{3}\b", citation_text)
            if item_id in evidence_by_id
        ]
        evidence = cited[0] if cited else _best_evidence_for_claim(
            _clean_evidence_line(raw),
            ledger,
            preferred_role_id=current_role_id,
        )
        if evidence:
            bullet_report = validate_generated_claims(
                "- " + _clean_evidence_line(raw),
                ledger,
                jd_text,
            )
            unsafe = any(issue.severity == "high" for issue in bullet_report.issues)
            output.extend(
                _canonical_bullet_block(
                    raw,
                    evidence,
                    matrix,
                    use_source_wording=unsafe,
                )
            )
        index = end
    return re.sub(r"\n{3,}", "\n\n", "\n".join(output)).strip()


def _annotated_bullet_blocks(text: str) -> list[tuple[str, list[str]]]:
    lines = text.splitlines()
    blocks: list[tuple[str, list[str]]] = []
    index = 0
    while index < len(lines):
        if not BULLET_RE.match(lines[index]):
            index += 1
            continue
        end = index + 1
        while end < len(lines) and not BULLET_RE.match(lines[end]):
            next_clean = lines[end].strip()
            if _section_heading(next_clean) or (
                ROLE_RE.search(next_clean)
                and not next_clean.lower().startswith(
                    ("evidence:", "status:", "jd match:")
                )
            ):
                break
            end += 1
        block = lines[index:end]
        ids = re.findall(r"\bE\d{3}\b", " ".join(block[1:]))
        if ids:
            blocks.append((ids[0], block))
        index = end
    return blocks


def _replace_experience_section(
    annotated_text: str,
    ledger: EvidenceLedger,
    matrix: EvidenceMatrix,
    plans: tuple[RoleBulletPlan, ...],
) -> str:
    if not plans or not ledger.profile:
        return annotated_text
    lines = annotated_text.splitlines()
    start = next(
        (
            index
            for index, line in enumerate(lines)
            if _section_heading(line.strip()) == "experience"
        ),
        None,
    )
    if start is None:
        start = len(lines)
        before = lines + ([""] if lines else [])
        after: list[str] = []
    else:
        end = next(
            (
                index
                for index in range(start + 1, len(lines))
                if _section_heading(lines[index].strip())
                and _section_heading(lines[index].strip()) != "experience"
            ),
            len(lines),
        )
        before = lines[:start]
        after = lines[end:]

    by_id = ledger.by_id()
    generated_by_role: dict[str, list[list[str]]] = {}
    for evidence_id, block in _annotated_bullet_blocks(annotated_text):
        item = by_id.get(evidence_id)
        if item and item.section == "experience" and item.role_id:
            generated_by_role.setdefault(item.role_id, []).append(block)

    section = ["PROFESSIONAL EXPERIENCE"]
    used_evidence: set[str] = set()
    for plan in plans:
        section.extend(["", plan.role_header])
        selected: list[list[str]] = []
        for block in generated_by_role.get(plan.role_id, []):
            evidence_id = re.findall(r"\bE\d{3}\b", " ".join(block[1:]))[0]
            if evidence_id in used_evidence:
                continue
            selected.append(block)
            used_evidence.add(evidence_id)
            if len(selected) >= plan.target:
                break
        source_items = [
            item
            for item in ledger.items
            if item.role_id == plan.role_id
            and item.section == "experience"
            and item.item_type in {"bullet", "role_detail", "user_confirmed"}
            and item.id not in used_evidence
        ]
        source_items.sort(
            key=lambda item: (
                _requirement_for_evidence(item.id, matrix) is None,
                item.item_type != "bullet",
                item.source_line,
            )
        )
        for item in source_items:
            if len(selected) >= plan.target:
                break
            selected.append(
                _canonical_bullet_block(
                    item.text,
                    item,
                    matrix,
                    use_source_wording=True,
                )
            )
            used_evidence.add(item.id)
        for block in selected:
            section.extend(block)

    merged = before + ([""] if before else []) + section
    if after:
        merged += [""] + after
    return re.sub(r"\n{3,}", "\n\n", "\n".join(merged)).strip()


def repair_grounded_resume_draft(
    generated_text: str,
    ledger: EvidenceLedger,
    jd_text: str,
    role_plans: tuple[RoleBulletPlan, ...] = (),
) -> str:
    """Deterministically repair audit metadata and source-role structure.

    The model remains responsible for wording. Code—not the model—owns exact
    evidence quotes, requirement quotes, IDs, and role headers. Unsupported
    bullet wording falls back to the cited source statement.
    """
    matrix = build_evidence_matrix(jd_text, ledger)
    canonical = _canonicalize_bullet_blocks(
        generated_text,
        ledger,
        matrix,
        jd_text,
    )
    return _replace_experience_section(
        canonical,
        ledger,
        matrix,
        role_plans,
    )


def build_safe_evidence_resume(
    ledger: EvidenceLedger,
    jd_text: str,
    role_plans: tuple[RoleBulletPlan, ...] = (),
) -> str:
    """Build a guaranteed source-only recovery version for blocked downloads."""
    profile = ledger.profile
    if not profile:
        return ""
    matrix = build_evidence_matrix(jd_text, ledger)
    plans = role_plans or allocate_role_bullet_targets(ledger, matrix)
    lines: list[str] = []
    if profile.candidate_name:
        lines.append(profile.candidate_name)
    contacts = list(profile.contact.emails + profile.contact.phones + profile.contact.links)
    if contacts:
        lines.append(" | ".join(contacts))
    if profile.summary_lines:
        lines.extend(["", "PROFESSIONAL SUMMARY", *profile.summary_lines])
    skill_lines = [
        line.strip()
        for line in profile.sections.get("skills", "").splitlines()
        if line.strip()
    ]
    if skill_lines:
        lines.extend(["", "CORE SKILLS", *skill_lines])

    seed = "\n".join(lines)
    if plans:
        seed = _replace_experience_section(seed, ledger, matrix, plans)
    else:
        raw_experience = [
            line.strip()
            for line in profile.sections.get("experience", "").splitlines()
            if line.strip()
        ]
        if raw_experience:
            seed += "\n\nPROFESSIONAL EXPERIENCE\n" + "\n".join(raw_experience)
            seed = _canonicalize_bullet_blocks(seed, ledger, matrix, jd_text)

    tail: list[str] = []
    education_lines = (
        [record.text for record in profile.education_records]
        or [
            line.strip()
            for line in profile.sections.get("education", "").splitlines()
            if line.strip()
        ]
    )
    if education_lines:
        tail.extend(
            ["", "EDUCATION", *education_lines]
        )
    certification_lines = (
        [record.text for record in profile.certification_records]
        or [
            line.strip()
            for line in profile.sections.get("certifications", "").splitlines()
            if line.strip()
        ]
    )
    if certification_lines:
        tail.extend(
            [
                "",
                "CERTIFICATIONS",
                *certification_lines,
            ]
        )
    if profile.projects:
        tail.extend(["", "PROJECTS"])
        for project in profile.projects:
            tail.append(project.title)
            project_items = [
                item
                for item in ledger.items
                if item.role_id == project.id and item.section == "projects"
            ]
            for item in project_items:
                tail.extend(
                    _canonical_bullet_block(
                        item.text,
                        item,
                        matrix,
                        use_source_wording=True,
                    )
                )
    return re.sub(r"\n{3,}", "\n\n", seed + "\n" + "\n".join(tail)).strip()


def validate_grounded_resume_draft(
    generated_text: str,
    ledger: EvidenceLedger,
    jd_text: str = "",
) -> ClaimValidationReport:
    """Audit a cited AI resume draft before evidence annotations are removed."""
    report = validate_achievement_claims(generated_text, ledger, jd_text)
    matrix = build_evidence_matrix(jd_text, ledger)
    requirements_by_id = {row.id: row for row in matrix.rows}
    lines = generated_text.splitlines()
    bullet_positions = [
        index
        for index, line in enumerate(lines)
        if BULLET_RE.match(line) and len(_clean_evidence_line(line).split()) >= 4
    ]
    for claim_index, position in enumerate(bullet_positions, start=1):
        claim_id = f"C{claim_index:03d}"
        claim = _clean_evidence_line(lines[position])
        end = (
            bullet_positions[claim_index]
            if claim_index < len(bullet_positions)
            else len(lines)
        )
        block = [line.strip() for line in lines[position + 1 : end]]
        evidence_text = " ".join(
            line for line in block if line.lower().startswith("evidence:")
        )
        cited_evidence = set(re.findall(r"\bE\d{3}\b", evidence_text))
        mapping_lines = [
            line for line in block if line.lower().startswith("jd match:")
        ]
        if not mapping_lines:
            report.issues.append(
                ClaimIssue(
                    claim_id,
                    "high",
                    "missing_jd_mapping",
                    claim,
                    "Every generated bullet must state a supported R### mapping "
                    "or explicitly state JD Match: none.",
                )
            )
            continue
        mapping_text = " ".join(mapping_lines)
        if re.search(r"\bnone\b", mapping_text, re.I):
            continue
        requirement_ids = tuple(
            dict.fromkeys(re.findall(r"\bR\d{3}\b", mapping_text))
        )
        if not requirement_ids:
            report.issues.append(
                ClaimIssue(
                    claim_id,
                    "high",
                    "missing_requirement_id",
                    claim,
                    "The JD Match annotation does not contain R### or none.",
                )
            )
            continue
        for requirement_id in requirement_ids:
            requirement = requirements_by_id.get(requirement_id)
            if not requirement:
                report.issues.append(
                    ClaimIssue(
                        claim_id,
                        "high",
                        "unknown_requirement_id",
                        claim,
                        f"{requirement_id} is not present in the requirement matrix.",
                    )
                )
                continue
            if not cited_evidence.intersection(requirement.evidence_ids):
                report.issues.append(
                    ClaimIssue(
                        claim_id,
                        "high",
                        "unsupported_jd_mapping",
                        claim,
                        f"{requirement_id} is not supported by the bullet's cited "
                        "candidate evidence.",
                    )
                )
            phrase_match = re.search(r'[“"]([^"”]{3,})[”"]', mapping_text)
            if (
                not phrase_match
                or phrase_match.group(1).strip().lower()
                not in requirement.requirement.lower()
            ):
                report.issues.append(
                    ClaimIssue(
                        claim_id,
                        "high",
                        "requirement_quote_mismatch",
                        claim,
                        f"The JD Match annotation must quote the actual {requirement_id} "
                        "requirement text.",
                    )
                )

    visible_text = strip_generation_annotations(generated_text)
    source_text = _ledger_source_text(ledger)

    unsupported_numbers = sorted(
        _normalized_numbers(visible_text) - _normalized_numbers(source_text)
    )
    if unsupported_numbers:
        report.issues.append(
            ClaimIssue(
                "D001",
                "high",
                "document_unsupported_metric",
                "Full generated resume",
                "Numbers absent from all candidate evidence: "
                + ", ".join(unsupported_numbers[:12]),
            )
        )

    unsupported_skills = sorted(
        _known_skills(visible_text) - _known_skills(source_text)
    )
    if unsupported_skills:
        report.issues.append(
            ClaimIssue(
                "D002",
                "high",
                "document_unsupported_skill",
                "Full generated resume",
                "Skills or tools absent from all candidate evidence: "
                + ", ".join(unsupported_skills[:12]),
            )
        )

    source_credentials = {
        match.group(0).lower() for match in CREDENTIAL_RE.finditer(source_text)
    }
    generated_credentials = {
        match.group(0).lower() for match in CREDENTIAL_RE.finditer(visible_text)
    }
    unsupported_credentials = sorted(generated_credentials - source_credentials)
    if unsupported_credentials:
        report.issues.append(
            ClaimIssue(
                "D003",
                "high",
                "document_unsupported_credential",
                "Full generated resume",
                "Credential terms absent from all candidate evidence: "
                + ", ".join(unsupported_credentials[:8]),
            )
        )

    source_roles = (
        {
            _normalized_fact_line(header)
            for header in (
                *(role.header for role in ledger.profile.roles),
                *(project.title for project in ledger.profile.projects),
            )
            if header
        }
        | {
            _normalized_fact_line(line)
            for section in ("experience", "projects")
            for line in ledger.profile.sections.get(section, "").splitlines()
            if ROLE_RE.search(line)
        }
        if ledger.profile
        else {
            _normalized_fact_line(item.role)
            for item in ledger.items
            if item.role
        }
    )
    source_section_lines = {
        section: {
            _normalized_fact_line(item.text)
            for item in ledger.items
            if item.section == section
        }
        for section in ("education", "certifications")
    }
    current_section = ""
    for line_number, raw_line in enumerate(visible_text.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        detected_section = _section_heading(line)
        if detected_section:
            current_section = detected_section
            continue
        normalized = _normalized_fact_line(_clean_evidence_line(line))
        if current_section in {"experience", "projects"} and ROLE_RE.search(line):
            if normalized not in source_roles:
                report.issues.append(
                    ClaimIssue(
                        f"D{line_number:03d}",
                        "high",
                        "unsupported_role_header",
                        line,
                        "This title, employer, location, or date header is not an exact "
                        "candidate-source role record.",
                    )
                )
        elif current_section in {"education", "certifications"}:
            if (
                normalized
                and normalized not in source_section_lines[current_section]
            ):
                report.issues.append(
                    ClaimIssue(
                        f"D{line_number:03d}",
                        "high",
                        f"unsupported_{current_section}_record",
                        line,
                        "This record does not exactly match a candidate-source "
                        f"{current_section} entry.",
                    )
                )

    issue_claim_ids = {issue.claim_id for issue in report.issues}
    report.supported_claims = max(
        0,
        report.claims_checked
        - sum(
            f"C{index:03d}" in issue_claim_ids
            for index in range(1, report.claims_checked + 1)
        ),
    )
    return report

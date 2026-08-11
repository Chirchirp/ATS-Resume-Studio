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
    canonical_resume_section,
    extract_job_profile,
    extract_resume_profile,
)


BULLET_RE = re.compile(r"^\s*[•▪◦●\uf0b7*\-–—]\s+")
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

_COVERAGE_NOISE_TERMS = {
    "across",
    "analyse",
    "analyze",
    "compile",
    "comprehensive",
    "continuous",
    "deliver",
    "delivering",
    "demonstrate",
    "develop",
    "ensure",
    "including",
    "maintain",
    "methodologies",
    "mindset",
    "organisational",
    "proficiency",
    "provide",
    "r",
    "support",
    "technical",
    "them",
    "through",
    "throughout",
    "tools",
    "understand",
}

_COVERAGE_CONCEPT_PATTERNS = {
    "sql": (r"\bsql\b",),
    "excel": (r"\b(?:ms|microsoft)?\s*excel\b",),
    "smartsheet": (r"\bsmartsheet\b",),
    "data visualization": (
        r"\bdata\s+visuali[sz]",
        r"\bpower\s*bi\b",
        r"\bdashboards?\b",
        r"\bscorecards?\b",
    ),
    "data cleaning": (
        r"\bdata\s+clean",
        r"\bcleaned\b",
        r"\bstandardized\b",
        r"\bstandardised\b",
    ),
    "data flow": (
        r"\bdata\s+flow",
        r"\bsource[-\s]to[-\s]report\b",
        r"\blineage\b",
    ),
    "external collaboration": (
        r"\bexternal\s+partners?\b",
        r"\bexternal\s+research\s+teams?\b",
        r"\br\s*&\s*d\b",
        r"\bresearch\s+and\s+development\b",
    ),
    "production context": (
        r"\bproduction\b",
        r"\bprocessing\b",
        r"\boperations?\b",
    ),
    "ad hoc analysis": (r"\bad[\s-]+hoc\b",),
    "decision support": (
        r"\bdecision[-\s]making\b",
        r"\bdecision\s+support\b",
        r"\bactionable\s+(?:insights?|recommendations?)\b",
        r"\bmanagement\s+reviews?\b",
    ),
    "management reporting": (
        r"\bmanagement\s+(?:reports?|reporting|updates?|reviews?)\b",
        r"\bupdate\s+reports?\b",
        r"\breporting\s+workflows?\b",
    ),
    "recommendations": (r"\brecommendations?\b",),
    "process improvement": (
        r"\bcontinuous\s+improvement\b",
        r"\bprocess\s+improvement\b",
        r"\bprocess\s+optimi[sz]",
        r"\bimprovement\s+initiatives?\b",
    ),
    "stakeholder collaboration": (
        r"\bstakeholders?\b",
        r"\bcross[-\s]functional\b",
        r"\bpartnered\s+with\b",
        r"\bbusiness\s+users?\b",
        r"\bacross\s+departments?\b",
    ),
    "requirements gathering": (
        r"\bgather(?:ed|ing)?\s+requirements?\b",
        r"\brequirements?\s+gathering\b",
    ),
    "analytical translation": (
        r"\btranslate(?:d|s|ing)?\b",
        r"\banalytical\s+solutions?\b",
        r"\breport\s+specifications?\b",
    ),
    "data quality controls": (
        r"\bdata[-\s]quality\b",
        r"\bvalidation\b",
        r"\bverification\b",
        r"\breconcil",
        r"\bdata\s+integrity\b",
    ),
    "documentation": (
        r"\bdocument(?:ed|ation|ing)?\b",
        r"\bdata\s+sources?\b",
        r"\bprocedures?\b",
    ),
    "user training": (
        r"\btraining\b",
        r"\btrained\b",
        r"\bend[-\s]users?\b",
        r"\buser\s+support\b",
        r"\bsupervisors?\b",
    ),
    "hse compliance": (
        r"\bhse\b",
        r"\bhealth\s+and\s+safety\b",
    ),
    "phytosanitary compliance": (r"\bphytosanitary\b",),
    "pressure handling": (r"\bunder\s+pressure\b", r"\btight\s+deadlines?\b"),
    "integrity": (r"\bintegrity\b", r"\bintellectual\s+honesty\b"),
}


def _coverage_terms(text: str, extracted_terms) -> set[str]:
    """Return high-signal requirement/evidence concepts for explainable matching."""
    lowered = re.sub(r"\s+", " ", text.lower())
    concepts = {
        concept
        for concept, patterns in _COVERAGE_CONCEPT_PATTERNS.items()
        if any(re.search(pattern, lowered) for pattern in patterns)
    }
    if concepts:
        return concepts
    return {
        normalized
        for term in extracted_terms
        if (normalized := _normalize_term(term))
        and normalized not in _COVERAGE_NOISE_TERMS
    }


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
    return canonical_resume_section(line)


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
    for section in (
        "training",
        "awards",
        "languages",
        "memberships",
        "publications",
        "volunteering",
        "achievements",
        "references",
        "interests",
    ):
        for line in profile.sections.get(section, "").splitlines():
            add_item(
                section=section,
                text=line,
                item_type="additional_record",
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
    required_terms = _coverage_terms(requirement.text, requirement.terms)
    ranked: list[tuple[float, EvidenceItem, set[str]]] = []
    for item in ledger.items:
        item_terms = _coverage_terms(item.text, item.terms)
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
        coverage_entries = ranked[:8]
        best = selected[0][0] if selected else 0.0
        aggregate_matched = (
            set().union(*(entry[2] for entry in coverage_entries))
            if coverage_entries
            else set()
        )
        demonstrated_matched = (
            set().union(
                *(
                    entry[2]
                    for entry in coverage_entries
                    if entry[1].section in demonstrated_sections
                )
            )
            if any(
                entry[1].section in demonstrated_sections
                for entry in coverage_entries
            )
            else set()
        )
        demonstrated_ratio = len(demonstrated_matched) / len(required_terms)
        aggregate_ratio = len(aggregate_matched) / len(required_terms)
        if demonstrated_ratio >= 0.67:
            status = "direct"
        elif aggregate_ratio >= 0.67 or best >= 0.67:
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


def candidate_facing_grounding_context(
    ledger: EvidenceLedger,
    matrix: EvidenceMatrix,
    *,
    alignment_score: int | None = None,
    confidence: str = "",
    max_evidence_per_requirement: int = 3,
) -> str:
    """Serialize exact candidate facts without exposing internal audit identifiers."""
    by_id = ledger.by_id()
    lines = []
    if alignment_score is not None:
        lines.append(
            f"Deterministic Job Alignment Score: {alignment_score}/100"
            + (f" ({confidence} confidence)" if confidence else "")
        )
    lines.append("Requirement coverage:")
    for row in matrix.rows:
        evidence = [
            by_id[item_id].text
            for item_id in row.evidence_ids[:max_evidence_per_requirement]
            if item_id in by_id
        ]
        lines.append(f"- {row.status.upper()}: {row.requirement}")
        if evidence:
            lines.extend(f'  Candidate source: "{item}"' for item in evidence)
        else:
            lines.append("  Candidate source: not evidenced")
    lines.append("Additional candidate facts:")
    for item in ledger.items[:40]:
        role = f" | {item.role}" if item.role else ""
        lines.append(f'- {item.section}{role}: "{item.text}"')
    return "\n".join(lines)


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
    max_chars: int = 18_000,
    max_item_chars: int = 700,
) -> str:
    """Serialize a fair, strictly bounded candidate story and requirement map."""
    max_chars = max(2_000, int(max_chars))
    max_item_chars = max(160, int(max_item_chars))
    profile = ledger.profile
    coverage_budget = min(5_000, max(1_200, max_chars // 3))
    coverage_lines = ["REQUIREMENT COVERAGE:"]
    coverage_used = len(coverage_lines[0])
    for row in matrix.rows[:18]:
        evidence = ", ".join(row.evidence_ids) or "none"
        requirement = re.sub(r"\s+", " ", row.requirement).strip()
        if len(requirement) > 360:
            requirement = requirement[:357].rsplit(" ", 1)[0] + "..."
        line = (
            f"[{row.id}] {row.priority} | {row.status} | "
            f"evidence={evidence} | {requirement}"
        )
        if coverage_used + len(line) + 1 > coverage_budget:
            coverage_lines.append("[Additional requirements omitted for token efficiency.]")
            break
        coverage_lines.append(line)
        coverage_used += len(line) + 1
    coverage_text = "\n".join(coverage_lines)
    evidence_budget = max(800, max_chars - len(coverage_text) - 2)

    lines: list[str] = []
    used = 0

    def clip(value: str, limit: int = max_item_chars) -> str:
        clean = re.sub(r"\s+", " ", value).strip()
        if len(clean) <= limit:
            return clean
        shortened = clean[: max(1, limit - 3)].rsplit(" ", 1)[0].strip()
        return (shortened or clean[: max(1, limit - 3)]) + "..."

    def add_line(line: str = "") -> bool:
        nonlocal used
        needed = len(line) + (1 if lines else 0)
        if used + needed > evidence_budget:
            return False
        lines.append(line)
        used += needed
        return True

    for line in (
        "STRUCTURED CANDIDATE PROFILE",
        "CANDIDATE EVIDENCE LEDGER (the only allowed factual source):",
    ):
        add_line(line)
    if profile:
        experience_depth = (
            "established"
            if (profile.estimated_years or 0) >= 8 or len(profile.roles) >= 3
            else "mid-career"
            if (profile.estimated_years or 0) >= 4 or len(profile.roles) >= 2
            else "developing"
        )
        profile_lines = (
            f"source_hash={profile.source_hash}",
            f"candidate_name={profile.candidate_name or 'not detected'}",
            "section_order=" + (", ".join(profile.section_order) or "not detected"),
            "contact="
            + clip(
                "; ".join(
                    profile.contact.emails
                    + profile.contact.phones
                    + profile.contact.links
                ),
                500,
            ),
            "declared_skills="
            + clip(", ".join(profile.declared_skills) or "not detected", 1_200),
            "estimated_experience_years="
            + (
                str(profile.estimated_years)
                if profile.estimated_years is not None
                else "not reliably calculated"
            ),
            f"career_depth_for_editorial_detail={experience_depth} "
            "(context only; never state an inferred duration or seniority title)",
        )
        for line in profile_lines:
            add_line(line)

    included_ids: set[str] = set()

    def append_item(item: EvidenceItem, indent: str = "") -> bool:
        if item.id in included_ids:
            return True
        role_ref = f" | role_id={item.role_id}" if item.role_id else ""
        added = add_line(
            f"{indent}[{item.id}] type={item.item_type} | "
            f"verification={item.verification}{role_ref} | {clip(item.text)}"
        )
        if added:
            included_ids.add(item.id)
        return added

    # These records define the candidate's identity and qualifications. Keep them
    # ahead of verbose role evidence so a capacity-constrained model cannot omit
    # education, credentials, the original profile, or declared skills.
    mandatory_sections = (
        ("summary", "SOURCE SUMMARY"),
        ("skills", "DECLARED SKILLS"),
        ("education", "EDUCATION — COPY EVERY RECORD EXACTLY"),
        ("certifications", "CERTIFICATIONS — COPY EVERY RECORD EXACTLY"),
        ("training", "TRAINING — PRESERVE SOURCE RECORDS"),
        ("awards", "AWARDS — PRESERVE SOURCE RECORDS"),
        ("languages", "LANGUAGES — PRESERVE SOURCE RECORDS"),
        ("memberships", "MEMBERSHIPS — PRESERVE SOURCE RECORDS"),
        ("publications", "PUBLICATIONS — PRESERVE SOURCE RECORDS"),
        ("volunteering", "VOLUNTEER EXPERIENCE — PRESERVE SOURCE RECORDS"),
        ("achievements", "KEY ACHIEVEMENTS — PRESERVE SOURCE RECORDS"),
        ("references", "REFERENCES — PRESERVE SOURCE RECORDS"),
        ("interests", "INTERESTS — PRESERVE SOURCE RECORDS"),
    )
    mandatory_start = used
    mandatory_budget = min(2_400, max(700, evidence_budget // 2))
    mandatory_truncated = False
    for section, label in mandatory_sections:
        section_items = [
            item
            for item in ledger.items
            if item.section == section and item.id not in included_ids
        ]
        if not section_items:
            continue
        add_line("")
        if not add_line(f"{label}:"):
            break
        for item in section_items:
            if used - mandatory_start >= mandatory_budget:
                mandatory_truncated = True
                break
            if not append_item(item, "  "):
                mandatory_truncated = True
                break
        if mandatory_truncated:
            break
    if mandatory_truncated:
        add_line(
            "[Additional source records omitted from the AI payload; code will "
            "restore them exactly after generation.]"
        )

    confirmed = [
        item for item in ledger.items if item.verification == "user_confirmed"
    ]
    if confirmed:
        add_line("")
        add_line("USER-CONFIRMED CLARIFICATIONS (prioritize these verified facts):")
        for item in confirmed:
            if not append_item(item, "  "):
                break

    if profile and profile.roles:
        add_line("")
        add_line("ROLE INDEX (preserve every exact header):")
        for role in profile.roles:
            add_line(
                f"[{role.id}] title={role.title or 'not separated'} | "
                f"employer={role.employer or 'not separated'} | "
                f"location={role.location or 'not supplied'} | "
                f"dates={role.date_text or 'not supplied'} | "
                f'exact_header="{role.header}"'
            )
        add_line("")
        add_line("ROLE EVIDENCE (round-robin to preserve fair role coverage):")
        role_queues = {
            role.id: [
                item
                for item in ledger.items
                if item.role_id == role.id and item.id not in included_ids
            ]
            for role in profile.roles
        }
        item_index = 0
        capacity_exhausted = False
        while any(item_index < len(items) for items in role_queues.values()):
            added_this_round = False
            for role in profile.roles:
                items = role_queues[role.id]
                if item_index >= len(items):
                    continue
                if not append_item(items[item_index], "  "):
                    capacity_exhausted = True
                    break
                added_this_round = True
            if capacity_exhausted or not added_this_round:
                break
            item_index += 1
    elif profile:
        add_line("[No reliable role hierarchy detected; inspect unassigned evidence.]")

    if profile and profile.projects:
        add_line("")
        add_line("PROJECTS:")
        for project in profile.projects:
            if not add_line(f'[{project.id}] exact_title="{clip(project.title, 500)}"'):
                break
            for item in ledger.items:
                if item.role_id == project.id:
                    if not append_item(item, "  "):
                        break

    section_labels = (("other", "CONTACT / OTHER SOURCE LINES"),)
    for section, label in section_labels:
        section_items = [
            item
            for item in ledger.items
            if item.section == section and item.id not in included_ids
        ]
        if not section_items:
            continue
        if not add_line("") or not add_line(f"{label}:"):
            break
        for item in section_items:
            if not append_item(item, "  "):
                break

    for item in ledger.items:
        if item.id not in included_ids and not append_item(item, "  "):
            break

    if len(included_ids) < len(ledger.items):
        add_line("[Additional lower-priority evidence omitted for model capacity.]")
    result = "\n".join(lines) + "\n\n" + coverage_text
    return result[:max_chars]


def compact_requirement_context(
    matrix: EvidenceMatrix,
    *,
    job_title: str = "",
    max_chars: int = 6_000,
) -> str:
    """Replace a potentially huge raw JD with extracted, auditable requirements."""
    max_chars = max(1_000, int(max_chars))
    lines = [
        "EXTRACTED JOB CONTEXT (derived deterministically from the supplied JD):",
        f"Target title: {job_title or 'Not reliably extracted'}",
    ]
    used = sum(len(line) + 1 for line in lines)
    for row in matrix.rows[:24]:
        requirement = re.sub(r"\s+", " ", row.requirement).strip()
        if len(requirement) > 420:
            requirement = requirement[:417].rsplit(" ", 1)[0] + "..."
        line = f"[{row.id}] {row.priority} | {requirement}"
        if used + len(line) + 1 > max_chars:
            lines.append("[Additional requirements omitted for model capacity.]")
            break
        lines.append(line)
        used += len(line) + 1
    return "\n".join(lines)[:max_chars]


def compact_optional_draft(text: str, max_chars: int = 12_000) -> str:
    """Bound optional editorial context; candidate evidence remains authoritative."""
    return compact_prompt_block(
        text,
        max_chars=max_chars,
        omission_message=(
            "Middle of previous draft omitted for model capacity; "
            "use candidate evidence."
        ),
    )


def compact_prompt_block(
    text: str,
    *,
    max_chars: int,
    omission_message: str = "Middle content omitted for model capacity.",
) -> str:
    """Bound non-authoritative prompt context while retaining its beginning and end."""
    max_chars = max(400, int(max_chars))
    clean = (text or "").strip()
    if len(clean) <= max_chars:
        return clean
    head_chars = int(max_chars * 0.7)
    marker = f"\n[{omission_message}]\n"
    tail_chars = max(80, max_chars - head_chars - len(marker))
    head = clean[:head_chars].rsplit("\n", 1)[0]
    tail = clean[-tail_chars:].split("\n", 1)[-1]
    return (head + marker + tail)[:max_chars]


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


def _audited_bullet_positions(lines: list[str]) -> list[int]:
    """Return contribution bullets, excluding scan-friendly skill bullets.

    Standalone achievement text has no section headings, so all substantive
    bullets remain auditable. Full resumes restrict claim citations to
    experience and project sections.
    """
    current_section = ""
    target_headings_seen = False
    target_positions: list[int] = []
    all_positions: list[int] = []
    for index, line in enumerate(lines):
        detected = _section_heading(line.strip())
        if detected:
            current_section = detected
            if detected in {"experience", "projects"}:
                target_headings_seen = True
            continue
        if BULLET_RE.match(line) and len(_clean_evidence_line(line).split()) >= 4:
            all_positions.append(index)
            if current_section in {"experience", "projects"}:
                target_positions.append(index)
    return target_positions if target_headings_seen else all_positions


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

    lines = generated_text.splitlines()
    claim_positions = _audited_bullet_positions(lines)
    claims = [_clean_evidence_line(lines[index]) for index in claim_positions]
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
    bullet_positions = _audited_bullet_positions(lines)

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
    visible = "\n".join(kept)
    visible = re.sub(
        r"\s*(?:\[(?:E|R|ROLE)\d{3}\]|\((?:E|R|ROLE)\d{3}\))",
        "",
        visible,
        flags=re.I,
    )
    return re.sub(r"\n{3,}", "\n\n", visible).strip()


def allocate_role_bullet_targets(
    ledger: EvidenceLedger,
    matrix: EvidenceMatrix,
    *,
    preferred_per_role: int = 4,
    minimum_per_role: int = 1,
    maximum_per_role: int = 6,
    target_pages: int | None = None,
) -> tuple[RoleBulletPlan, ...]:
    """Distribute a finite bullet budget fairly across parsed source roles.

    Every source role is retained in order. Roles with usable evidence receive a
    baseline allocation before extra bullets are assigned; header-only source
    roles remain visible with a zero target. Remaining capacity is distributed
    in round-robin order without starving older or less aligned organizations.
    """
    if not ledger.profile or not ledger.profile.roles:
        return ()

    preferred = max(1, min(maximum_per_role, int(preferred_per_role)))
    role_items = {}
    for role in ledger.profile.roles:
        bullets = [
            item
            for item in ledger.items
            if item.role_id == role.id
            and item.section == "experience"
            and item.item_type in {"bullet", "user_confirmed"}
        ]
        role_items[role.id] = bullets or [
            item
            for item in ledger.items
            if item.role_id == role.id
            and item.section == "experience"
            and item.item_type == "role_detail"
        ]
    relevant_ids = {
        evidence_id
        for row in matrix.rows
        if row.status in {"direct", "equivalent", "transferable"}
        for evidence_id in row.evidence_ids
    }
    # Keep every parsed source organization in its original order. A role with
    # no usable responsibility line still receives a zero-bullet header rather
    # than disappearing from the candidate's employment history.
    roles = list(ledger.profile.roles)
    if not roles:
        return ()

    allocations = {
        role.id: min(len(role_items[role.id]), max(1, minimum_per_role))
        for role in roles
    }
    total_available = sum(len(role_items[role.id]) for role in roles)
    total_budget = min(total_available, preferred * len(roles))
    if target_pages is not None:
        pages = max(1, min(4, int(target_pages)))
        # Summary, skills and qualifications consume roughly one third of a
        # page. Keep a concise, predictable contribution budget while retaining
        # at least one bullet for every role that has evidence.
        page_budget = {1: 4, 2: 7, 3: 11, 4: 15}[pages]
        evidenced_roles = sum(bool(role_items[role.id]) for role in roles)
        total_budget = min(total_budget, max(evidenced_roles, page_budget))
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


def role_bullet_plan_context(
    plans: tuple[RoleBulletPlan, ...],
    max_chars: int = 4_000,
) -> str:
    """Return prompt-safe role targets with exact source headers."""
    if not plans:
        return "No reliably parsed role records; preserve the source structure."
    lines: list[str] = []
    used = 0
    for plan in plans:
        header = re.sub(r"\s+", " ", plan.role_header).strip()
        if len(header) > 600:
            header = header[:597].rsplit(" ", 1)[0] + "..."
        line = (
            f"- {plan.role_id}: {plan.target} bullet(s) | exact_header="
            f'"{header}" | available_evidence={plan.available}'
        )
        if used + len(line) + 1 > max_chars:
            lines.append(
                "- Additional role-plan detail omitted; preserve remaining ROLE headers "
                "from the candidate evidence index."
            )
            break
        lines.append(line)
        used += len(line) + 1
    return "\n".join(lines)[:max_chars]


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
    current_section = ""
    source_headers = {
        _normalized_fact_line(role.header): role.id
        for role in (ledger.profile.roles if ledger.profile else ())
    }
    index = 0
    while index < len(lines):
        raw = lines[index]
        clean = raw.strip()
        detected_section = _section_heading(clean)
        if detected_section:
            current_section = detected_section
        normalized = _normalized_fact_line(clean)
        if normalized in source_headers:
            current_role_id = source_headers[normalized]
        if (
            current_section not in {"experience", "projects"}
            or not BULLET_RE.match(raw)
            or len(_clean_evidence_line(raw).split()) < 4
        ):
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
            claim_terms = _content_terms(_clean_evidence_line(raw))
            grounded_overlap = bool(claim_terms.intersection(evidence.terms))
            unsafe = (
                not grounded_overlap
                or any(issue.severity == "high" for issue in bullet_report.issues)
            )
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
            and item.item_type in {"bullet", "user_confirmed"}
            and item.id not in used_evidence
        ]
        if len(source_items) < max(0, plan.target - len(selected)):
            source_items.extend(
                item
                for item in ledger.items
                if item.role_id == plan.role_id
                and item.section == "experience"
                and item.item_type == "role_detail"
                and item.id not in used_evidence
                and item not in source_items
            )
        source_items.sort(
            key=lambda item: (
                0 if item.metrics else 1,
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


_CAPABILITY_PATTERNS = (
    (r"\bdata (?:analysis|analytics|analys(?:is|es|ed|ing))\b", "Data Analysis"),
    (r"\bdata clean(?:ing|ed)?\b", "Data Cleaning"),
    (r"\bdata (?:quality|integrity|validation|verification)\b", "Data Quality & Validation"),
    (r"\b(?:dashboard|visuali[sz](?:ation|ations|ed|ing))\b", "Dashboarding & Visualization"),
    (r"\b(?:reporting|management reports?|analytical reports?)\b", "Reporting & Management Insights"),
    (r"\bdata pipelines?\b", "Data Pipelines"),
    (r"\b(?:workflow|process) automat(?:ion|ed|ing)\b", "Workflow Automation"),
    (r"\bprocess (?:improvement|optimi[sz]ation)\b", "Process Improvement"),
    (r"\brequirements? gathering\b", "Requirements Gathering"),
    (r"\bstakeholder (?:management|engagement|collaboration)\b", "Stakeholder Collaboration"),
    (r"\b(?:training|trained|end-user support|user support)\b", "Training & User Support"),
    (r"\b(?:documentation|documented|data dictionaries?)\b", "Documentation"),
    (r"\bhse reporting\b", "HSE Reporting"),
    (r"\b(?:phytosanitary|hygiene) compliance\b", "Phytosanitary & Hygiene Compliance"),
    (r"\b(?:forecasting|forecasted|budgeting|budgeted)\b", "Forecasting & Budgeting"),
    (r"\b(?:project coordination|project management)\b", "Project Delivery"),
    (r"\bdecision[- ]making\b", "Decision Support"),
)

_SKILL_GROUPS = (
    (
        "Data & Analytics",
        {
            "data analysis", "data science", "data cleaning", "data governance",
            "data integrity", "data quality", "data visualization",
            "data visualisation", "machine learning", "financial analysis",
            "market research", "google analytics",
        },
    ),
    (
        "Tools & Technology",
        {
            "adobe creative suite", "amazon web services", "angular", "ansible",
            "apache airflow", "aws", "azure", "c#", "c++", "ci/cd",
            "cloud computing", "css", "django", "docker", "excel", "fastapi",
            "figma", "flask", "gcp", "git", "go", "graphql", "html", "java",
            "javascript", "jira", "kotlin", "kubernetes", "linux",
            "microsoft excel", "mongodb", "mysql", "next.js", "node.js",
            "oracle", "pandas", "php", "postgresql", "power bi", "python",
            "pytorch", "r", "react", "redis", "salesforce", "smartsheet",
            "snowflake", "spark", "spring", "sql", "tableau", "tensorflow",
            "terraform", "typescript", "vue", "webpack",
        },
    ),
    (
        "Business & Delivery",
        {
            "agile", "business analysis", "change management", "crm",
            "customer success", "process improvement", "process optimization",
            "process optimisation", "product management", "project management",
            "requirements gathering", "risk management", "stakeholder engagement",
            "stakeholder management", "supply chain", "user research",
        },
    ),
)

def _display_skill(value: str) -> str:
    """Format a source-backed skill without turning it into a new claim."""
    acronyms = {
        "aws": "AWS", "c#": "C#", "c++": "C++", "ci/cd": "CI/CD",
        "css": "CSS", "gcp": "GCP", "git": "Git", "go": "Go",
        "graphql": "GraphQL", "html": "HTML", "java": "Java",
        "javascript": "JavaScript", "jira": "Jira", "linux": "Linux",
        "mongodb": "MongoDB", "mysql": "MySQL", "next.js": "Next.js",
        "node.js": "Node.js", "oracle": "Oracle", "pandas": "Pandas",
        "php": "PHP", "postgresql": "PostgreSQL", "power bi": "Power BI",
        "python": "Python", "pytorch": "PyTorch", "r": "R", "react": "React",
        "redis": "Redis", "sql": "SQL", "tableau": "Tableau",
        "tensorflow": "TensorFlow", "typescript": "TypeScript",
    }
    clean = re.sub(r"\s+", " ", value).strip(" ,;|")
    if clean.lower() in acronyms:
        return acronyms[clean.lower()]
    return clean.title() if clean == clean.lower() else clean


def _source_backed_skill_lines(ledger: EvidenceLedger) -> list[str]:
    """Build mature, grouped competencies only from candidate-source language."""
    profile = ledger.profile
    if not profile:
        return []
    source_text = _ledger_source_text(ledger)
    detected = {
        skill
        for skill in SKILL_PHRASES
        if re.search(r"(?<!\w)" + re.escape(skill) + r"(?!\w)", source_text, re.I)
    }
    declared = list(profile.declared_skills)
    used: set[str] = set()
    lines: list[str] = []
    for label, vocabulary in _SKILL_GROUPS:
        values: list[str] = []
        for skill in sorted(detected):
            normalized = _normalize_term(skill)
            if skill not in vocabulary and normalized not in vocabulary:
                continue
            display = _display_skill(skill)
            key = _normalize_term(display)
            if key not in used:
                values.append(display)
                used.add(key)
        for skill in declared:
            normalized = _normalize_term(skill)
            if normalized not in vocabulary:
                continue
            display = _display_skill(skill)
            key = _normalize_term(display)
            if key not in used:
                values.append(display)
                used.add(key)
        if values:
            lines.append(f"- {label}: " + " | ".join(values[:12]))

    source_known_skills = _known_skills(source_text)
    capabilities = []
    for pattern, label in _CAPABILITY_PATTERNS:
        if not re.search(pattern, source_text, re.I):
            continue
        if _normalize_term(label) in used:
            continue
        # A polished label may contain a known ATS skill phrase. Retain it only
        # when that phrase is also present in the candidate source; otherwise a
        # harmless grammatical normalization could incorrectly block download.
        if _known_skills(label) - source_known_skills:
            continue
        capabilities.append(label)
    capabilities = list(dict.fromkeys(capabilities))
    if capabilities:
        lines.append(
            "- Demonstrated Capabilities: " + " | ".join(capabilities[:12])
        )

    remaining = []
    for skill in declared:
        display = _display_skill(skill)
        key = _normalize_term(display)
        if key not in used and not re.search(r"\d", display):
            remaining.append(display)
            used.add(key)
    if remaining:
        lines.append("- Domain & Professional: " + " | ".join(remaining[:12]))
    return lines


def _evidence_summary_sentence(text: str) -> str:
    """Retain a concrete source action without generator scaffolding."""
    clean = _clean_evidence_line(text).rstrip(".")
    return clean + "." if clean else ""


def _premium_summary_lines(ledger: EvidenceLedger) -> list[str]:
    """Create a multi-sentence source-only summary for shallow/fallback drafts."""
    profile = ledger.profile
    if not profile:
        return []
    source_summary = " ".join(
        line.strip() for line in profile.summary_lines if line.strip()
    ).strip()
    sentences: list[str] = []
    if source_summary:
        sentences.append(source_summary.rstrip(".") + ".")
    else:
        titles = list(
            dict.fromkeys(role.title for role in profile.roles if role.title)
        )
        if titles:
            if len(titles) == 1:
                sentences.append(f"{titles[0]} with a documented record of delivery.")
            else:
                sentences.append(
                    f"{titles[0]} with prior experience as "
                    + " and ".join(titles[1:3])
                    + "."
                )

    evidence = [
        item
        for item in ledger.items
        if item.section in {"experience", "projects"}
        and item.item_type in {"bullet", "role_detail", "project_detail", "user_confirmed"}
        and len(item.text.split()) >= 5
    ]
    evidence.sort(
        key=lambda item: (
            0 if item.metrics else 1,
            0 if item.verification == "user_confirmed" else 1,
            item.source_line,
        )
    )
    for item in evidence[:2]:
        sentence = _evidence_summary_sentence(item.text)
        if sentence:
            sentences.append(sentence)

    if len(sentences) < 3:
        skill_lines = _source_backed_skill_lines(ledger)
        skill_values: list[str] = []
        for line in skill_lines:
            _, _, values = line.partition(":")
            skill_values.extend(
                value.strip() for value in values.split("|") if value.strip()
            )
        skill_values = list(dict.fromkeys(skill_values))
        if skill_values:
            lead = skill_values[:4]
            joined = (
                ", ".join(lead[:-1]) + f", and {lead[-1]}"
                if len(lead) > 1
                else lead[0]
            )
            sentences.append(f"Works across {joined}.")
    return sentences[:4]


def _grounded_model_summary(summary_text: str, ledger: EvidenceLedger) -> bool:
    """Allow a strong model narrative only when its content stays source-close."""
    sentences = [
        value.strip()
        for value in re.split(r"(?<=[.!?])\s+", summary_text)
        if value.strip()
    ]
    if len(sentences) < 3 or len(summary_text.split()) < 45:
        return False
    source_terms = _content_terms(_ledger_source_text(ledger))
    for sentence in sentences:
        terms = _content_terms(sentence)
        if not terms:
            continue
        overlap = terms.intersection(source_terms)
        if len(overlap) < 2 or len(overlap) / len(terms) < 0.45:
            return False
    return True


def _grounded_model_skill_lines(
    lines: list[str],
    ledger: EvidenceLedger,
) -> list[str]:
    """Keep richer model grouping only when each listed competency is grounded."""
    candidates = [line.strip() for line in lines if line.strip()]
    if not 3 <= len(candidates) <= 5:
        return []
    source_fact_text = _normalized_fact_line(_ledger_source_text(ledger))
    source_terms = _content_terms(_ledger_source_text(ledger))
    accepted: list[str] = []
    for line in candidates:
        clean = BULLET_RE.sub("", line, count=1).strip()
        if ":" not in clean:
            return []
        _, values = clean.split(":", 1)
        skills = [
            value.strip()
            for value in re.split(r"\s*(?:\||;|,)\s*", values)
            if value.strip()
        ]
        if not skills:
            return []
        for skill in skills:
            normalized = _normalized_fact_line(skill)
            terms = _content_terms(skill)
            if normalized and normalized in source_fact_text:
                continue
            if not terms or len(terms.intersection(source_terms)) / len(terms) < 0.75:
                return []
        accepted.append("- " + clean)
    return accepted


def _sectioned_resume(text: str) -> tuple[list[str], dict[str, list[str]], list[str]]:
    """Split known resume sections while retaining any unclassified tail."""
    prefix: list[str] = []
    sections: dict[str, list[str]] = {}
    order: list[str] = []
    current = ""
    for raw_line in text.splitlines():
        heading = _section_heading(raw_line.strip())
        if heading:
            current = heading
            if heading not in sections:
                sections[heading] = []
                order.append(heading)
            continue
        if current:
            sections[current].append(raw_line)
        else:
            prefix.append(raw_line)
    return prefix, sections, order


_SIMPLE_RESUME_SECTIONS = {
    "summary",
    "skills",
    "experience",
    "education",
    "certifications",
}
_EXPLICIT_EXTRA_HEADINGS = {
    "core leadership capabilities",
    "leadership capabilities",
    "leadership competencies",
    "selected leadership capabilities",
    "selected ai automation architecture portfolio",
    "selected ai automation and architecture portfolio",
    "ai automation architecture portfolio",
    "leadership delivery approach",
    "leadership and delivery approach",
    "technical environment",
}


def _keep_simple_resume_sections(text: str) -> str:
    """Remove non-standard resume blocks without touching employment records."""
    kept: list[str] = []
    skipping = False
    for raw_line in text.splitlines():
        clean = re.sub(r"[^a-z0-9]+", " ", raw_line.casefold()).strip()
        section = _section_heading(raw_line.strip())
        if clean in _EXPLICIT_EXTRA_HEADINGS or (
            "leadership" in clean
            and any(word in clean for word in ("capabilities", "competencies"))
            and len(clean.split()) <= 6
        ):
            skipping = True
            continue
        if section:
            skipping = section not in _SIMPLE_RESUME_SECTIONS
            if not skipping:
                kept.append(raw_line)
            continue
        if not skipping:
            kept.append(raw_line)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(kept)).strip()


def enhance_resume_core_sections(
    generated_text: str,
    ledger: EvidenceLedger,
    *,
    target_pages: int = 3,
) -> str:
    """Enforce premium depth and exact source records after model generation.

    The model can improve prose and ordering, but code owns the sections that
    are most damaging when omitted or hallucinated: qualifications and skills.
    """
    profile = ledger.profile
    if not profile:
        return generated_text
    target_pages = max(1, min(4, int(target_pages)))
    generated_text = _keep_simple_resume_sections(generated_text)
    prefix, sections, original_order = _sectioned_resume(generated_text)
    source_prefix = [profile.candidate_name] if profile.candidate_name else []
    source_prefix.extend(
        item.text
        for item in ledger.items
        if item.section == "other" and item.item_type == "contact_or_header"
    )
    if source_prefix:
        prefix = list(dict.fromkeys(value for value in source_prefix if value.strip()))

    summary_text = " ".join(
        line.strip() for line in sections.get("summary", []) if line.strip()
    )
    sentence_count = len(
        [value for value in re.split(r"(?<=[.!?])\s+", summary_text) if value.strip()]
    )
    min_sentences = 2 if target_pages == 1 else 3
    min_words = 35 if target_pages == 1 else 55
    generic_opening = bool(
        re.search(
            r"\b(?:results-driven|dynamic professional|proven track record|"
            r"seasoned professional|highly motivated|proven ability|expert in)\b",
            summary_text,
            re.I,
        )
    )
    premium_summary = _premium_summary_lines(ledger)
    if (
        sentence_count < min_sentences
        or len(summary_text.split()) < min_words
        or generic_opening
        or not _grounded_model_summary(summary_text, ledger)
    ):
        if premium_summary:
            sections["summary"] = premium_summary
        else:
            sections.pop("summary", None)

    skill_lines = _source_backed_skill_lines(ledger)
    model_skill_lines = _grounded_model_skill_lines(
        sections.get("skills", []),
        ledger,
    )
    if model_skill_lines:
        sections["skills"] = model_skill_lines
    elif skill_lines:
        sections["skills"] = skill_lines
    elif not profile.sections.get("skills", "").strip():
        sections.pop("skills", None)

    education = [record.text for record in profile.education_records]
    certifications = [record.text for record in profile.certification_records]
    if education:
        sections["education"] = education
    else:
        sections.pop("education", None)
    if certifications:
        sections["certifications"] = certifications
    else:
        sections.pop("certifications", None)
    canonical_order = [
        "summary",
        "skills",
        "experience",
        "education",
        "certifications",
    ]
    sections = {
        key: value for key, value in sections.items() if key in canonical_order
    }
    ordered = canonical_order
    headings = {
        "summary": "PROFESSIONAL SUMMARY",
        "skills": "CORE SKILLS",
        "experience": "PROFESSIONAL EXPERIENCE",
        "education": "EDUCATION",
        "certifications": "CERTIFICATIONS",
    }
    blocks = ["\n".join(prefix).strip()]
    for section in ordered:
        content = "\n".join(sections.get(section, [])).strip()
        if content:
            blocks.append(f"{headings.get(section, section.upper())}\n{content}")
    return re.sub(r"\n{3,}", "\n\n", "\n\n".join(block for block in blocks if block)).strip()


def build_safe_evidence_resume(
    ledger: EvidenceLedger,
    jd_text: str,
    role_plans: tuple[RoleBulletPlan, ...] = (),
    *,
    target_pages: int = 3,
) -> str:
    """Build a polished, guaranteed source-only recovery for blocked downloads."""
    profile = ledger.profile
    if not profile:
        return ""
    matrix = build_evidence_matrix(jd_text, ledger)
    plans = role_plans or allocate_role_bullet_targets(
        ledger,
        matrix,
        target_pages=target_pages,
    )
    lines: list[str] = []
    if profile.candidate_name:
        lines.append(profile.candidate_name)
    contacts = list(profile.contact.emails + profile.contact.phones + profile.contact.links)
    if contacts:
        lines.append(" | ".join(contacts))
    summary_lines = _premium_summary_lines(ledger)
    if summary_lines:
        lines.extend(["", "PROFESSIONAL SUMMARY", *summary_lines])
    skill_lines = _source_backed_skill_lines(ledger)
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
    safe_resume = re.sub(
        r"\n{3,}", "\n\n", seed + "\n" + "\n".join(tail)
    ).strip()
    enhanced = enhance_resume_core_sections(
        safe_resume,
        ledger,
        target_pages=target_pages,
    )
    return repair_grounded_resume_draft(
        enhanced,
        ledger,
        jd_text,
        plans,
    )


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
    bullet_positions = _audited_bullet_positions(lines)
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
    if ledger.profile and ledger.profile.roles:
        visible_role_lines = [
            _normalized_fact_line(line)
            for line in visible_text.splitlines()
            if ROLE_RE.search(line)
        ]
        last_position = -1
        for role_index, role in enumerate(ledger.profile.roles, start=1):
            expected = _normalized_fact_line(role.header)
            try:
                position = visible_role_lines.index(expected)
            except ValueError:
                report.issues.append(
                    ClaimIssue(
                        f"ROLE{role_index:03d}",
                        "high",
                        "missing_source_role",
                        role.header,
                        "Every candidate-source organization must appear in Professional "
                        "Experience with its exact role header.",
                    )
                )
                continue
            if position <= last_position:
                report.issues.append(
                    ClaimIssue(
                        f"ROLE{role_index:03d}",
                        "high",
                        "source_role_order_mismatch",
                        role.header,
                        "Professional Experience must preserve the source organization order.",
                    )
                )
            last_position = position
    source_section_lines = {
        section: {
            _normalized_fact_line(item.text)
            for item in ledger.items
            if item.section == section
        }
        for section in (
            "education",
            "certifications",
            "training",
            "awards",
            "languages",
            "memberships",
            "publications",
            "volunteering",
            "achievements",
            "references",
            "interests",
        )
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
        elif current_section in source_section_lines:
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

"""
Deterministic, explainable job-alignment analysis.

This module deliberately avoids claiming to reproduce a specific vendor's ATS.
It extracts a small structured profile from a job description and resume, then
calculates a transparent Job Alignment Score from observable text evidence.
"""

from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass, field
from datetime import date
from typing import Iterable


TOKEN_RE = re.compile(r"[a-zA-Z][a-zA-Z0-9+#./-]*")
METRIC_RE = re.compile(
    r"(?:[$£€]\s?\d[\d,.]*|\b\d+(?:\.\d+)?\s?%|"
    r"\b\d+(?:\.\d+)?\s+(?:(?:[A-Za-z+#/-]+)\s+){0,3}"
    r"(?:percent|hours?|days?|weeks?|months?|years?|users?|clients?|customers?|"
    r"people|employees?|projects?|dashboards?|reports?|million|billion)\b|"
    r"\b\d+(?:\.\d+)?\s?[km]\b)",
    re.I,
)
YEAR_REQUIREMENT_RE = re.compile(
    r"(?P<years>\d{1,2})\+?\s*(?:-\s*\d{1,2}\s*)?years?(?:\s+of)?\s+experience",
    re.I,
)
DATE_RANGE_RE = re.compile(
    r"\b(?P<start>19\d{2}|20\d{2})\b\s*(?:-|–|—|to)\s*"
    r"(?P<end>present|current|19\d{2}|20\d{2})\b",
    re.I,
)
MONTH_NAME_RE = (
    r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|"
    r"Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|"
    r"Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
)
ROLE_DATE_TOKEN_RE = rf"(?:{MONTH_NAME_RE}\s+)?(?:19\d{{2}}|20\d{{2}})"
ROLE_DATE_RANGE_RE = re.compile(
    rf"\b(?P<start>{ROLE_DATE_TOKEN_RE})\b\s*(?:-|–|—|to)\s*"
    rf"(?P<end>present|current|now|{ROLE_DATE_TOKEN_RE})\b",
    re.I,
)

STOPWORDS = {
    "a", "about", "an", "and", "are", "as", "at", "be", "been", "being",
    "by", "can", "for", "from", "has", "have", "having", "in", "into", "is",
    "it", "its", "of", "on", "or", "our", "that", "the", "their", "this",
    "to", "using", "we", "will", "with", "you", "your", "work", "working",
    "role", "job", "candidate", "experience", "years", "year", "ability",
}

GENERIC_TERMS = {
    "excellent", "strong", "good", "effective", "skills", "skill", "team",
    "including", "responsible", "preferred", "required", "requirements",
    "knowledge", "understanding", "support", "opportunity", "business",
}

SECTION_ALIASES = {
    "summary": (
        "summary", "professional summary", "profile", "professional profile",
        "career summary", "objective", "about",
    ),
    "skills": (
        "skills", "core skills", "key skills", "technical skills",
        "technologies", "competencies", "core competencies", "expertise",
        "areas of expertise", "technical proficiencies", "toolkit",
    ),
    "experience": (
        "experience", "professional experience", "work experience",
        "employment", "employment history", "work history", "career history",
    ),
    "education": (
        "education", "academic", "academic background", "education background",
        "qualifications",
    ),
    "certifications": (
        "certifications", "certificates", "licenses", "licences", "credentials",
        "professional qualifications",
    ),
    "projects": ("projects", "selected projects", "professional projects"),
    "training": ("training", "professional development", "courses"),
    "awards": ("awards", "honors", "honours"),
    "languages": ("languages",),
    "memberships": ("memberships", "professional memberships", "affiliations"),
    "publications": ("publications",),
    "volunteering": (
        "volunteering",
        "volunteer experience",
        "community involvement",
    ),
    "achievements": (
        "achievements",
        "key achievements",
        "career highlights",
        "selected achievements",
        "accomplishments",
    ),
    "references": ("references", "referees"),
    "interests": ("interests", "professional interests", "hobbies"),
}

SKILL_PHRASES = {
    "adobe creative suite", "agile", "amazon web services", "angular", "ansible",
    "apache airflow", "aws", "azure", "business analysis", "c#", "c++",
    "change management", "ci/cd", "cloud computing", "content strategy", "crm",
    "css", "customer success", "cybersecurity", "data analysis", "data science",
    "digital marketing", "django", "docker", "excel", "fastapi", "figma",
    "data cleaning", "data governance", "data integrity", "data quality",
    "data visualization", "data visualisation", "financial analysis", "flask",
    "gcp", "git", "go", "google analytics",
    "graphql", "html", "java", "javascript", "jira", "kotlin", "kubernetes",
    "lead generation", "linux", "machine learning", "market research",
    "microsoft excel", "mongodb", "mysql", "next.js", "node.js", "oracle",
    "pandas", "php", "postgresql", "power bi", "product management",
    "project management", "python", "pytorch", "r", "react", "redis",
    "risk management", "salesforce", "seo", "snowflake", "spark", "spring",
    "process improvement", "process optimization", "process optimisation",
    "requirements gathering", "smartsheet", "sql", "stakeholder engagement",
    "stakeholder management", "supply chain", "tableau", "tensorflow",
    "terraform", "typescript", "user research", "vue", "webpack",
}

SYNONYMS = {
    "amazon web services": "aws",
    "microsoft azure": "azure",
    "google cloud platform": "gcp",
    "continuous integration": "ci/cd",
    "continuous delivery": "ci/cd",
    "continuous deployment": "ci/cd",
    "powerbi": "power bi",
    "ms excel": "excel",
    "microsoft excel": "excel",
    "postgres": "postgresql",
    "js": "javascript",
    "ts": "typescript",
    "data visualisation": "data visualization",
    "process optimisation": "process optimization",
    "stakeholder engagement": "stakeholder management",
}

MORPHOLOGY = {
    "analysed": "analyze",
    "analyses": "analyze",
    "analysis": "analyze",
    "analytics": "analyze",
    "analytical": "analyze",
    "analyzed": "analyze",
    "analyzing": "analyze",
    "automated": "automate",
    "automating": "automate",
    "built": "build",
    "collaborated": "collaborate",
    "collaboration": "collaborate",
    "collaborating": "collaborate",
    "communicated": "communicate",
    "communication": "communicate",
    "developed": "develop",
    "developing": "develop",
    "dashboards": "dashboard",
    "managed": "manage",
    "management": "manage",
    "manager": "manage",
    "managing": "manage",
    "optimized": "optimize",
    "optimisation": "optimize",
    "optimization": "optimize",
    "optimizing": "optimize",
    "projects": "project",
    "workflows": "workflow",
    "reported": "report",
    "reporting": "report",
    "reports": "report",
    "visualisation": "visualize",
    "visualization": "visualize",
    "visualizing": "visualize",
}

ACTION_VERBS = {
    "achieved", "automated", "built", "created", "cut", "delivered", "designed",
    "developed", "drove", "eliminated", "generated", "grew", "implemented",
    "improved", "increased", "launched", "led", "managed", "optimized",
    "reduced", "saved", "scaled", "streamlined", "transformed",
}

RESPONSIBILITY_MARKERS = (
    "responsibilities", "what you will do", "you will", "duties", "accountabilities",
)
REQUIRED_MARKERS = ("must", "required", "minimum", "essential", "need to", "shall")
PREFERRED_MARKERS = ("preferred", "nice to have", "desirable", "bonus", "ideally")


@dataclass(frozen=True)
class Requirement:
    text: str
    priority: str
    terms: tuple[str, ...]


@dataclass
class JobProfile:
    title: str = ""
    required: list[Requirement] = field(default_factory=list)
    preferred: list[Requirement] = field(default_factory=list)
    responsibilities: list[str] = field(default_factory=list)
    skills: list[str] = field(default_factory=list)
    phrases: list[str] = field(default_factory=list)
    minimum_years: int | None = None


@dataclass
class ResumeProfile:
    candidate_name: str = ""
    sections: dict[str, str] = field(default_factory=dict)
    skills: list[str] = field(default_factory=list)
    phrases: list[str] = field(default_factory=list)
    metrics: list[str] = field(default_factory=list)
    estimated_years: int | None = None
    has_contact: bool = False
    source_hash: str = ""
    contact: "ResumeContact" = field(default_factory=lambda: ResumeContact())
    summary_lines: tuple[str, ...] = ()
    declared_skills: tuple[str, ...] = ()
    roles: tuple["ResumeRole", ...] = ()
    projects: tuple["ResumeProject", ...] = ()
    education_records: tuple["ResumeRecord", ...] = ()
    certification_records: tuple["ResumeRecord", ...] = ()
    section_order: tuple[str, ...] = ()
    parse_warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class ResumeContact:
    emails: tuple[str, ...] = ()
    phones: tuple[str, ...] = ()
    links: tuple[str, ...] = ()


@dataclass(frozen=True)
class ResumeBullet:
    text: str
    metrics: tuple[str, ...] = ()
    skills: tuple[str, ...] = ()
    action_led: bool = False
    source_line: int = 0


@dataclass(frozen=True)
class ResumeRole:
    id: str
    header: str
    title: str = ""
    employer: str = ""
    location: str = ""
    date_text: str = ""
    start_date: str = ""
    end_date: str = ""
    bullets: tuple[ResumeBullet, ...] = ()
    details: tuple[str, ...] = ()
    source_line: int = 0


@dataclass(frozen=True)
class ResumeProject:
    id: str
    title: str
    bullets: tuple[ResumeBullet, ...] = ()
    details: tuple[str, ...] = ()
    source_line: int = 0


@dataclass(frozen=True)
class ResumeRecord:
    id: str
    text: str
    metrics: tuple[str, ...] = ()
    source_line: int = 0


@dataclass(frozen=True)
class ScoreDimension:
    key: str
    label: str
    score: float
    maximum: float
    explanation: str


@dataclass
class AlignmentReport:
    score: int
    confidence: str
    dimensions: list[ScoreDimension]
    matched_terms: list[str]
    missing_required: list[str]
    missing_preferred: list[str]
    knockout_risks: list[str]
    job: JobProfile
    resume: ResumeProfile
    matched_phrases: list[str] = field(default_factory=list)
    missing_terms: list[str] = field(default_factory=list)
    section_matches: dict[str, list[str]] = field(default_factory=dict)


def _clean_line(line: str) -> str:
    line = re.sub(r"^[\s•▪◦●\uf0b7*\-–—\d.)]+", "", line)
    return re.sub(r"\s+", " ", line).strip()


def _restore_resume_bullet_boundaries(text: str) -> str:
    """Split common PDF bullet glyphs that were flattened into one line."""
    restored = text.replace("\r\n", "\n").replace("\r", "\n")
    restored = re.sub(
        r"\s+[•▪◦●\uf0b7]\s+",
        "\n- ",
        restored,
    )
    lines = []
    for line in restored.splitlines():
        clean = line.strip()
        if re.match(r"^[•▪◦●\uf0b7]\s+", clean):
            clean = re.sub(r"^[•▪◦●\uf0b7]\s+", "- ", clean, count=1)
        lines.append(clean)
    return "\n".join(lines)


def _normalize_term(term: str) -> str:
    value = re.sub(r"\s+", " ", term.strip().lower())
    value = value.strip(".,;:!?()[]{}")
    value = SYNONYMS.get(value, value)
    if " " not in value:
        return MORPHOLOGY.get(value, value)
    return " ".join(
        MORPHOLOGY.get(token, token)
        for token in value.split()
    )


def _tokens(text: str) -> list[str]:
    return [
        _normalize_term(token)
        for token in TOKEN_RE.findall(text.lower())
        if token.lower() not in STOPWORDS and len(token) > 1
    ]


def _content_terms(text: str) -> set[str]:
    lowered = text.lower()
    matched_phrases = {
        phrase
        for phrase in SKILL_PHRASES
        if re.search(r"(?<!\w)" + re.escape(phrase) + r"(?!\w)", lowered)
    }
    found = {_normalize_term(phrase) for phrase in matched_phrases}
    phrase_components = {
        token
        for phrase in matched_phrases
        if " " in phrase
        for token in _tokens(phrase)
    }
    found.update(
        token for token in _tokens(text)
        if token not in GENERIC_TERMS
        and token not in phrase_components
        and (len(token) >= 4 or any(c in token for c in "+#./"))
    )
    return found


def extract_ngram_phrases(
    text: str,
    *,
    min_n: int = 2,
    max_n: int = 3,
) -> tuple[str, ...]:
    """Extract normalized 2-3 word phrases without crossing source lines."""
    phrases: list[str] = []
    for line in text.splitlines():
        raw_tokens = [
            token.lower().strip(".,;:!?()[]{}")
            for token in TOKEN_RE.findall(line)
        ]
        for size in range(max(2, min_n), max(2, max_n) + 1):
            for index in range(0, len(raw_tokens) - size + 1):
                raw_window = raw_tokens[index : index + size]
                if any(
                    token in STOPWORDS or not token
                    for token in raw_window
                ):
                    continue
                window = [_normalize_term(token) for token in raw_window]
                if all(token in GENERIC_TERMS for token in window):
                    continue
                phrase = _normalize_term(" ".join(window))
                if len(phrase) >= 5:
                    phrases.append(phrase)
    return tuple(dict.fromkeys(phrases))


def _phrase_signature(phrase: str) -> tuple[str, ...]:
    return tuple(sorted(_tokens(_normalize_term(phrase))))


def _meaningful_job_phrases(text: str) -> list[str]:
    skill_vocabulary = {
        token
        for item in SKILL_PHRASES
        for token in _tokens(item)
    }
    matched_known_phrases = [
        phrase
        for phrase in SKILL_PHRASES
        if re.search(r"(?<!\w)" + re.escape(phrase) + r"(?!\w)", text.lower())
    ]
    known = {_normalize_term(phrase) for phrase in matched_known_phrases}
    known_token_sets = [set(_tokens(phrase)) for phrase in matched_known_phrases]
    ngrams = extract_ngram_phrases(text)
    selected = list(known)
    for phrase in ngrams:
        tokens = phrase.split()
        token_set = set(tokens)
        if any(token_set < known_tokens for known_tokens in known_token_sets):
            continue
        if (
            any(token in skill_vocabulary for token in tokens)
            or any(
                marker in phrase
                for marker in (
                    "data ",
                    "project ",
                    "stakeholder ",
                    "process ",
                    "quality ",
                    "risk ",
                    "customer ",
                    "financial ",
                    "machine ",
                    "business ",
                )
            )
        ):
            selected.append(phrase)
    return list(dict.fromkeys(selected))[:60]


def extract_alignment_terms(text: str) -> set[str]:
    """Public phrase- and morphology-aware feature extractor."""
    return _content_terms(text) | set(_meaningful_job_phrases(text))


def _line_priority(line: str, current_heading: str) -> str:
    lowered = f"{current_heading} {line}".lower()
    if any(marker in lowered for marker in PREFERRED_MARKERS):
        return "preferred"
    if any(marker in lowered for marker in REQUIRED_MARKERS):
        return "required"
    if any(
        marker in current_heading.lower()
        for marker in (
            "qualification",
            "requirement",
            "essential",
            "minimum criteria",
            "what you need",
        )
    ):
        return "required"
    return "normal"


def _looks_like_heading(line: str) -> bool:
    clean = line.strip().rstrip(":")
    return bool(
        clean
        and len(clean.split()) <= 7
        and (clean.isupper() or line.strip().endswith(":"))
        and not re.search(r"[.!?]$", clean)
    )


def extract_job_profile(text: str) -> JobProfile:
    """Extract a conservative structured job profile from observable JD text."""
    lines = [_clean_line(line) for line in text.splitlines() if _clean_line(line)]
    profile = JobProfile()
    heading = ""

    for raw in lines[:12]:
        if re.search(r"\b(job title|position|role)\s*:", raw, re.I):
            profile.title = raw.split(":", 1)[-1].strip()
            break
    if not profile.title and lines:
        first = lines[0]
        if len(first.split()) <= 8 and not first.endswith("."):
            profile.title = first

    year_matches = [int(m.group("years")) for m in YEAR_REQUIREMENT_RE.finditer(text)]
    profile.minimum_years = max(year_matches) if year_matches else None

    for line in lines:
        if _looks_like_heading(line):
            heading = line
            continue
        terms = tuple(sorted(_content_terms(line)))
        priority = _line_priority(line, heading)
        req = Requirement(text=line, priority=priority, terms=terms)
        if priority == "required" and terms:
            profile.required.append(req)
        elif priority == "preferred" and terms:
            profile.preferred.append(req)

        heading_lower = heading.lower()
        if any(marker in heading_lower for marker in RESPONSIBILITY_MARKERS):
            profile.responsibilities.append(line)
        elif re.match(r"^(lead|manage|develop|design|build|create|deliver|drive|own|support|analy[sz]e)\b", line, re.I):
            profile.responsibilities.append(line)

    feature_text = "\n".join(
        [req.text for req in profile.required + profile.preferred]
        + profile.responsibilities
    )
    all_terms = _content_terms(feature_text)
    frequency = {term: feature_text.lower().count(term) for term in all_terms}
    profile.skills = sorted(all_terms, key=lambda term: (-frequency[term], term))[:40]
    profile.phrases = _meaningful_job_phrases(feature_text)

    if not profile.required:
        for line in lines:
            terms = tuple(sorted(_content_terms(line)))
            if terms and len(line.split()) <= 28:
                profile.required.append(Requirement(line, "required", terms))
            if len(profile.required) >= 8:
                break
    return profile


def canonical_resume_section(line: str) -> str | None:
    """Return a canonical section only for an explicit heading alias.

    Resume content frequently ends with heading-like words (for example,
    ``Smartsheet Core Product Training | 2021``). Treating suffix matches as
    headings moves genuine evidence into the wrong section, so punctuation is
    ignored but the remaining heading text must match an alias exactly.
    """
    clean = re.sub(r"[^a-z ]", "", line.lower()).strip()
    for key, aliases in SECTION_ALIASES.items():
        if clean in aliases:
            return key
    return None


def _section_key(line: str) -> str | None:
    return canonical_resume_section(line)


def _candidate_name(lines: list[str]) -> str:
    for line in lines[:6]:
        clean = _clean_line(line)
        if not clean or any(c in clean for c in "@|") or re.search(r"\d{3,}", clean):
            continue
        if _section_key(clean):
            continue
        words = clean.split()
        if 2 <= len(words) <= 5 and all(re.match(r"^[A-Za-zÀ-ÖØ-öø-ÿ'’-]+$", w) for w in words):
            return clean
    return ""


def _estimate_years(text: str) -> int | None:
    current_year = date.today().year
    ranges: list[tuple[int, int]] = []
    for match in DATE_RANGE_RE.finditer(text):
        start = int(match.group("start"))
        end_text = match.group("end").lower()
        end = current_year if end_text in {"present", "current"} else int(end_text)
        if 1950 <= start <= end <= current_year + 1:
            ranges.append((start, end))
    if not ranges:
        return None
    covered = set()
    for start, end in ranges:
        covered.update(range(start, end + 1))
    return max(0, len(covered) - 1)


def _contact_profile(text: str) -> ResumeContact:
    emails = tuple(
        dict.fromkeys(
            match.group(0)
            for match in re.finditer(
                r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b",
                text,
                re.I,
            )
        )
    )
    phone_candidates = [
        re.sub(r"\s+", " ", match.group(0)).strip()
        for match in re.finditer(r"(?:\+?\d[\d ()-]{7,}\d)", text)
    ]
    phones = tuple(
        dict.fromkeys(
            value
            for value in phone_candidates
            if not re.fullmatch(
                r"(?:19|20)\d{2}\s*[-–—]\s*(?:19|20)\d{2}",
                value,
                re.I,
            )
        )
    )
    links = tuple(
        dict.fromkeys(
            match.group(0).rstrip(".,;)")
            for match in re.finditer(
                r"(?:https?://|www\.)\S+|linkedin\.com/\S+|github\.com/\S+",
                text,
                re.I,
            )
        )
    )
    return ResumeContact(emails=emails, phones=phones, links=links)


def _declared_skill_entries(lines: list[tuple[int, str]]) -> tuple[str, ...]:
    entries: list[str] = []
    for _, line in lines:
        clean = _clean_line(line)
        if ":" in clean:
            clean = clean.split(":", 1)[1].strip()
        for value in re.split(r"[,;|•]", clean):
            value = re.sub(r"\s+", " ", value).strip(" -–—")
            if value and len(value.split()) <= 6:
                entries.append(value)
    return tuple(dict.fromkeys(entries))


def _resume_bullet(text: str, source_line: int) -> ResumeBullet:
    clean = _clean_line(text)
    tokens = _tokens(clean)
    return ResumeBullet(
        text=clean,
        metrics=tuple(METRIC_RE.findall(clean)),
        skills=tuple(sorted(_content_terms(clean))),
        action_led=bool(tokens and tokens[0] in ACTION_VERBS),
        source_line=source_line,
    )


def _role_header_parts(header: str) -> dict[str, str]:
    date_match = ROLE_DATE_RANGE_RE.search(header)
    date_text = date_match.group(0).strip() if date_match else ""
    without_date = (
        (header[: date_match.start()] + header[date_match.end() :])
        if date_match
        else header
    )
    parts = [
        part.strip(" -–—,")
        for part in re.split(r"\s*\|\s*", without_date)
        if part.strip(" -–—,")
    ]
    title = parts[0] if parts else ""
    employer = parts[1] if len(parts) > 1 else ""
    location = " | ".join(parts[2:]) if len(parts) > 2 else ""
    role_markers = re.compile(
        r"\b(?:analyst|engineer|manager|specialist|consultant|coordinator|"
        r"director|officer|assistant|developer|scientist|accountant|lead|"
        r"administrator|supervisor|intern)\b",
        re.I,
    )
    if employer and role_markers.search(employer) and not role_markers.search(title):
        title, employer = employer, title
    return {
        "title": title,
        "employer": employer,
        "location": location,
        "date_text": date_text,
        "start_date": date_match.group("start").strip() if date_match else "",
        "end_date": date_match.group("end").strip() if date_match else "",
    }


def _parse_roles(lines: list[tuple[int, str]]) -> tuple[tuple[ResumeRole, ...], tuple[str, ...]]:
    roles: list[ResumeRole] = []
    warnings: list[str] = []
    current: dict | None = None
    pending_headers: list[tuple[int, str]] = []

    def finish():
        nonlocal current
        if not current:
            return
        parts = _role_header_parts(current["header"])
        roles.append(
            ResumeRole(
                id=f"ROLE{len(roles) + 1:03d}",
                header=current["header"],
                bullets=tuple(current["bullets"]),
                details=tuple(current["details"]),
                source_line=current["source_line"],
                **parts,
            )
        )
        current = None

    for source_line, line in lines:
        is_bullet = bool(re.match(r"^\s*[•▪◦●\uf0b7*\-–—]\s+", line))
        if is_bullet:
            if pending_headers and current:
                current["details"].extend(
                    _clean_line(value) for _, value in pending_headers
                )
                pending_headers.clear()
            if current:
                current["bullets"].append(_resume_bullet(line, source_line))
            else:
                warnings.append(
                    f"Experience bullet on line {source_line} could not be assigned to a role."
                )
            continue

        date_match = ROLE_DATE_RANGE_RE.search(line)
        if date_match:
            finish()
            header_parts = [value.strip() for _, value in pending_headers[-3:]]
            header_parts.append(line.strip())
            header = " | ".join(header_parts)
            header_source_line = (
                pending_headers[0][0] if pending_headers else source_line
            )
            pending_headers.clear()
            current = {
                "header": header,
                "bullets": [],
                "details": [],
                "source_line": header_source_line,
            }
            continue

        if current and not current["bullets"] and not pending_headers:
            current["details"].append(_clean_line(line))
        else:
            pending_headers.append((source_line, line))

    if pending_headers and current:
        current["details"].extend(
            _clean_line(value) for _, value in pending_headers
        )
    finish()
    if lines and not roles:
        warnings.append(
            "No dated role headers were reliably parsed from the experience section."
        )
    return tuple(roles), tuple(dict.fromkeys(warnings))


def _parse_projects(lines: list[tuple[int, str]]) -> tuple[ResumeProject, ...]:
    projects: list[ResumeProject] = []
    current_title = ""
    current_line = 0
    bullets: list[ResumeBullet] = []
    details: list[str] = []

    def finish():
        nonlocal current_title, current_line, bullets, details
        if not current_title and not bullets and not details:
            return
        projects.append(
            ResumeProject(
                id=f"PROJECT{len(projects) + 1:03d}",
                title=current_title or f"Project {len(projects) + 1}",
                bullets=tuple(bullets),
                details=tuple(details),
                source_line=current_line,
            )
        )
        current_title, current_line, bullets, details = "", 0, [], []

    for source_line, line in lines:
        if re.match(r"^\s*[•▪◦●\uf0b7*\-–—]\s+", line):
            bullets.append(_resume_bullet(line, source_line))
        elif not current_title:
            current_title = _clean_line(line)
            current_line = source_line
        elif bullets:
            finish()
            current_title = _clean_line(line)
            current_line = source_line
        else:
            details.append(_clean_line(line))
    finish()
    return tuple(projects)


def extract_resume_profile(text: str) -> ResumeProfile:
    """Extract one canonical, provenance-preserving candidate profile."""
    text = _restore_resume_bullet_boundaries(text)
    indexed_lines = [
        (index, line.strip())
        for index, line in enumerate(text.splitlines(), start=1)
        if line.strip()
    ]
    raw_lines = [line for _, line in indexed_lines]
    sections: dict[str, list[tuple[int, str]]] = {"other": []}
    section_order: list[str] = []
    active = "other"
    for source_line, line in indexed_lines:
        section = _section_key(line)
        if section:
            active = section
            sections.setdefault(active, [])
            if section not in section_order:
                section_order.append(section)
        else:
            sections.setdefault(active, []).append((source_line, line))

    roles, role_warnings = _parse_roles(sections.get("experience", []))
    education = tuple(
        ResumeRecord(
            id=f"EDU{index:03d}",
            text=_clean_line(line),
            metrics=tuple(METRIC_RE.findall(line)),
            source_line=source_line,
        )
        for index, (source_line, line) in enumerate(
            sections.get("education", []), start=1
        )
    )
    certifications = tuple(
        ResumeRecord(
            id=f"CERT{index:03d}",
            text=_clean_line(line),
            metrics=tuple(METRIC_RE.findall(line)),
            source_line=source_line,
        )
        for index, (source_line, line) in enumerate(
            sections.get("certifications", []), start=1
        )
    )
    contact = _contact_profile(text)

    return ResumeProfile(
        candidate_name=_candidate_name(raw_lines),
        sections={
            key: "\n".join(line for _, line in value)
            for key, value in sections.items()
        },
        skills=sorted(_content_terms(text)),
        phrases=list(extract_ngram_phrases(text)),
        metrics=METRIC_RE.findall(text),
        estimated_years=_estimate_years(text),
        has_contact=bool(contact.emails or contact.phones),
        source_hash=hashlib.sha256(text.encode("utf-8")).hexdigest()[:16],
        contact=contact,
        summary_lines=tuple(
            _clean_line(line) for _, line in sections.get("summary", [])
        ),
        declared_skills=_declared_skill_entries(sections.get("skills", [])),
        roles=roles,
        projects=_parse_projects(sections.get("projects", [])),
        education_records=education,
        certification_records=certifications,
        section_order=tuple(section_order),
        parse_warnings=role_warnings,
    )


def _term_present(term: str, resume_text: str, resume_terms: set[str]) -> bool:
    normalized = _normalize_term(term)
    normalized_terms = {_normalize_term(item) for item in resume_terms}
    if normalized in normalized_terms:
        return True
    if " " not in normalized:
        return normalized in set(_tokens(resume_text))
    target = _phrase_signature(normalized)
    return bool(target) and target in {
        _phrase_signature(phrase)
        for phrase in extract_ngram_phrases(resume_text)
    }


SECTION_MATCH_WEIGHTS = {
    "experience": 1.0,
    "projects": 1.0,
    "education": 0.95,
    "certifications": 0.95,
    "skills": 0.75,
    "summary": 0.6,
    "other": 0.25,
}


def _term_section_strength(
    term: str,
    resume: ResumeProfile,
) -> tuple[float, str]:
    best_strength = 0.0
    best_section = ""
    for section, weight in SECTION_MATCH_WEIGHTS.items():
        section_text = resume.sections.get(section, "")
        if section_text and _term_present(
            term,
            section_text,
            _content_terms(section_text),
        ):
            if weight > best_strength:
                best_strength = weight
                best_section = section
    return best_strength, best_section


def _requirement_coverage(
    requirements: Iterable[Requirement],
    resume: ResumeProfile,
) -> tuple[float, list[str], dict[str, list[str]]]:
    requirements = list(requirements)
    if not requirements:
        return 1.0, [], {}
    missed: list[str] = []
    covered = 0.0
    section_matches: dict[str, list[str]] = {}
    for req in requirements:
        if not req.terms:
            continue
        strengths: list[float] = []
        for term in req.terms:
            strength, section = _term_section_strength(term, resume)
            strengths.append(strength)
            if section:
                section_matches.setdefault(section, []).append(
                    _normalize_term(term)
                )
        ratio = sum(strengths) / len(req.terms)
        covered += ratio
        if ratio < 0.5:
            missed.append(req.text)
    return (
        covered / len(requirements),
        missed,
        {
            section: sorted(set(terms))
            for section, terms in section_matches.items()
        },
    )


def _cosine_overlap(left: str, right: str) -> float:
    left_tokens = set(_tokens(left))
    right_tokens = set(_tokens(right))
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / math.sqrt(len(left_tokens) * len(right_tokens))


def _responsibility_score(job: JobProfile, resume_text: str) -> float:
    if not job.responsibilities:
        return 0.5
    resume_lines = [_clean_line(line) for line in resume_text.splitlines() if _clean_line(line)]
    if not resume_lines:
        return 0.0
    best_matches = [
        max((_cosine_overlap(req, line) for line in resume_lines), default=0.0)
        for req in job.responsibilities
    ]
    return min(1.0, sum(best_matches) / len(best_matches) * 2.2)


def _placement_score(job_terms: set[str], resume: ResumeProfile) -> float:
    relevant_sections = [
        resume.sections.get("summary", ""),
        resume.sections.get("skills", ""),
        resume.sections.get("experience", ""),
    ]
    nonempty = [section for section in relevant_sections if section]
    if not job_terms or not nonempty:
        return 0.0
    section_scores = []
    for section in nonempty:
        matched = sum(
            _term_present(term, section, _content_terms(section))
            for term in job_terms
        )
        section_scores.append(matched / len(job_terms))
    return min(1.0, sum(section_scores) / len(nonempty) * 2.5)


def analyze_alignment(jd_text: str, resume_text: str) -> AlignmentReport:
    """Calculate the single deterministic alignment score used across the app."""
    job = extract_job_profile(jd_text)
    resume = extract_resume_profile(resume_text)
    job_terms = set(job.skills) | set(job.phrases)

    required_ratio, missing_required, required_sections = _requirement_coverage(
        job.required, resume
    )
    preferred_ratio, missing_preferred, preferred_sections = _requirement_coverage(
        job.preferred, resume
    )
    section_matches: dict[str, list[str]] = {}
    for source in (required_sections, preferred_sections):
        for section, terms in source.items():
            section_matches.setdefault(section, []).extend(terms)
    section_matches = {
        section: sorted(set(terms))
        for section, terms in section_matches.items()
    }

    term_strengths = {
        term: _term_section_strength(term, resume)
        for term in job_terms
    }
    skill_ratio = (
        sum(strength for strength, _ in term_strengths.values()) / len(job_terms)
        if job_terms else 0.0
    )
    responsibility_ratio = _responsibility_score(job, resume_text)

    if job.minimum_years is None:
        experience_ratio = 0.65 if resume.sections.get("experience") else 0.35
        experience_note = "The JD does not state a numeric minimum; score uses visible experience structure."
    elif resume.estimated_years is None:
        experience_ratio = 0.35
        experience_note = (
            f"The JD requests {job.minimum_years}+ years, but resume dates could not be reliably calculated."
        )
    else:
        experience_ratio = min(1.0, resume.estimated_years / max(job.minimum_years, 1))
        experience_note = (
            f"Approximately {resume.estimated_years} years visible versus "
            f"{job.minimum_years}+ requested."
        )

    structured_bullets = [
        bullet
        for role in resume.roles
        for bullet in role.bullets
    ]
    if structured_bullets:
        bullet_like = [bullet.text for bullet in structured_bullets]
        metric_lines = [
            bullet.text for bullet in structured_bullets if bullet.metrics
        ]
        action_lines = [
            bullet.text for bullet in structured_bullets if bullet.action_led
        ]
    else:
        experience_lines = resume.sections.get("experience", "").splitlines()
        bullet_like = [
            line
            for line in experience_lines
            if re.match(r"^\s*[•▪◦●\uf0b7*\-–—]", line)
        ]
        metric_lines = [
            line for line in experience_lines if METRIC_RE.search(line)
        ]
        action_lines = [
            line for line in experience_lines
            if _tokens(_clean_line(line))
            and _tokens(_clean_line(line))[0] in ACTION_VERBS
        ]
    if bullet_like:
        achievement_ratio = min(
            1.0,
            0.65 * (len(metric_lines) / len(bullet_like))
            + 0.35 * (len(action_lines) / len(bullet_like)),
        )
    else:
        achievement_ratio = 0.15 if resume.metrics else 0.0

    structure_signals = [
        bool(resume.candidate_name),
        resume.has_contact,
        bool(resume.roles or resume.sections.get("experience")),
        bool(resume.sections.get("education")),
        bool(resume.sections.get("skills") or resume.skills),
        not resume.parse_warnings,
    ]
    parseability_ratio = sum(structure_signals) / len(structure_signals)
    placement_ratio = _placement_score(job_terms, resume)

    dimensions = [
        ScoreDimension(
            "required", "Required qualifications", required_ratio * 30, 30,
            f"{len(job.required) - len(missing_required)} of {len(job.required)} "
            "required requirements meet the evidence threshold; experience/project "
            "matches carry more weight than skills-only mentions.",
        ),
        ScoreDimension(
            "preferred", "Preferred qualifications", preferred_ratio * 10, 10,
            f"{len(job.preferred) - len(missing_preferred)} of {len(job.preferred)} "
            "preferred requirements meet the evidence threshold.",
        ),
        ScoreDimension(
            "skills", "Skills and phrase alignment", skill_ratio * 15, 15,
            f"{sum(strength > 0 for strength, _ in term_strengths.values())} of "
            f"{len(job_terms)} normalized terms or 2-3 word phrases were found with "
            "section-aware weighting.",
        ),
        ScoreDimension(
            "responsibilities", "Relevant responsibilities", responsibility_ratio * 15, 15,
            "Measures morphology-normalized contextual overlap between JD responsibilities "
            "and candidate evidence lines.",
        ),
        ScoreDimension(
            "experience", "Experience and seniority", experience_ratio * 10, 10,
            experience_note,
        ),
        ScoreDimension(
            "achievements", "Achievement evidence", achievement_ratio * 5, 5,
            f"{len(metric_lines)} quantified and {len(action_lines)} action-led experience bullets detected.",
        ),
        ScoreDimension(
            "parseability", "Source-text parseability", parseability_ratio * 10, 10,
            f"{sum(structure_signals)} of {len(structure_signals)} identity, contact, "
            "section, role-structure, and parser-confidence signals passed. Exported "
            "DOCX parseability is verified separately by round-trip extraction.",
        ),
        ScoreDimension(
            "placement", "Keyword placement", placement_ratio * 5, 5,
            "Checks whether normalized terms and phrases appear across summary, skills, "
            "and experience—not merely anywhere in the document.",
        ),
    ]

    total = round(sum(d.score for d in dimensions))
    if not jd_text.strip() or not resume_text.strip():
        total = 0
    matched = sorted(
        term for term, (strength, _) in term_strengths.items() if strength > 0
    )
    missing_terms = sorted(
        term for term, (strength, _) in term_strengths.items() if strength == 0
    )
    resume_phrase_signatures = {
        _phrase_signature(phrase) for phrase in resume.phrases
    }
    matched_phrases = sorted(
        phrase
        for phrase in job.phrases
        if _phrase_signature(phrase) in resume_phrase_signatures
    )
    knockout = missing_required[:5]
    observable = len(job.required) + len(job.preferred) + len(job.responsibilities)
    confidence = (
        "High"
        if observable >= 10 and (resume.roles or resume.sections.get("experience"))
        else "Medium"
        if observable >= 5
        else "Low"
    )
    return AlignmentReport(
        score=max(0, min(100, total)),
        confidence=confidence,
        dimensions=dimensions,
        matched_terms=matched,
        missing_required=missing_required,
        missing_preferred=missing_preferred,
        knockout_risks=knockout,
        job=job,
        resume=resume,
        matched_phrases=matched_phrases,
        missing_terms=missing_terms,
        section_matches=section_matches,
    )


def top_requirement_text(job: JobProfile, limit: int = 10) -> list[str]:
    """Return prioritized requirement text for grounded prompt context."""
    combined = job.required + job.preferred
    seen: set[str] = set()
    result: list[str] = []
    for requirement in combined:
        key = requirement.text.lower()
        if key not in seen:
            seen.add(key)
            result.append(requirement.text)
        if len(result) >= limit:
            break
    return result

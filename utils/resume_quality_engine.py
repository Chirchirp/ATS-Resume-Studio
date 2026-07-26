"""Standalone resume quality checks that do not require a job description."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass


SECTION_ALIASES = {
    "summary": {
        "summary",
        "professional summary",
        "profile",
        "professional profile",
        "career summary",
        "objective",
    },
    "experience": {
        "experience",
        "professional experience",
        "work experience",
        "employment",
        "employment history",
        "work history",
    },
    "skills": {
        "skills",
        "core skills",
        "technical skills",
        "core competencies",
        "competencies",
        "areas of expertise",
    },
    "education": {
        "education",
        "academic background",
        "education background",
        "qualifications",
    },
    "certifications": {
        "certifications",
        "certification",
        "licenses",
        "licences",
        "professional development",
        "credentials",
        "professional qualifications",
    },
    "projects": {"projects", "selected projects", "professional projects"},
    "training": {"training", "courses", "training & professional development"},
    "awards": {"awards", "awards & honors", "awards & honours", "honors", "honours"},
    "languages": {"languages"},
    "memberships": {
        "memberships",
        "professional memberships",
        "affiliations",
    },
    "publications": {"publications"},
    "volunteering": {
        "volunteering",
        "volunteer experience",
        "community involvement",
    },
    "achievements": {
        "achievements",
        "key achievements",
        "career highlights",
        "selected achievements",
        "accomplishments",
    },
    "references": {"references", "referees"},
    "interests": {"interests", "professional interests", "hobbies"},
}

MONTH_PATTERN = (
    r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|"
    r"Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|"
    r"Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
)
DATE_TOKEN = rf"(?:{MONTH_PATTERN}\s+\d{{4}}|\d{{4}})"
DATE_RANGE_RE = re.compile(
    rf"(?P<start>{DATE_TOKEN})\s*(?P<separator>-|–|—|to)\s*"
    rf"(?P<end>{DATE_TOKEN}|Present|Current|Now)",
    re.IGNORECASE,
)
MONTH_NUMBERS = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}


@dataclass(frozen=True)
class QualityIssue:
    category: str
    severity: str
    message: str
    evidence: str
    recommendation: str


@dataclass(frozen=True)
class QualityDimension:
    label: str
    score: int
    maximum: int
    explanation: str


@dataclass(frozen=True)
class DateRange:
    source_line: str
    start_label: str
    end_label: str
    start_month: int
    end_month: int | None
    format_style: str
    separator: str


@dataclass(frozen=True)
class ResumeQualityReport:
    score: int
    grade: str
    source_hash: str
    word_count: int
    detected_sections: tuple[str, ...]
    dimensions: tuple[QualityDimension, ...]
    strengths: tuple[str, ...]
    issues: tuple[QualityIssue, ...]
    date_ranges: tuple[DateRange, ...]


def _normalise_header(line: str) -> str:
    value = re.sub(r"[^A-Za-z &]", "", line).strip().lower()
    return re.sub(r"\s+", " ", value)


def _detect_sections(lines: list[str]) -> dict[str, int]:
    detected: dict[str, int] = {}
    for index, line in enumerate(lines):
        candidate = _normalise_header(line.rstrip(":"))
        if not candidate or len(candidate.split()) > 5:
            continue
        for canonical, aliases in SECTION_ALIASES.items():
            if candidate in aliases and canonical not in detected:
                detected[canonical] = index
    return detected


def _experience_lines(lines: list[str], sections: dict[str, int]) -> list[str]:
    start = sections.get("experience")
    if start is None:
        return lines
    later_sections = [
        position
        for name, position in sections.items()
        if position > start and name != "experience"
    ]
    end = min(later_sections) if later_sections else len(lines)
    return lines[start + 1 : end]


def _month_index(value: str, *, end: bool = False) -> int | None:
    cleaned = value.strip().lower()
    if cleaned in {"present", "current", "now"}:
        return None
    year_match = re.search(r"\b(19|20)\d{2}\b", cleaned)
    if not year_match:
        return None
    year = int(year_match.group())
    month_match = re.match(r"([a-z]+)", cleaned)
    if month_match:
        month = MONTH_NUMBERS.get(month_match.group(1)[:3], 1)
    else:
        month = 12 if end else 1
    return year * 12 + month


def _extract_date_ranges(lines: list[str]) -> list[DateRange]:
    ranges: list[DateRange] = []
    for line in lines:
        for match in DATE_RANGE_RE.finditer(line):
            start_label = match.group("start")
            end_label = match.group("end")
            start_month = _month_index(start_label)
            if start_month is None:
                continue
            style = (
                "month_year"
                if re.search(MONTH_PATTERN, start_label, re.IGNORECASE)
                else "year_only"
            )
            ranges.append(
                DateRange(
                    source_line=line.strip()[:240],
                    start_label=start_label,
                    end_label=end_label,
                    start_month=start_month,
                    end_month=_month_index(end_label, end=True),
                    format_style=style,
                    separator=match.group("separator").lower(),
                )
            )
    return ranges


def _issue(
    category: str,
    severity: str,
    message: str,
    evidence: str,
    recommendation: str,
) -> QualityIssue:
    return QualityIssue(category, severity, message, evidence[:280], recommendation)


def analyze_resume_quality(resume_text: str) -> ResumeQualityReport:
    """Return explainable resume-only quality feedback."""
    text = (resume_text or "").replace("\r\n", "\n").strip()
    source_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    word_count = len(re.findall(r"\b[\w+#.-]+\b", text))
    sections = _detect_sections(lines)
    issues: list[QualityIssue] = []
    strengths: list[str] = []

    # Structure and hierarchy — 25 points.
    structure_score = 25
    required_sections = {
        "experience": (9, "Add a clearly labelled EXPERIENCE or PROFESSIONAL EXPERIENCE section."),
        "skills": (5, "Add a focused SKILLS section with readable skill categories."),
        "education": (4, "Add an EDUCATION section, even when experience is the main selling point."),
    }
    for section, (penalty, recommendation) in required_sections.items():
        if section not in sections:
            structure_score -= penalty
            issues.append(
                _issue(
                    "Structure",
                    "high" if section == "experience" else "medium",
                    f"No standard {section.title()} section was detected.",
                    "Section heading not found in the extracted resume text.",
                    recommendation,
                )
            )
    if "summary" not in sections:
        structure_score -= 2
        issues.append(
            _issue(
                "Structure",
                "low",
                "No professional summary was detected.",
                "No SUMMARY, PROFILE, or equivalent heading was found.",
                "Add a concise 3–5 line summary if it helps explain your level and specialism.",
            )
        )
    if sections.get("skills", 10**6) < sections.get("experience", -1):
        strengths.append("The skills section is positioned early for fast scanning.")
    if len(sections) >= 3:
        strengths.append("The resume uses recognizable section headings.")

    # Language, grammar signals, and bullet quality — 25 points.
    language_score = 25
    pronouns = re.findall(r"\b(?:I|me|my|mine|we|our|ours)\b", text, re.IGNORECASE)
    if pronouns:
        language_score -= min(5, len(pronouns))
        issues.append(
            _issue(
                "Grammar & style",
                "medium",
                "First-person pronouns weaken standard resume style.",
                ", ".join(pronouns[:8]),
                "Remove the pronouns and begin statements with direct action verbs.",
            )
        )
    spacing_examples = [
        line
        for line in lines
        if "@" not in line
        and "http://" not in line.lower()
        and "https://" not in line.lower()
        and re.search(r"\s{2,}|[A-Za-z]\s+[,.!?;:]|[,.!?;:][A-Za-z]", line)
    ]
    if spacing_examples:
        language_score -= min(4, len(spacing_examples))
        issues.append(
            _issue(
                "Grammar & style",
                "medium",
                "Inconsistent spacing or punctuation was detected.",
                spacing_examples[0],
                "Normalize spacing and punctuation, then proofread the affected lines.",
            )
        )
    common_usage = [
        (r"\bresponsible of\b", "responsible for"),
        (r"\bcomprised of\b", "composed of"),
        (r"\bhelped to\b", "a direct action verb"),
        (r"\bworked on\b", "a precise action verb"),
        (r"\bduties included\b", "a direct action verb"),
    ]
    for pattern, replacement in common_usage:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            language_score -= 2
            issues.append(
                _issue(
                    "Grammar & style",
                    "medium",
                    f'Weak or incorrect wording: “{match.group()}”.',
                    match.group(),
                    f"Replace it with {replacement} and describe the specific action.",
                )
            )
    bullet_lines = [
        line for line in lines if re.match(r"^[•●▪◦*-]\s+\S", line)
    ]
    long_bullets = [
        line for line in bullet_lines if len(re.findall(r"\b\w+\b", line)) > 40
    ]
    if long_bullets:
        language_score -= min(5, len(long_bullets) * 2)
        issues.append(
            _issue(
                "Grammar & style",
                "medium",
                f"{len(long_bullets)} bullet(s) exceed 40 words.",
                long_bullets[0],
                "Split or tighten long bullets so each communicates one action and its result.",
            )
        )
    bullet_punctuation = [line[-1] in ".;!?" for line in bullet_lines if line]
    if len(bullet_punctuation) >= 3 and len(set(bullet_punctuation)) > 1:
        language_score -= 2
        issues.append(
            _issue(
                "Grammar & style",
                "low",
                "Bullet-ending punctuation is inconsistent.",
                "Some bullets end with punctuation while others do not.",
                "Choose one convention and apply it consistently to every experience bullet.",
            )
        )
    if len(bullet_lines) >= 4 and not long_bullets:
        strengths.append("Experience content is broken into concise, scannable bullets.")

    # Chronology and date consistency — 25 points.
    chronology_score = 25
    experience_lines = _experience_lines(lines, sections)
    date_ranges = _extract_date_ranges(experience_lines)
    if not date_ranges:
        chronology_score -= 12
        issues.append(
            _issue(
                "Dates & chronology",
                "high",
                "No employment date ranges were reliably detected.",
                "The experience section has no parseable YYYY–YYYY or Mon YYYY–Mon YYYY range.",
                "Add a consistent date range to every role and align dates in the source document.",
            )
        )
    else:
        styles = {item.format_style for item in date_ranges}
        separators = {item.separator for item in date_ranges}
        if len(styles) > 1:
            chronology_score -= 5
            issues.append(
                _issue(
                    "Dates & chronology",
                    "medium",
                    "Employment dates mix year-only and month-year formats.",
                    "; ".join(
                        f"{item.start_label} {item.separator} {item.end_label}"
                        for item in date_ranges[:4]
                    ),
                    "Use one format throughout, preferably Mon YYYY – Mon YYYY.",
                )
            )
        if len(separators) > 1:
            chronology_score -= 2
            issues.append(
                _issue(
                    "Dates & chronology",
                    "low",
                    "Date-range separators are inconsistent.",
                    ", ".join(sorted(separators)),
                    "Use the same separator for every date range.",
                )
            )
        starts = [item.start_month for item in date_ranges]
        if any(starts[index] < starts[index + 1] for index in range(len(starts) - 1)):
            chronology_score -= 6
            issues.append(
                _issue(
                    "Dates & chronology",
                    "high",
                    "Roles do not appear to be in reverse-chronological order.",
                    " | ".join(item.source_line for item in date_ranges[:4]),
                    "Place the most recent role first and order earlier roles by start date.",
                )
            )
        ordered = sorted(date_ranges, key=lambda item: item.start_month, reverse=True)
        possible_gaps: list[tuple[int, DateRange, DateRange]] = []
        for newer, older in zip(ordered, ordered[1:]):
            if older.end_month is None:
                continue
            gap_months = newer.start_month - older.end_month - 1
            if gap_months >= 6:
                possible_gaps.append((gap_months, older, newer))
        for gap_months, older, newer in possible_gaps[:3]:
            chronology_score -= min(5, 2 + gap_months // 12)
            issues.append(
                _issue(
                    "Dates & chronology",
                    "medium",
                    f"Possible employment gap of about {gap_months} months.",
                    f"{older.end_label} to {newer.start_label}",
                    "Confirm the dates. If accurate, prepare a concise explanation or add relevant work, study, caregiving, or projects when appropriate.",
                )
            )
        if len(styles) == 1 and not possible_gaps:
            strengths.append("Detected employment dates use a consistent format without an obvious gap.")

    # ATS readability — 25 points.
    ats_score = 25
    email_found = bool(
        re.search(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", text, re.IGNORECASE)
    )
    phone_found = bool(re.search(r"(?:\+?\d[\d ()-]{7,}\d)", text))
    if not email_found:
        ats_score -= 4
        issues.append(
            _issue(
                "ATS readability",
                "high",
                "No email address was detected.",
                "Contact details could not be verified in the extracted text.",
                "Place a professional email in the main document body, not only in a header or image.",
            )
        )
    if not phone_found:
        ats_score -= 2
        issues.append(
            _issue(
                "ATS readability",
                "medium",
                "No phone number was detected.",
                "Contact details could not be verified in the extracted text.",
                "Add a reachable phone number in the main document body.",
            )
        )
    if word_count < 180:
        ats_score -= 5
        issues.append(
            _issue(
                "ATS readability",
                "medium",
                "The resume appears unusually short.",
                f"Approximately {word_count} words were extracted.",
                "Confirm that the PDF extracted fully and that key experience and achievements are present.",
            )
        )
    elif word_count > 1_300:
        ats_score -= 5
        issues.append(
            _issue(
                "ATS readability",
                "medium",
                "The resume may be too dense.",
                f"Approximately {word_count} words were extracted.",
                "Remove low-value repetition and prioritize recent, relevant achievements.",
            )
        )
    multi_column_signals = [line for line in lines if len(re.findall(r"\s{4,}", line)) >= 2]
    if multi_column_signals:
        ats_score -= 4
        issues.append(
            _issue(
                "ATS readability",
                "medium",
                "Extracted text suggests possible multi-column alignment.",
                multi_column_signals[0],
                "Verify reading order in the PDF and prefer a simple single-column layout.",
            )
        )
    if len(lines) >= 8 and len(sections) >= 3:
        strengths.append("The extracted text has a clear, ATS-readable hierarchy.")

    dimension_values = (
        (
            "Structure & hierarchy",
            max(0, structure_score),
            "Standard sections, ordering, and recruiter scanability.",
        ),
        (
            "Grammar & bullet style",
            max(0, language_score),
            "Wording, punctuation, concision, and resume voice.",
        ),
        (
            "Dates & chronology",
            max(0, chronology_score),
            "Date consistency, role order, and possible timeline gaps.",
        ),
        (
            "ATS readability",
            max(0, ats_score),
            "Contact parsing, text density, and layout risk signals.",
        ),
    )
    dimensions = tuple(
        QualityDimension(label, score, 25, explanation)
        for label, score, explanation in dimension_values
    )
    score = sum(item.score for item in dimensions)
    grade = (
        "Excellent"
        if score >= 90
        else "Strong"
        if score >= 80
        else "Competitive"
        if score >= 70
        else "Needs work"
        if score >= 55
        else "High risk"
    )
    severity_order = {"high": 0, "medium": 1, "low": 2}
    issues.sort(key=lambda item: (severity_order[item.severity], item.category))
    return ResumeQualityReport(
        score=score,
        grade=grade,
        source_hash=source_hash,
        word_count=word_count,
        detected_sections=tuple(sections.keys()),
        dimensions=dimensions,
        strengths=tuple(dict.fromkeys(strengths)),
        issues=tuple(issues),
        date_ranges=tuple(date_ranges),
    )

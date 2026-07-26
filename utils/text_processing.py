"""
utils/text_processing.py — PDF extraction, keyword matching, and text sanitization.
"""

import html
import re

import PyPDF2 as pdf
from utils.ats_engine import (
    analyze_alignment,
    canonical_resume_section,
    extract_alignment_terms,
    extract_resume_profile,
)


BULLET_PREFIX_RE = re.compile(r"^\s*[•▪◦●\uf0b7*\-–—]\s+")
INLINE_GLYPH_BULLET_RE = re.compile(r"\s+[•▪◦●\uf0b7]\s+")
INLINE_DASH_BULLET_RE = re.compile(
    r"(?<=[.!?;:])\s+[-*]\s+(?=[A-Z0-9])"
)


# ──────────────────────────────────────────────────────────────
# PDF Extraction
# ──────────────────────────────────────────────────────────────

def extract_text_from_pdf(uploaded_file) -> str:
    """Extract plain text from an uploaded PDF file object."""
    try:
        reader = pdf.PdfReader(uploaded_file)
        parts = []
        for page in reader.pages:
            try:
                txt = page.extract_text()
            except Exception:
                txt = ""
            if txt:
                parts.append(txt)
        return normalize_resume_structure("\n".join(parts))
    except Exception:
        return ""


# ──────────────────────────────────────────────────────────────
# Unified alignment compatibility helpers
# ──────────────────────────────────────────────────────────────

STOPWORDS = {
    "and", "or", "the", "a", "an", "to", "with", "of", "for", "in", "on",
    "by", "that", "is", "are", "as", "at", "from", "be", "using",
    "experience", "years", "year", "able", "work", "working", "ability",
}


def extract_keyword_set(text: str, min_len: int = 3) -> set:
    """Return the canonical phrase-, synonym-, and morphology-aware term set."""
    if not text:
        return set()
    return {
        term
        for term in extract_alignment_terms(text)
        if len(term) >= min_len and term not in STOPWORDS
    }


def compute_match_score(jd_text: str, resume_text: str):
    """
    Compute the explainable Job Alignment Score.

    Returns:
        (score: int, matched: list[str], missing: list[str])

    This compatibility wrapper keeps the existing UI contract. New code should
    use ``analyze_alignment`` to display the score dimensions and confidence.
    """
    if not jd_text.strip() or not resume_text.strip():
        return 0, [], []
    report = analyze_alignment(jd_text, resume_text)
    missing = report.missing_required + report.missing_preferred
    return report.score, report.matched_terms, missing


# ──────────────────────────────────────────────────────────────
# Text Sanitization & Cleaning
# ──────────────────────────────────────────────────────────────

def sanitize_display_text(text: str, placeholder: str = "[Removed]") -> str:
    """Basic sanitization to prevent injection in displayed output."""
    if not text:
        return ""
    if len(text) > 25_000:
        return f"{placeholder} — output too large to display safely."
    lowered = text.lower()
    if "{" in lowered and "}" in lowered and "background" in lowered:
        return f"{placeholder} — removed suspicious styling content."
    return text


def sanitize_candidate_feedback(text: str, source_text: str = "") -> str:
    """Remove internal notation and unsafe hypothetical claims from feedback."""
    clean = sanitize_display_text(text)
    if not clean:
        return ""
    clean = re.sub(r"\[(?:E|R|ROLE)\d{3}\]", "", clean, flags=re.I)
    clean = re.sub(r"\b(?:E|R|ROLE)\d{3}\b", "", clean, flags=re.I)
    clean = re.sub(r"\(\s*(?:[,;/]\s*)*\)", "", clean)
    if source_text:
        source_flat = re.sub(r"\s+", " ", source_text).casefold()
        guarded_lines = []
        for line in clean.splitlines():
            line = re.sub(
                r"\s*\((?:e\.g\.|for example),?[^)]*\)",
                "",
                line,
                flags=re.I,
            )
            if re.search(r"\*\*rewrite:\*\*", line, flags=re.I):
                line = re.sub(
                    r"\s*\*\*rewrite:\*\*.*$",
                    " **Safe action:** retain the source wording until the candidate "
                    "verifies an exact outcome or metric.",
                    line,
                    flags=re.I,
                )
            is_edit = bool(re.search(
                r"\b(?:add|insert|include|rewrite|replace|specify)\b",
                line,
                flags=re.I,
            ))
            has_hypothetical = bool(re.search(
                r"(?:\be\.g\.|\bfor example\b|\bsuch as\b)",
                line,
                flags=re.I,
            ))
            numeric_claims = re.findall(
                r"\b\d+(?:\.\d+)?\s*(?:%|percent|hours?|days?|weeks?|months?|years?)\b",
                line,
                flags=re.I,
            )
            has_unsupported_number = any(
                re.sub(r"\s+", " ", claim).casefold() not in source_flat
                for claim in numeric_claims
            )
            if is_edit and (has_hypothetical or has_unsupported_number):
                prefix_match = re.match(
                    r"^(\s*(?:[-*]\s*)?(?:\*\*[^*]+\*\*|[^–—:\n]+))"
                    r"(?:\s*[–—:]\s*).*$",
                    line,
                )
                prefix = prefix_match.group(1).rstrip() if prefix_match else line.split(
                    "e.g.", 1
                )[0].rstrip(" ,;:–—-")
                line = (
                    prefix
                    + " — ask the candidate for the exact verified detail; "
                    "leave it as a documented gap if none exists."
                )
            elif is_edit:
                line = re.sub(
                    r"\s*\(e\.g\.,[^)]*\)",
                    "",
                    line,
                    flags=re.I,
                )
                line = re.sub(
                    r"\s+[–—-]\s*e\.g\.,?.*$",
                    " — ask the candidate for the exact verified detail; "
                    "leave it as a gap if none exists.",
                    line,
                    flags=re.I,
                )
            guarded_lines.append(line)
        clean = "\n".join(guarded_lines)
    clean = re.sub(r" {2,}", " ", clean)
    clean = re.sub(r"\*\*\s*##\s*", "## ", clean)
    return clean.strip()


def finalize_cover_letter(
    text: str,
    source_text: str = "",
    candidate_name: str = "",
) -> str:
    """Remove internal citations, unsafe training extrapolation, and truncation."""
    clean = sanitize_display_text(text)
    if not clean:
        return ""
    clean = re.sub(
        r"\s*(?:【\s*E\d{3}\s*】|\[\s*E\d{3}\s*\])",
        "",
        clean,
        flags=re.I,
    )
    clean = re.sub(
        r"\s*,?\s*(?:which\s+)?equips me to[^.!?]*(?=[.!?])",
        "",
        clean,
        flags=re.I,
    )

    source_lower = re.sub(r"\s+", " ", source_text).casefold()
    has_compliance_action = bool(re.search(
        r"\b(?:ensur(?:e|ed|ing)|upheld|complied|adhered|enforced)\b.{0,80}"
        r"\b(?:hse|phytosanitary|hygiene|compliance|protocols?)\b",
        source_lower,
        flags=re.I,
    ))
    if not has_compliance_action:
        clean = re.sub(
            r"(?<=[.!?]\s)|^"
            r"[^.!?]*\b(?:ensur(?:e|ed|ing)|uphold|complied|adhered|enforced)\b"
            r"[^.!?]*\b(?:hse|phytosanitary|hygiene|compliance|protocols?)\b"
            r"[^.!?]*[.!?]\s*",
            "",
            clean,
            flags=re.I,
        )

    paragraphs = [value.strip() for value in re.split(r"\n\s*\n", clean) if value.strip()]
    if paragraphs and not re.search(r"[.!?\"”]$", paragraphs[-1]):
        paragraphs.pop()
    clean = "\n\n".join(paragraphs).strip()

    if not re.search(
        r"\b(?:sincerely|kind regards|best regards|respectfully)\b",
        clean[-400:],
        flags=re.I,
    ):
        signatory = candidate_name.strip() or "Candidate"
        clean = (
            clean.rstrip()
            + "\n\nThank you for considering my application. I would welcome the "
            "opportunity to discuss how my verified experience can support this role."
            + "\n\nSincerely,\n"
            + signatory
        )
    return clean.strip()


def clean_resume_output(text: str) -> str:
    """Strip markdown formatting symbols from AI-generated resume text."""
    if not text:
        return ""
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"\*\*", "", text)
    text = re.sub(r"^_{2,}\s*$", "", text, flags=re.MULTILINE)
    text = re.sub(r"^[-\*_]{3,}\s*$", "", text, flags=re.MULTILINE)
    return normalize_resume_structure(text)


def normalize_resume_structure(text: str) -> str:
    """Normalize line endings and restore explicit bullet boundaries.

    PDF extractors and language models sometimes return multiple visible bullets
    inside one paragraph. Converting every recognized marker to a dedicated
    source line gives the browser preview, truth audit, and DOCX builder the same
    deterministic structure.
    """
    if not text:
        return ""
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    output: list[str] = []
    for raw_line in normalized.splitlines():
        line = re.sub(r"[ \t]+", " ", raw_line).strip()
        if not line:
            if output and output[-1] != "":
                output.append("")
            continue
        line = INLINE_GLYPH_BULLET_RE.sub("\n- ", line)
        if BULLET_PREFIX_RE.match(line):
            line = BULLET_PREFIX_RE.sub("- ", line, count=1)
            line = INLINE_DASH_BULLET_RE.sub("\n- ", line)
        for fragment in line.split("\n"):
            clean = fragment.strip()
            if clean:
                output.append(clean)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(output)).strip()


def _display_section_key(line: str) -> str | None:
    return canonical_resume_section(line)


def _is_contact_line(line: str, profile) -> bool:
    lowered = line.lower()
    known_values = (
        profile.contact.emails
        + profile.contact.phones
        + profile.contact.links
    )
    return bool(
        any(value and value in line for value in known_values)
        or any(
            marker in lowered
            for marker in ("@", "email", "phone", "linkedin", "github")
        )
    )


def format_resume_for_display(text: str) -> str:
    """Render a safe, semantic, single-column resume preview as HTML."""
    if not text:
        return ""
    text = normalize_resume_structure(text)
    profile = extract_resume_profile(text)
    lines = text.splitlines()
    out = [
        """
<style>
.ats-resume-preview{background:#fff;color:#263645;border:1px solid #d8e1ea;
border-top:5px solid #1b7f79;border-radius:12px;padding:34px 40px;
box-shadow:0 10px 30px rgba(23,54,93,.09);font-family:Arial,sans-serif;
font-size:15px;line-height:1.5;max-width:900px;margin:0 auto}
.ats-resume-preview h1{color:#17365d;font-size:30px;line-height:1.15;
margin:0 0 5px;font-weight:750;letter-spacing:-.02em}
.ats-resume-preview .contact{color:#536779;font-size:13px;margin:0 0 18px;
word-break:break-word}
.ats-resume-preview h2{color:#17365d;font-size:15px;line-height:1.25;
letter-spacing:.075em;margin:22px 0 9px;padding-bottom:5px;
border-bottom:2px solid #1b7f79;font-weight:750}
.ats-resume-preview p{margin:0 0 8px}
.ats-resume-preview .record{margin:13px 0 4px;color:#263645}
.ats-resume-preview .record .primary{font-weight:700;color:#17365d}
.ats-resume-preview .record .separator{color:#1b7f79;padding:0 5px}
.ats-resume-preview .skill-line{margin:0 0 6px}
.ats-resume-preview .skill-line strong{color:#17365d}
.ats-resume-preview ul{margin:5px 0 10px;padding-left:23px}
.ats-resume-preview li{margin:0 0 7px;padding-left:3px;line-height:1.48}
.ats-resume-preview li::marker{color:#1b7f79}
@media(max-width:700px){.ats-resume-preview{padding:24px 20px;font-size:14px}
.ats-resume-preview h1{font-size:25px}}
</style>
<article class="ats-resume-preview">
"""
    ]
    in_core_skills = False
    list_open = False
    name_written = False

    def close_list():
        nonlocal list_open
        if list_open:
            out.append("</ul>")
            list_open = False

    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            continue

        clean_line = re.sub(r"\*\*", "", line).strip()
        if (
            profile.candidate_name
            and not name_written
            and clean_line.casefold() == profile.candidate_name.casefold()
        ):
            close_list()
            out.append(f"<h1>{html.escape(clean_line)}</h1>")
            name_written = True
            continue

        section = _display_section_key(clean_line)
        if section:
            close_list()
            in_core_skills = section == "skills"
            out.append(f"<h2>{html.escape(clean_line.rstrip(':').upper())}</h2>")
            continue

        if _is_contact_line(clean_line, profile):
            close_list()
            out.append(
                f'<div class="contact">{html.escape(clean_line)}</div>'
            )
            continue

        if not in_core_skills and BULLET_PREFIX_RE.match(clean_line):
            if not list_open:
                out.append("<ul>")
                list_open = True
            bullet = BULLET_PREFIX_RE.sub("", clean_line, count=1).strip()
            out.append(f"<li>{html.escape(bullet)}</li>")
            continue

        close_list()
        if in_core_skills and ":" in clean_line:
            label, value = clean_line.split(":", 1)
            out.append(
                '<p class="skill-line"><strong>'
                + html.escape(label.strip())
                + ":</strong> "
                + html.escape(value.strip())
                + "</p>"
            )
            continue

        if "|" in clean_line and not clean_line.startswith("["):
            parts = [part.strip() for part in clean_line.split("|") if part.strip()]
            rendered_parts = []
            for index, part in enumerate(parts):
                if index:
                    rendered_parts.append('<span class="separator">|</span>')
                cls = ' class="primary"' if index == 0 else ""
                rendered_parts.append(f"<span{cls}>{html.escape(part)}</span>")
            out.append('<div class="record">' + "".join(rendered_parts) + "</div>")
            continue

        out.append(f"<p>{html.escape(clean_line)}</p>")

    close_list()
    out.append("</article>")
    return "\n".join(out)

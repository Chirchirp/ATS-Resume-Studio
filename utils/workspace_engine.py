"""Phase 3 application workspace, positioning, versioning, and evaluation tools."""

from __future__ import annotations

import difflib
import hashlib
import re
from dataclasses import dataclass
from datetime import datetime, timezone

from utils.ats_engine import analyze_alignment
from utils.domain_profiles import DomainContext
from utils.evidence_engine import EvidenceLedger, EvidenceMatrix, validate_generated_claims


@dataclass(frozen=True)
class PositioningStrategy:
    id: str
    name: str
    thesis: str
    evidence_ids: tuple[str, ...]
    best_for: str
    risk: str


@dataclass(frozen=True)
class RecruiterObjection:
    priority: str
    objection: str
    evidence_response: str
    preparation: str


@dataclass(frozen=True)
class InterviewQuestion:
    question: str
    evidence_ids: tuple[str, ...]
    answer_plan: str


@dataclass(frozen=True)
class DocumentVersion:
    id: str
    created_at: str
    label: str
    strategy_id: str
    text: str
    alignment_score: int
    support_rate: int
    source_hash: str


@dataclass(frozen=True)
class ChangeImpact:
    original_score: int
    optimized_score: int
    word_delta: int
    metric_delta: int
    matched_term_delta: int
    added_lines: tuple[str, ...]
    removed_lines: tuple[str, ...]


def build_positioning_strategies(
    ledger: EvidenceLedger,
    matrix: EvidenceMatrix,
    domain: DomainContext,
) -> list[PositioningStrategy]:
    contextual = [
        item for item in ledger.items
        if item.section in {"experience", "projects", "clarification"}
    ]
    quantified = [item for item in contextual if item.metrics]
    direct_ids = tuple(
        dict.fromkeys(
            evidence_id
            for row in matrix.rows
            if row.status == "direct"
            for evidence_id in row.evidence_ids
        )
    )
    outcome_ids = tuple(item.id for item in quantified[:6])
    transferable_ids = tuple(
        dict.fromkeys(
            evidence_id
            for row in matrix.rows
            if row.status in {"equivalent", "transferable"}
            for evidence_id in row.evidence_ids
        )
    )
    strongest = tuple(item.id for item in contextual[:6])
    return [
        PositioningStrategy(
            id="direct_fit",
            name=f"Direct {domain.profile.label} Fit",
            thesis=(
                "Lead with the strongest demonstrated overlap between candidate evidence "
                "and required work, using the employer's language only where evidence supports it."
            ),
            evidence_ids=direct_ids or strongest,
            best_for="Applications with several directly evidenced required capabilities.",
            risk="Weak requirements must remain gaps rather than being disguised as experience.",
        ),
        PositioningStrategy(
            id="business_impact",
            name="Verified Business Impact",
            thesis=(
                "Lead with measurable decisions, efficiency, quality, adoption, or operational "
                "outcomes and show the analytical or professional method behind them."
            ),
            evidence_ids=outcome_ids or strongest,
            best_for="Candidates with defensible metrics or clear outcome evidence.",
            risk="Do not force metrics onto work where no result was measured.",
        ),
        PositioningStrategy(
            id="transferable_growth",
            name="Transferable Capability & Growth",
            thesis=(
                "Position adjacent experience honestly, making the transfer mechanism explicit "
                "and separating demonstrated capability from skills still being developed."
            ),
            evidence_ids=transferable_ids or strongest,
            best_for="Career transitions, sector changes, and partial requirement coverage.",
            risk="Avoid claiming immediate mastery of missing domain tools or regulations.",
        ),
    ]


def build_recruiter_objections(
    matrix: EvidenceMatrix,
    ledger: EvidenceLedger,
    limit: int = 5,
) -> list[RecruiterObjection]:
    objections: list[RecruiterObjection] = []
    by_id = ledger.by_id()
    ordered = sorted(
        matrix.rows,
        key=lambda row: (
            0 if row.priority == "required" else 1,
            {"missing": 0, "mention_only": 1, "transferable": 2, "equivalent": 3, "direct": 4}.get(row.status, 5),
        ),
    )
    for row in ordered:
        if row.status in {"direct", "equivalent"}:
            continue
        evidence = "; ".join(
            f"“{by_id[item_id].text}”"
            for item_id in row.evidence_ids
            if item_id in by_id
        )
        objections.append(
            RecruiterObjection(
                priority="Critical" if row.priority == "required" and row.status == "missing" else "High",
                objection=f"{row.requirement} — coverage is {row.status}.",
                evidence_response=evidence or "No candidate evidence currently supports this requirement.",
                preparation=(
                    "Provide a verified example with context, personal action, and outcome."
                    if row.status != "missing"
                    else "Do not bluff. State the gap, identify adjacent evidence, and explain a concrete learning plan."
                ),
            )
        )
        if len(objections) >= limit:
            break
    return objections


def build_interview_questions(
    matrix: EvidenceMatrix,
    ledger: EvidenceLedger,
    domain: DomainContext,
    limit: int = 6,
) -> list[InterviewQuestion]:
    questions: list[InterviewQuestion] = []
    for row in matrix.rows:
        if not row.evidence_ids:
            continue
        ids = tuple(row.evidence_ids[:2])
        questions.append(
            InterviewQuestion(
                question=f"Tell me about a time you demonstrated: {row.requirement}",
                evidence_ids=ids,
                answer_plan=(
                    "Situation: establish relevant context. Task: clarify your ownership. "
                    "Action: explain method and judgment. Result: use only verified outcomes."
                ),
            )
        )
        if len(questions) >= limit:
            break
    if len(questions) < limit:
        questions.append(
            InterviewQuestion(
                question=f"How do you approach quality and stakeholder trust in {domain.profile.label} work?",
                evidence_ids=(),
                answer_plan=(
                    "Choose a real example involving validation, communication, documentation, "
                    "or correction of an error. Do not answer only with principles."
                ),
            )
        )
    return questions[:limit]


def create_document_version(
    existing: list[DocumentVersion],
    *,
    label: str,
    strategy_id: str,
    text: str,
    jd_text: str,
    ledger: EvidenceLedger,
) -> list[DocumentVersion]:
    digest = hashlib.sha256(
        (strategy_id + "\n" + text + "\n" + ledger.source_hash).encode("utf-8")
    ).hexdigest()[:12]
    if any(version.source_hash == digest for version in existing):
        return existing
    alignment = analyze_alignment(jd_text, text)
    validation = validate_generated_claims(text, ledger, jd_text)
    version = DocumentVersion(
        id=f"V{len(existing) + 1:03d}",
        created_at=datetime.now(timezone.utc).isoformat(),
        label=label,
        strategy_id=strategy_id,
        text=text,
        alignment_score=alignment.score,
        support_rate=validation.support_rate,
        source_hash=digest,
    )
    return existing + [version]


def compare_versions(original: str, optimized: str, jd_text: str) -> ChangeImpact:
    original_report = analyze_alignment(jd_text, original)
    optimized_report = analyze_alignment(jd_text, optimized)
    original_metrics = len(re.findall(r"(?:[$£€]\s*)?\d[\d,.]*\s?%?", original))
    optimized_metrics = len(re.findall(r"(?:[$£€]\s*)?\d[\d,.]*\s?%?", optimized))
    diff = list(
        difflib.ndiff(
            [line.strip() for line in original.splitlines() if line.strip()],
            [line.strip() for line in optimized.splitlines() if line.strip()],
        )
    )
    added = tuple(line[2:] for line in diff if line.startswith("+ "))[:20]
    removed = tuple(line[2:] for line in diff if line.startswith("- "))[:20]
    return ChangeImpact(
        original_score=original_report.score,
        optimized_score=optimized_report.score,
        word_delta=len(optimized.split()) - len(original.split()),
        metric_delta=optimized_metrics - original_metrics,
        matched_term_delta=(
            len(optimized_report.matched_terms) - len(original_report.matched_terms)
        ),
        added_lines=added,
        removed_lines=removed,
    )

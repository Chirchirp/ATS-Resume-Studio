"""Phase 0 functional contracts used during the Cloudflare migration."""

from __future__ import annotations

import json
from pathlib import Path

from utils.ats_engine import analyze_alignment
from utils.resume_quality_engine import analyze_resume_quality


BASELINE = Path(__file__).resolve().parent.parent / "docs" / "baseline"


def _fixtures() -> tuple[str, str, dict]:
    resume = (BASELINE / "fixtures" / "sample_resume.txt").read_text(
        encoding="utf-8"
    ).strip()
    jd = (BASELINE / "fixtures" / "sample_job_description.txt").read_text(
        encoding="utf-8"
    ).strip()
    expected = json.loads(
        (BASELINE / "expected-results.json").read_text(encoding="utf-8")
    )
    return resume, jd, expected


def test_alignment_baseline_contract():
    resume, jd, expected = _fixtures()
    contract = expected["alignment"]
    report = analyze_alignment(jd, resume)

    assert report.score == contract["score"]
    assert report.confidence == contract["confidence"]
    assert len(report.matched_terms) == contract["matched_term_count"]
    assert report.matched_terms == contract["matched_terms"]
    assert len(report.missing_required) == contract["missing_required_count"]
    assert len(report.missing_preferred) == contract["missing_preferred_count"]
    assert len(report.knockout_risks) == contract["knockout_risk_count"]
    assert [dimension.label for dimension in report.dimensions] == contract[
        "dimension_labels"
    ]
    assert len(report.resume.roles) == contract["resume_profile"]["roles"]
    assert sum(len(role.bullets) for role in report.resume.roles) == contract[
        "resume_profile"
    ]["role_bullets"]
    assert len(report.resume.declared_skills) == contract["resume_profile"][
        "declared_skills"
    ]
    assert report.resume.has_contact is contract["resume_profile"]["has_contact"]


def test_resume_quality_baseline_contract():
    resume, _, expected = _fixtures()
    contract = expected["resume_quality"]
    report = analyze_resume_quality(resume)

    assert report.score == contract["score"]
    assert report.grade == contract["grade"]
    assert report.word_count == contract["word_count"]
    assert list(report.detected_sections) == contract["detected_sections"]
    assert {
        dimension.label: dimension.score for dimension in report.dimensions
    } == contract["dimension_scores"]
    assert len(report.issues) == contract["issue_count"]
    assert (
        sum(issue.severity.lower() == "high" for issue in report.issues)
        == contract["high_priority_issue_count"]
    )
    assert len(report.date_ranges) == contract["date_range_count"]

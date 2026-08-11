from components.tab_premium import _apply_alignment_no_regression_gate
from utils.ats_engine import analyze_alignment
from utils.evidence_engine import (
    allocate_role_bullet_targets,
    build_evidence_ledger,
    build_evidence_matrix,
    build_safe_evidence_resume,
    strip_generation_annotations,
)


def test_clean_resume_cannot_regress_against_project_heavy_source():
    source = """Jane Doe
jane@example.com

SKILLS
SQL

EXPERIENCE
Data Analyst | Acme Ltd | 2022 - Present
- Built weekly SQL reports for management.

PROJECTS
Automation Portfolio
- Developed Python workflow automation for recurring reports.

EDUCATION
BSc Statistics | Example University | 2021
"""
    jd = """Data Analyst
Requirements:
- Python and SQL are required
Responsibilities:
- Develop workflow automation for recurring reports
"""
    ledger = build_evidence_ledger(source)
    matrix = build_evidence_matrix(jd, ledger)
    plans = allocate_role_bullet_targets(
        ledger,
        matrix,
        target_pages=2,
    )
    strict_draft = build_safe_evidence_resume(
        ledger,
        jd,
        plans,
        target_pages=2,
    )
    accepted, validation, _, gate = _apply_alignment_no_regression_gate(
        strict_draft,
        ledger,
        source_resume=source,
        jd_text=jd,
        role_plans=plans,
        target_pages=2,
    )
    visible = strip_generation_annotations(accepted)

    assert gate["passed"]
    assert gate["delta"] >= 0
    assert analyze_alignment(jd, visible).score >= analyze_alignment(jd, source).score
    assert validation.is_download_safe
    assert "PROJECTS" not in visible

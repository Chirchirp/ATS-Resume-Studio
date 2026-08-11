from types import SimpleNamespace

from utils.ats_engine import analyze_alignment
from utils.resume_strategy import build_keyword_xray, build_three_stage_audit


JD = """
Preferred qualifications
- Power BI and Smartsheet
Requirements
- SQL and Microsoft Excel
Responsibilities
- Build data visualisation dashboards and present reports to stakeholders
"""

RESUME = """
Jane Analyst
jane@example.com | linkedin.com/in/jane

PROFESSIONAL SUMMARY
Data Analyst focused on production reporting and decision support. Builds practical dashboards for operational teams. Translates data findings into clear management updates.

CORE SKILLS
- Analytics Tools: SQL | Microsoft Excel | Power BI
- Delivery: Stakeholder Management | Reporting

PROFESSIONAL EXPERIENCE
Data Analyst | Grower Ltd | Nairobi | 2022 - Present
- Built Power BI dashboards from SQL production data for management reporting.
- Presented weekly findings to operational stakeholders.

EDUCATION
BSc Data Analytics | Example University | 2021
"""


def test_keyword_xray_preserves_priority_buckets():
    xray = build_keyword_xray(analyze_alignment(JD, RESUME))
    assert [bucket.label for bucket in xray.buckets] == [
        "1 · Preferred qualifications",
        "2 · Hard requirements",
        "3 · Technical responsibilities",
    ]
    assert xray.supported_count > 0


def test_three_stage_audit_detects_human_reading_structure():
    audit = build_three_stage_audit(
        JD,
        RESUME,
        truth_validation=SimpleNamespace(is_download_safe=True),
    )
    assert [stage.name for stage in audit.stages] == ["Skim", "Scan", "Study"]
    assert audit.overall_score >= 60
    assert not audit.generic_phrases


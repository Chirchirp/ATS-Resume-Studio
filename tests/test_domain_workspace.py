import unittest

from utils.domain_profiles import (
    deterministic_field_label,
    infer_domain_context,
    normalize_field_label,
)
from utils.evidence_engine import build_evidence_ledger, build_evidence_matrix
from utils.workspace_engine import (
    build_interview_questions,
    build_positioning_strategies,
    build_recruiter_objections,
    compare_versions,
    create_document_version,
)


ANALYTICS_JD = """\
Data Analyst
Develop SQL, MS Excel, Smartsheet, data visualisation, and data cleaning proficiency.
Prepare management reports and provide ad hoc analytical insights.
Ensure data quality, validation, and documentation.
Provide dashboard training to end users.
Always comply with phytosanitary and HSE protocols on the horticulture site.
Requirements:
- SQL, Excel and Smartsheet experience required.
"""

RESUME = """\
Jane Doe
jane@example.com
SKILLS
SQL, Excel, Power BI
EXPERIENCE
Reporting Analyst | Acme | 2022 - Present
- Built 8 Power BI reports using validated SQL data for management reviews.
- Trained 12 users and reduced weekly reporting time by 30%.
EDUCATION
BSc Statistics | University | 2021
"""


class DomainWorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.domain = infer_domain_context(ANALYTICS_JD + "\n" + RESUME)
        self.ledger = build_evidence_ledger(RESUME)
        self.matrix = build_evidence_matrix(ANALYTICS_JD, self.ledger)

    def test_data_analytics_specialization_preserves_sector(self):
        self.assertEqual(self.domain.profile.id, "data_analytics")
        self.assertIn("Agriculture/Horticulture", self.domain.sector_signals)
        self.assertIn("data quality", self.domain.matched_signals)

    def test_field_label_uses_deterministic_domain_before_ai(self):
        self.assertEqual(
            deterministic_field_label(ANALYTICS_JD),
            "Data Analytics & Business Intelligence",
        )

    def test_empty_ai_field_label_has_safe_fallback(self):
        self.assertEqual(normalize_field_label(""), "General")
        self.assertEqual(normalize_field_label("\n\n"), "General")
        self.assertEqual(
            normalize_field_label("**Label:** Data Analytics"),
            "Data Analytics",
        )

    def test_unrelated_role_uses_universal_profile(self):
        context = infer_domain_context(
            "Museum guide needed to welcome visitors and explain exhibitions."
        )
        self.assertEqual(context.profile.id, "generic")

    def test_builds_three_distinct_positioning_strategies(self):
        strategies = build_positioning_strategies(
            self.ledger, self.matrix, self.domain
        )
        self.assertEqual(len(strategies), 3)
        self.assertEqual(
            {item.id for item in strategies},
            {"direct_fit", "business_impact", "transferable_growth"},
        )

    def test_objections_and_interview_questions_are_evidence_grounded(self):
        objections = build_recruiter_objections(self.matrix, self.ledger)
        self.assertTrue(any("Smartsheet" in item.objection for item in objections))
        questions = build_interview_questions(
            self.matrix, self.ledger, self.domain
        )
        self.assertTrue(questions)
        self.assertTrue(any(question.evidence_ids for question in questions))

    def test_version_creation_is_deduplicated(self):
        optimized = RESUME.replace(
            "Built 8 Power BI reports",
            "Built 8 Power BI management reports",
        )
        first = create_document_version(
            [],
            label="Test",
            strategy_id="direct_fit",
            text=optimized,
            jd_text=ANALYTICS_JD,
            ledger=self.ledger,
        )
        second = create_document_version(
            first,
            label="Duplicate",
            strategy_id="direct_fit",
            text=optimized,
            jd_text=ANALYTICS_JD,
            ledger=self.ledger,
        )
        self.assertEqual(len(first), 1)
        self.assertEqual(len(second), 1)

    def test_change_impact_is_deterministic(self):
        optimized = RESUME.replace(
            "Built 8 Power BI reports",
            "Built 8 validated Power BI management reports",
        )
        first = compare_versions(RESUME, optimized, ANALYTICS_JD)
        second = compare_versions(RESUME, optimized, ANALYTICS_JD)
        self.assertEqual(first, second)
        self.assertGreater(first.word_delta, 0)


if __name__ == "__main__":
    unittest.main()

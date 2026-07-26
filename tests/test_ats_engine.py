import unittest

from utils.ats_engine import (
    analyze_alignment,
    extract_alignment_terms,
    extract_job_profile,
    extract_ngram_phrases,
    extract_resume_profile,
    top_requirement_text,
)
from utils.text_processing import compute_match_score


JD = """\
Senior Data Analyst

Requirements:
- Required: 3+ years of experience using SQL and Python
- Power BI is required
- Amazon Web Services experience is preferred

Responsibilities:
- Analyze customer data and build executive dashboards
- Automate recurring reporting workflows
"""

STRONG_RESUME = """\
Jane Doe
jane@example.com | +254 700 000 000

PROFESSIONAL SUMMARY
Data analyst specializing in customer reporting and decision support.

CORE SKILLS
SQL, Python, Power BI, AWS

PROFESSIONAL EXPERIENCE
Data Analyst | Acme Ltd | Nairobi | 2021 - Present
- Automated recurring SQL reporting, reducing preparation time by 30%.
- Built 12 Power BI dashboards for executive and customer performance reviews.

EDUCATION
BSc Statistics | Example University | 2020
"""


class AtsEngineTests(unittest.TestCase):
    def test_role_date_ranges_are_not_extracted_as_phone_numbers(self):
        profile = extract_resume_profile(
            "Jane Doe\n"
            "jane@example.com | +254 700 000 000\n\n"
            "EXPERIENCE\n"
            "Data Analyst | Acme Ltd | 2016 - 2020\n"
            "- Prepared weekly reports.\n"
            "Reporting Officer | Beta Ltd | 2012 - 2016\n"
            "- Validated source data."
        )
        self.assertEqual(profile.contact.phones, ("+254 700 000 000",))

    def test_extended_resume_sections_are_extracted_without_absorption(self):
        profile = extract_resume_profile(
            "Jane Doe\n"
            "jane@example.com\n\n"
            "PROFESSIONAL PROFILE\n"
            "Data analyst supporting operational reporting.\n\n"
            "TECHNICAL PROFICIENCIES\n"
            "SQL, Power BI\n\n"
            "PROFESSIONAL EXPERIENCE\n"
            "Data Analyst | Acme Ltd | 2022 - Present\n"
            "- Built weekly reports.\n\n"
            "ACADEMIC BACKGROUND\n"
            "BSc Statistics | Example University | 2021\n\n"
            "PROFESSIONAL QUALIFICATIONS\n"
            "Power BI Data Analyst Associate | 2024\n\n"
            "KEY ACHIEVEMENTS\n"
            "- Operations Insight Award | 2023\n\n"
            "PROFESSIONAL MEMBERSHIPS\n"
            "Data Management Association\n\n"
            "REFERENCES\n"
            "Available on request"
        )
        self.assertEqual(
            profile.section_order,
            (
                "summary",
                "skills",
                "experience",
                "education",
                "certifications",
                "achievements",
                "memberships",
                "references",
            ),
        )
        self.assertIn("Operations Insight Award", profile.sections["achievements"])
        self.assertEqual(
            profile.certification_records[0].text,
            "Power BI Data Analyst Associate | 2024",
        )

    def test_content_ending_in_training_is_not_promoted_to_a_heading(self):
        profile = extract_resume_profile(
            "Amina Kamau\n\n"
            "CORE SKILLS\n"
            "Business Partnership: Requirements gathering, management reporting, user training\n\n"
            "PROFESSIONAL DEVELOPMENT\n"
            "Smartsheet Core Product Training | 2021"
        )
        self.assertEqual(
            profile.sections["skills"],
            "Business Partnership: Requirements gathering, management reporting, user training",
        )
        self.assertEqual(
            profile.sections["training"],
            "Smartsheet Core Product Training | 2021",
        )

    def test_extracts_structured_job_requirements(self):
        profile = extract_job_profile(JD)
        self.assertEqual(profile.title, "Senior Data Analyst")
        self.assertEqual(profile.minimum_years, 3)
        self.assertGreaterEqual(len(profile.required), 2)
        self.assertGreaterEqual(len(profile.preferred), 1)
        self.assertIn("Power BI is required", top_requirement_text(profile))

    def test_extracts_resume_identity_and_evidence(self):
        profile = extract_resume_profile(STRONG_RESUME)
        self.assertEqual(profile.candidate_name, "Jane Doe")
        self.assertTrue(profile.has_contact)
        self.assertIn("sql", profile.skills)
        self.assertIn("power bi", profile.skills)
        self.assertGreaterEqual(len(profile.metrics), 2)
        self.assertGreaterEqual(profile.estimated_years or 0, 3)
        self.assertEqual(len(profile.roles), 1)
        role = profile.roles[0]
        self.assertEqual(role.id, "ROLE001")
        self.assertEqual(role.title, "Data Analyst")
        self.assertEqual(role.employer, "Acme Ltd")
        self.assertEqual(role.location, "Nairobi")
        self.assertEqual(role.start_date, "2021")
        self.assertEqual(role.end_date.lower(), "present")
        self.assertEqual(len(role.bullets), 2)
        self.assertIn("30%", role.bullets[0].metrics)
        self.assertEqual(
            profile.education_records[0].text,
            "BSc Statistics | Example University | 2020",
        )
        self.assertIn("SQL", profile.declared_skills)
        self.assertEqual(
            profile.section_order,
            ("summary", "skills", "experience", "education"),
        )

    def test_parses_two_line_role_header_with_month_dates(self):
        resume = """\
Jane Doe
jane@example.com

EXPERIENCE
Senior Data Analyst
Acme Ltd | Nairobi | Jan 2022 - Present
- Built weekly SQL reporting pipelines.

EDUCATION
BSc Statistics | Example University | 2021
"""
        profile = extract_resume_profile(resume)
        self.assertEqual(len(profile.roles), 1)
        role = profile.roles[0]
        self.assertEqual(role.title, "Senior Data Analyst")
        self.assertEqual(role.employer, "Acme Ltd")
        self.assertEqual(role.location, "Nairobi")
        self.assertEqual(role.start_date, "Jan 2022")
        self.assertEqual(role.end_date.lower(), "present")
        self.assertEqual(
            role.bullets[0].text,
            "Built weekly SQL reporting pipelines.",
        )
        self.assertFalse(profile.parse_warnings)

    def test_parses_three_line_role_identity_without_losing_title(self):
        resume = """\
Jane Doe
jane@example.com
EXPERIENCE
Senior Data Analyst
Acme Ltd
Nairobi | Jan 2022 - Present
- Automated weekly reporting.
"""
        role = extract_resume_profile(resume).roles[0]
        self.assertEqual(role.title, "Senior Data Analyst")
        self.assertEqual(role.employer, "Acme Ltd")
        self.assertEqual(role.location, "Nairobi")
        self.assertEqual(role.date_text, "Jan 2022 - Present")

    def test_synonym_matching_recognizes_aws(self):
        report = analyze_alignment(JD, STRONG_RESUME)
        self.assertIn("aws", report.matched_terms)
        self.assertFalse(
            any("Amazon Web Services" in item for item in report.missing_preferred)
        )

    def test_required_gap_reduces_score_and_is_explained(self):
        weak_resume = """\
John Doe
john@example.com
EXPERIENCE
Assistant | Example | 2024 - Present
- Prepared weekly documents for the team.
EDUCATION
Diploma | College | 2023
"""
        strong = analyze_alignment(JD, STRONG_RESUME)
        weak = analyze_alignment(JD, weak_resume)
        self.assertGreater(strong.score, weak.score)
        self.assertTrue(weak.missing_required)
        self.assertEqual(len(weak.dimensions), 8)
        self.assertEqual(weak.score, round(sum(item.score for item in weak.dimensions)))

    def test_phrase_and_morphology_matching_preserves_multiword_capabilities(self):
        phrases = extract_ngram_phrases(
            "Managed projects using machine learning and stakeholder engagement."
        )
        terms = extract_alignment_terms(
            "Managed projects using machine learning and stakeholder engagement."
        )
        self.assertIn("manage project", phrases)
        self.assertIn("machine learning", phrases)
        self.assertIn("stakeholder manage", phrases)
        self.assertIn("machine learning", terms)

        report = analyze_alignment(
            """\
Project Manager
Requirements:
- Project management is required
- Machine learning is preferred
""",
            """\
Jane Doe
jane@example.com
EXPERIENCE
Project Lead | Acme | 2022 - Present
- Managed projects and coordinated delivery teams.
- Built machine learning models for forecasting.
""",
        )
        self.assertIn("project manage", report.matched_phrases)
        self.assertIn("machine learning", report.matched_phrases)
        self.assertFalse(report.missing_required)

    def test_demonstrated_experience_outweighs_skills_only_mention(self):
        jd = """\
Project Manager
Requirements:
- Project management is required
"""
        skills_only = """\
Jane Doe
jane@example.com
SKILLS
Project management
EXPERIENCE
Assistant | Acme | 2023 - Present
- Prepared weekly documents.
"""
        demonstrated = """\
Jane Doe
jane@example.com
EXPERIENCE
Project Lead | Acme | 2023 - Present
- Managed projects and coordinated delivery.
"""
        skills_report = analyze_alignment(jd, skills_only)
        demonstrated_report = analyze_alignment(jd, demonstrated)
        self.assertGreater(demonstrated_report.score, skills_report.score)
        self.assertIn("skills", skills_report.section_matches)
        self.assertIn("experience", demonstrated_report.section_matches)

    def test_score_is_deterministic(self):
        first = analyze_alignment(JD, STRONG_RESUME)
        second = analyze_alignment(JD, STRONG_RESUME)
        self.assertEqual(first.score, second.score)
        self.assertEqual(first.matched_terms, second.matched_terms)
        self.assertEqual(first.missing_required, second.missing_required)

    def test_legacy_score_wrapper_uses_the_canonical_engine(self):
        report = analyze_alignment(JD, STRONG_RESUME)
        score, matched, missing = compute_match_score(JD, STRONG_RESUME)
        self.assertEqual(score, report.score)
        self.assertEqual(matched, report.matched_terms)
        self.assertEqual(
            missing,
            report.missing_required + report.missing_preferred,
        )

    def test_empty_documents_return_low_confidence_report(self):
        report = analyze_alignment("", "")
        self.assertEqual(report.confidence, "Low")
        self.assertLess(report.score, 50)


if __name__ == "__main__":
    unittest.main()

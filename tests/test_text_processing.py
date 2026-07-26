import unittest

from utils.text_processing import (
    clean_resume_output,
    finalize_cover_letter,
    format_resume_for_display,
    normalize_resume_structure,
    sanitize_candidate_feedback,
)


class ResumeTextRenderingTests(unittest.TestCase):
    def test_inline_glyph_bullets_are_restored_to_separate_lines(self):
        raw = (
            "PROFESSIONAL EXPERIENCE\n"
            "Data Analyst | Acme Ltd | 2022 - Present\n"
            "• Built weekly SQL reports. • Validated source data. "
            "• Trained dashboard users."
        )
        normalized = normalize_resume_structure(raw)
        bullets = [
            line for line in normalized.splitlines() if line.startswith("- ")
        ]
        self.assertEqual(len(bullets), 3)
        self.assertEqual(bullets[0], "- Built weekly SQL reports.")
        self.assertEqual(bullets[2], "- Trained dashboard users.")

    def test_clean_resume_output_preserves_real_bullet_boundaries(self):
        cleaned = clean_resume_output(
            "## EXPERIENCE\n* Built SQL reports.\n* Improved data quality."
        )
        self.assertIn("- Built SQL reports.", cleaned)
        self.assertIn("\n- Improved data quality.", cleaned)

    def test_browser_preview_uses_semantic_list_items_and_escapes_source(self):
        source = (
            "Jane Doe\n"
            "jane@example.com\n\n"
            "PROFESSIONAL EXPERIENCE\n"
            "Data Analyst | Acme Ltd | 2022 - Present\n"
            "• Built SQL reports. • Validated <source> data.\n\n"
            "EDUCATION\n"
            "BSc Statistics | Example University | 2021"
        )
        rendered = format_resume_for_display(source)
        self.assertIn('<article class="ats-resume-preview">', rendered)
        self.assertEqual(rendered.count("<li>"), 2)
        self.assertEqual(rendered.count("</li>"), 2)
        self.assertIn("&lt;source&gt;", rendered)
        self.assertNotIn("<source>", rendered)
        self.assertIn("<h2>PROFESSIONAL EXPERIENCE</h2>", rendered)

    def test_candidate_feedback_hides_internal_audit_ids(self):
        cleaned = sanitize_candidate_feedback(
            "Strong evidence [E003] supports R002 for ROLE001. (E004, R003)"
        )
        self.assertNotIn("E003", cleaned)
        self.assertNotIn("R002", cleaned)
        self.assertNotIn("ROLE001", cleaned)

    def test_candidate_feedback_blocks_hypothetical_candidate_claims(self):
        source = "Prepared weekly HSE reporting using controlled Excel workbooks."
        feedback = (
            "- **State compliance work** – Insert a line, e.g., "
            "\"Ensured phytosanitary compliance for every production release.\"\n"
            "- **Show speed** – Add an achievement such as \"Delivered analysis within "
            "24 hours with 100% accuracy.\""
        )

        cleaned = sanitize_candidate_feedback(feedback, source)

        self.assertNotIn("Ensured phytosanitary", cleaned)
        self.assertNotIn("24 hours", cleaned)
        self.assertNotIn("100%", cleaned)
        self.assertEqual(cleaned.count("exact verified detail"), 2)

    def test_candidate_feedback_replaces_unsupported_recruiter_rewrite(self):
        source = "Built weekly SQL reporting workflows."
        feedback = (
            '- **Current:** "Built weekly SQL reporting workflows." '
            '**Rewrite:** "Built weekly SQL reporting workflows, eliminating '
            'duplicate work and increasing adoption."'
        )

        cleaned = sanitize_candidate_feedback(feedback, source)

        self.assertNotIn("eliminating duplicate work", cleaned)
        self.assertIn("retain the source wording", cleaned)

    def test_cover_letter_finalizer_removes_ids_extrapolation_and_truncation(self):
        source = (
            "Amina Kamau completed Occupational Health and Safety Awareness training. "
            "Facilitated dashboard training for supervisors."
        )
        draft = (
            "Dear Hiring Committee,\n\n"
            "I completed Occupational Health and Safety Awareness training 【E023】, "
            "which equips me to uphold HSE protocols.\n\n"
            "My membership and language skills,"
        )

        cleaned = finalize_cover_letter(draft, source, "Amina Kamau")

        self.assertNotIn("E023", cleaned)
        self.assertNotIn("uphold HSE", cleaned)
        self.assertNotIn("language skills,", cleaned)
        self.assertTrue(cleaned.endswith("Sincerely,\nAmina Kamau"))


if __name__ == "__main__":
    unittest.main()

import unittest

from utils.text_processing import (
    clean_resume_output,
    format_resume_for_display,
    normalize_resume_structure,
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


if __name__ == "__main__":
    unittest.main()

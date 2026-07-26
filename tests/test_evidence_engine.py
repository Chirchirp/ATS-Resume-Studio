import unittest

from utils.evidence_engine import (
    allocate_role_bullet_targets,
    achievement_grounding_context,
    build_evidence_ledger,
    build_evidence_matrix,
    build_safe_evidence_resume,
    compact_grounding_context,
    compact_optional_draft,
    compact_requirement_context,
    generate_clarification_questions,
    repair_grounded_resume_draft,
    strip_generation_annotations,
    validate_achievement_claims,
    validate_generated_claims,
    validate_grounded_resume_draft,
)


JD = """\
Data Engineer
Requirements:
- Python and SQL are required
- AWS experience is required
- Terraform is preferred
Responsibilities:
- Build reliable data pipelines
"""

RESUME = """\
Jane Doe
jane@example.com

SKILLS
Python, SQL

EXPERIENCE
Data Analyst | Acme Ltd | 2022 - Present
- Built Python and SQL reporting pipelines used by 12 analysts.
- Reduced weekly preparation time by 30%.

EDUCATION
BSc Statistics | Example University | 2021
"""


class EvidenceEngineTests(unittest.TestCase):
    def test_ledger_has_stable_ids_and_role_provenance(self):
        first = build_evidence_ledger(RESUME)
        second = build_evidence_ledger(RESUME)
        self.assertEqual(first.source_hash, second.source_hash)
        self.assertEqual(
            [item.id for item in first.items],
            [item.id for item in second.items],
        )
        experience = [item for item in first.items if item.section == "experience"]
        self.assertTrue(experience)
        self.assertTrue(all("Acme" in item.role for item in experience))

    def test_requirement_matrix_distinguishes_evidence_strength(self):
        ledger = build_evidence_ledger(RESUME)
        matrix = build_evidence_matrix(JD, ledger)
        aws = next(row for row in matrix.rows if "AWS" in row.requirement)
        terraform = next(row for row in matrix.rows if "Terraform" in row.requirement)
        self.assertEqual(aws.status, "missing")
        self.assertEqual(terraform.status, "missing")
        python = next(row for row in matrix.rows if "Python" in row.requirement)
        self.assertEqual(python.status, "direct")
        self.assertTrue(python.evidence_ids)
        self.assertEqual(
            ledger.by_id()[python.evidence_ids[0]].section,
            "experience",
        )

    def test_clarification_answer_becomes_confirmed_evidence(self):
        base = build_evidence_ledger(RESUME)
        matrix = build_evidence_matrix(JD, base)
        questions = generate_clarification_questions(matrix, base)
        aws_question = next(q for q in questions if "AWS" in q.prompt)
        answers = {
            aws_question.id: (
                "At Acme Ltd I deployed two Python data pipelines to AWS Lambda "
                "and monitored them in CloudWatch."
            )
        }
        updated = build_evidence_ledger(RESUME, answers)
        self.assertTrue(
            any(
                item.verification == "user_confirmed" and "AWS Lambda" in item.text
                for item in updated.items
            )
        )
        updated_matrix = build_evidence_matrix(JD, updated)
        updated_aws = next(row for row in updated_matrix.rows if "AWS" in row.requirement)
        self.assertNotEqual(updated_aws.status, "missing")

    def test_truth_audit_evidence_can_be_attached_to_exact_source_role(self):
        updated = build_evidence_ledger(
            RESUME,
            {
                "AUDIT-ROLE001-C001-unsupported_metric": (
                    "At Acme Ltd, I reduced monthly reconciliation time by 15% "
                    "using the existing Python and SQL reporting workflow."
                )
            },
        )
        confirmed = next(
            item
            for item in updated.items
            if item.verification == "user_confirmed"
        )
        self.assertEqual(confirmed.role_id, "ROLE001")
        self.assertEqual(
            confirmed.role,
            "Data Analyst | Acme Ltd | 2022 - Present",
        )
        self.assertEqual(confirmed.section, "experience")
        matrix = build_evidence_matrix(JD, updated)
        plans = allocate_role_bullet_targets(
            updated,
            matrix,
            preferred_per_role=3,
        )
        self.assertGreaterEqual(plans[0].available, 3)

    def test_confirmed_metric_can_pass_after_traceable_repair(self):
        ledger = build_evidence_ledger(
            RESUME,
            {
                "AUDIT-ROLE001-C001-unsupported_metric": (
                    "At Acme Ltd, I reduced monthly reconciliation time by 15% "
                    "using Python and SQL."
                )
            },
        )
        item = next(
            item for item in ledger.items if item.verification == "user_confirmed"
        )
        draft = (
            "PROFESSIONAL EXPERIENCE\n"
            "Data Analyst | Acme Ltd | 2022 - Present\n"
            "- Reduced monthly reconciliation time by 15% using Python and SQL.\n"
            f'  Evidence: {item.id} — "{item.text}"\n'
            "  JD Match: none — retained candidate value"
        )
        matrix = build_evidence_matrix(JD, ledger)
        plans = allocate_role_bullet_targets(ledger, matrix, preferred_per_role=3)
        repaired = repair_grounded_resume_draft(draft, ledger, JD, plans)
        report = validate_grounded_resume_draft(repaired, ledger, JD)
        self.assertTrue(report.is_download_safe, report.issues)
        self.assertIn("15%", strip_generation_annotations(repaired))

    def test_compact_context_contains_traceable_ids(self):
        ledger = build_evidence_ledger(RESUME)
        matrix = build_evidence_matrix(JD, ledger)
        context = compact_grounding_context(ledger, matrix, max_chars=2000)
        self.assertIn("[E", context)
        self.assertIn("[R", context)
        self.assertIn("only allowed factual source", context)
        self.assertIn("STRUCTURED CANDIDATE PROFILE", context)
        self.assertIn("[ROLE001]", context)
        self.assertIn("title=Data Analyst", context)
        self.assertIn("employer=Acme Ltd", context)
        self.assertIn("type=bullet", context)

    def test_compact_context_is_strictly_bounded_and_prioritizes_clarifications(self):
        answers = {
            "Q-R001": (
                "In the Reporting Analyst role, I personally validated SQL extracts "
                "before management reporting. " * 300
            )
        }
        ledger = build_evidence_ledger(RESUME, answers)
        matrix = build_evidence_matrix(JD, ledger)
        context = compact_grounding_context(
            ledger,
            matrix,
            max_chars=4_000,
            max_item_chars=420,
        )
        self.assertLessEqual(len(context), 4_000)
        self.assertIn("USER-CONFIRMED CLARIFICATIONS", context)
        self.assertIn("verification=user_confirmed", context)
        self.assertIn("REQUIREMENT COVERAGE", context)

    def test_requirement_and_previous_draft_contexts_are_bounded(self):
        ledger = build_evidence_ledger(RESUME)
        matrix = build_evidence_matrix(JD * 30, ledger)
        job_context = compact_requirement_context(
            matrix,
            job_title="Data Analyst",
            max_chars=1_200,
        )
        previous = compact_optional_draft(
            "PROFESSIONAL EXPERIENCE\n" + ("Verified source bullet.\n" * 2_000),
            max_chars=2_000,
        )
        self.assertLessEqual(len(job_context), 1_200)
        self.assertLessEqual(len(previous), 2_000)
        self.assertIn("Target title: Data Analyst", job_context)
        self.assertIn("omitted for model capacity", previous)

    def test_achievement_context_excludes_non_experience_content(self):
        ledger = build_evidence_ledger(RESUME)
        matrix = build_evidence_matrix(JD, ledger)
        context = achievement_grounding_context(ledger, matrix)
        self.assertIn("Built Python and SQL reporting pipelines", context)
        self.assertIn("[E", context)
        self.assertNotIn("jane@example.com", context)
        self.assertNotIn("BSc Statistics", context)

    def test_achievement_context_rejects_skills_only_resume(self):
        ledger = build_evidence_ledger(
            "Jane Doe\njane@example.com\nSKILLS\nPython, SQL, AWS"
        )
        matrix = build_evidence_matrix(JD, ledger)
        self.assertEqual(achievement_grounding_context(ledger, matrix), "")

    def test_truth_audit_flags_unsupported_metric_and_skill(self):
        ledger = build_evidence_ledger(RESUME)
        generated = (
            "- Built AWS data pipelines that saved $2 million annually.\n"
            "- Reduced weekly preparation time by 30%."
        )
        report = validate_generated_claims(generated, ledger, JD)
        issue_types = {issue.issue_type for issue in report.issues}
        self.assertIn("unsupported_metric", issue_types)
        self.assertIn("unsupported_skill", issue_types)
        self.assertFalse(report.is_download_safe)

    def test_truth_audit_accepts_supported_numbers(self):
        ledger = build_evidence_ledger(RESUME)
        generated = "- Reduced weekly preparation time by 30%."
        report = validate_generated_claims(generated, ledger, JD)
        self.assertTrue(report.is_download_safe)
        self.assertEqual(report.supported_claims, 1)

    def test_achievement_audit_requires_valid_id_and_exact_source_quote(self):
        ledger = build_evidence_ledger(RESUME)
        item = next(
            item
            for item in ledger.items
            if "reporting pipelines used by 12 analysts" in item.text
        )
        generated = (
            "- Built Python and SQL reporting pipelines used by 12 analysts.\n"
            f'  Evidence: {item.id} — "{item.text}"\n'
            "  Status: supported"
        )
        report = validate_achievement_claims(generated, ledger, JD)
        self.assertTrue(report.is_download_safe)
        self.assertEqual(report.supported_claims, 1)

    def test_achievement_audit_blocks_uncited_or_mismatched_bullets(self):
        ledger = build_evidence_ledger(RESUME)
        item = next(item for item in ledger.items if item.section == "experience")
        uncited = validate_achievement_claims(
            "- Built weekly reporting pipelines.", ledger, JD
        )
        self.assertIn(
            "missing_evidence_citation",
            {issue.issue_type for issue in uncited.issues},
        )
        self.assertFalse(uncited.is_download_safe)

        mismatched = validate_achievement_claims(
            "- Built weekly reporting pipelines.\n"
            f'  Evidence: {item.id} — "This phrase is not in the resume"',
            ledger,
            JD,
        )
        self.assertIn(
            "source_quote_mismatch",
            {issue.issue_type for issue in mismatched.issues},
        )
        self.assertFalse(mismatched.is_download_safe)

    def test_grounded_resume_audit_accepts_cited_bullet_and_strips_annotation(self):
        ledger = build_evidence_ledger(RESUME)
        item = next(
            item
            for item in ledger.items
            if "reporting pipelines used by 12 analysts" in item.text
        )
        matrix = build_evidence_matrix(JD, ledger)
        requirement = next(
            row for row in matrix.rows if item.id in row.evidence_ids
        )
        draft = (
            "PROFESSIONAL EXPERIENCE\n"
            "Data Analyst | Acme Ltd | 2022 - Present\n"
            "- Built Python and SQL reporting pipelines used by 12 analysts.\n"
            f'  Evidence: {item.id} — "{item.text}"\n'
            f'  JD Match: {requirement.id} — "{requirement.requirement}"'
        )
        report = validate_grounded_resume_draft(draft, ledger, JD)
        self.assertTrue(report.is_download_safe)
        visible = strip_generation_annotations(draft)
        self.assertNotIn("Evidence:", visible)
        self.assertIn("12 analysts", visible)

    def test_grounded_resume_audit_checks_non_bullet_document_claims(self):
        ledger = build_evidence_ledger(RESUME)
        item = next(
            item
            for item in ledger.items
            if "reporting pipelines used by 12 analysts" in item.text
        )
        draft = (
            "PROFESSIONAL SUMMARY\n"
            "Data analyst who delivered $2 million in annual savings.\n\n"
            "PROFESSIONAL EXPERIENCE\n"
            "- Built Python and SQL reporting pipelines used by 12 analysts.\n"
            f'  Evidence: {item.id} — "{item.text}"'
        )
        report = validate_grounded_resume_draft(draft, ledger, JD)
        self.assertIn(
            "document_unsupported_metric",
            {issue.issue_type for issue in report.issues},
        )
        self.assertFalse(report.is_download_safe)

    def test_grounded_resume_audit_blocks_false_jd_mapping(self):
        ledger = build_evidence_ledger(RESUME)
        matrix = build_evidence_matrix(JD, ledger)
        item = next(
            item
            for item in ledger.items
            if "reporting pipelines used by 12 analysts" in item.text
        )
        unrelated = next(
            row for row in matrix.rows if item.id not in row.evidence_ids
        )
        draft = (
            "PROFESSIONAL EXPERIENCE\n"
            "Data Analyst | Acme Ltd | 2022 - Present\n"
            "- Built Python and SQL reporting pipelines used by 12 analysts.\n"
            f'  Evidence: {item.id} — "{item.text}"\n'
            f'  JD Match: {unrelated.id} — "{unrelated.requirement}"'
        )
        report = validate_grounded_resume_draft(draft, ledger, JD)
        self.assertIn(
            "unsupported_jd_mapping",
            {issue.issue_type for issue in report.issues},
        )
        self.assertFalse(report.is_download_safe)

    def test_grounded_resume_audit_blocks_invented_role_and_education(self):
        ledger = build_evidence_ledger(RESUME)
        item = next(
            item
            for item in ledger.items
            if "reporting pipelines used by 12 analysts" in item.text
        )
        draft = (
            "PROFESSIONAL EXPERIENCE\n"
            "Senior Data Scientist | Fictional Corp | 2020 - Present\n"
            "- Built Python and SQL reporting pipelines used by 12 analysts.\n"
            f'  Evidence: {item.id} — "{item.text}"\n\n'
            "EDUCATION\n"
            "MSc Data Science | Fictional University | 2022"
        )
        report = validate_grounded_resume_draft(draft, ledger, JD)
        issue_types = {issue.issue_type for issue in report.issues}
        self.assertIn("unsupported_role_header", issue_types)
        self.assertIn("unsupported_education_record", issue_types)
        self.assertFalse(report.is_download_safe)

    def test_deterministic_repair_fixes_quotes_mappings_and_role_header(self):
        ledger = build_evidence_ledger(RESUME)
        matrix = build_evidence_matrix(JD, ledger)
        plans = allocate_role_bullet_targets(
            ledger, matrix, preferred_per_role=3
        )
        draft = (
            "Jane Doe\njane@example.com\n\n"
            "PROFESSIONAL EXPERIENCE\n"
            "Senior Data Analyst | Fictional Label | 2022 - Present\n"
            "- Built Python and SQL reporting pipelines used by 12 analysts.\n"
            "  Evidence: E999\n"
            '  JD Match: R002 — "wrong requirement wording"\n'
            "- Reduced weekly preparation time by 30%.\n"
        )
        repaired = repair_grounded_resume_draft(draft, ledger, JD, plans)
        report = validate_grounded_resume_draft(repaired, ledger, JD)
        self.assertTrue(report.is_download_safe, report.issues)
        self.assertIn("Data Analyst | Acme Ltd | 2022 - Present", repaired)
        self.assertNotIn("Fictional Label", repaired)
        self.assertIn('Evidence: E003 — "Built Python and SQL', repaired)
        self.assertIn('JD Match: R001 — "Python and SQL are required"', repaired)
        self.assertIn("JD Match: none — retained candidate value", repaired)

    def test_role_plan_gives_every_role_a_fair_baseline(self):
        multi_role_resume = RESUME.replace(
            "\nEDUCATION",
            "\nReporting Analyst | Beta Ltd | 2020 - 2022\n"
            "- Prepared monthly Excel reports.\n"
            "- Validated operational datasets.\n"
            "- Documented reporting definitions.\n\nEDUCATION",
        )
        ledger = build_evidence_ledger(multi_role_resume)
        matrix = build_evidence_matrix(JD, ledger)
        plans = allocate_role_bullet_targets(
            ledger, matrix, preferred_per_role=2
        )
        self.assertEqual(len(plans), 2)
        self.assertTrue(all(plan.target >= 1 for plan in plans))
        self.assertLessEqual(max(plan.target for plan in plans), 2)
        repaired = repair_grounded_resume_draft(
            (
                "PROFESSIONAL EXPERIENCE\n"
                "Data Analyst | Acme Ltd | 2022 - Present\n"
                "- Built Python and SQL reporting pipelines used by 12 analysts.\n"
                "Reporting Analyst | Beta Ltd | 2020 - 2022\n"
                "- Prepared monthly Excel reports.\n"
            ),
            ledger,
            JD,
            plans,
        )
        visible = strip_generation_annotations(repaired)
        for plan in plans:
            self.assertIn(plan.role_header, visible)

    def test_safe_recovery_is_downloadable_and_source_only(self):
        ledger = build_evidence_ledger(RESUME)
        matrix = build_evidence_matrix(JD, ledger)
        plans = allocate_role_bullet_targets(ledger, matrix)
        safe = build_safe_evidence_resume(ledger, JD, plans)
        report = validate_grounded_resume_draft(safe, ledger, JD)
        self.assertTrue(report.is_download_safe, report.issues)
        self.assertIn("Data Analyst | Acme Ltd | 2022 - Present", safe)
        self.assertNotIn("AWS", strip_generation_annotations(safe))


if __name__ == "__main__":
    unittest.main()

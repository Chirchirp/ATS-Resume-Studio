import re
import unittest

from utils.evidence_engine import (
    allocate_role_bullet_targets,
    achievement_grounding_context,
    build_evidence_ledger,
    build_evidence_matrix,
    build_safe_evidence_resume,
    compact_grounding_context,
    compact_optional_draft,
    compact_prompt_block,
    compact_requirement_context,
    enhance_resume_core_sections,
    generate_clarification_questions,
    repair_grounded_resume_draft,
    role_bullet_plan_context,
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
    def test_semantic_requirement_coverage_uses_demonstrated_concepts(self):
        resume = """Amina Kamau
PROFESSIONAL EXPERIENCE
Senior Data Analyst | Greenfields Produce | 2021 - Present
- Built SQL and Power BI reporting workflows for weekly management reviews.
- Partnered with external research teams to document source-to-report data flows.
- Gathered requirements from business users and translated them into report specifications.
- Facilitated dashboard training for supervisors and documented refresh procedures.
Data Analyst | HarvestLink | 2017 - 2020
- Maintained Smartsheet trackers for process improvement initiatives.
"""
        jd = """Use SQL, Excel, Smartsheet and data visualisation tools.
Analyse production data flows and work with external R&D partners.
Collaborate with stakeholders to gather requirements and translate business needs.
Train end-users on dashboards and analytical outputs."""
        ledger = build_evidence_ledger(resume)
        matrix = build_evidence_matrix(jd, ledger)

        statuses = [row.status for row in matrix.rows]
        self.assertGreaterEqual(
            sum(status in {"direct", "equivalent"} for status in statuses),
            3,
        )
        self.assertNotIn("missing", statuses)

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

    def test_compact_context_reserves_qualifications_before_role_detail(self):
        resume = RESUME + (
            "\nCERTIFICATIONS\n"
            "Microsoft Certified: Power BI Data Analyst Associate | 2024\n"
        )
        ledger = build_evidence_ledger(resume)
        matrix = build_evidence_matrix(JD * 20, ledger)
        context = compact_grounding_context(
            ledger,
            matrix,
            max_chars=5_000,
            max_item_chars=220,
        )
        self.assertLessEqual(len(context), 5_000)
        self.assertIn("EDUCATION — COPY EVERY RECORD EXACTLY", context)
        self.assertIn("BSc Statistics | Example University | 2021", context)
        self.assertIn("CERTIFICATIONS — COPY EVERY RECORD EXACTLY", context)
        self.assertIn(
            "Microsoft Certified: Power BI Data Analyst Associate | 2024",
            context,
        )
        self.assertIn("ROLE INDEX", context)

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
        bounded_strategy = compact_prompt_block(
            "Positioning guidance. " * 500,
            max_chars=900,
            omission_message="Strategy shortened.",
        )
        self.assertLessEqual(len(bounded_strategy), 900)
        self.assertIn("Strategy shortened", bounded_strategy)

    def test_role_plan_prompt_is_bounded(self):
        multi_role_resume = "\n".join(
            [
                "Jane Doe",
                "EXPERIENCE",
                *[
                    (
                        f"Data Analyst {index} | Employer {index} | 202{index} - Present\n"
                        f"- Prepared verified SQL report {index}."
                    )
                    for index in range(5)
                ],
            ]
        )
        ledger = build_evidence_ledger(multi_role_resume)
        matrix = build_evidence_matrix(JD, ledger)
        plans = allocate_role_bullet_targets(ledger, matrix, preferred_per_role=3)
        context = role_bullet_plan_context(plans, max_chars=350)
        self.assertLessEqual(len(context), 350)
        self.assertIn("ROLE001", context)

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

    def test_role_plan_prefers_real_bullets_over_role_detail_lines(self):
        resume = (
            "Jane Doe\njane@example.com\n\n"
            "PROFESSIONAL EXPERIENCE\n"
            "Data Analyst | Acme Ltd | 2022 - Present\n"
            "Analytics & BI: SQL, Power BI, Excel\n"
            "- Built weekly SQL reports.\n"
            "- Validated operational datasets.\n"
        )
        ledger = build_evidence_ledger(resume)
        matrix = build_evidence_matrix(JD, ledger)
        plans = allocate_role_bullet_targets(
            ledger, matrix, preferred_per_role=2
        )
        repaired = repair_grounded_resume_draft(
            "PROFESSIONAL EXPERIENCE",
            ledger,
            JD,
            plans,
        )
        visible = strip_generation_annotations(repaired)

        self.assertIn("- Built weekly SQL reports.", visible)
        self.assertIn("- Validated operational datasets.", visible)
        self.assertNotIn("- Analytics & BI:", visible)

    def test_safe_recovery_is_downloadable_and_source_only(self):
        ledger = build_evidence_ledger(RESUME)
        matrix = build_evidence_matrix(JD, ledger)
        plans = allocate_role_bullet_targets(ledger, matrix)
        safe = build_safe_evidence_resume(ledger, JD, plans)
        report = validate_grounded_resume_draft(safe, ledger, JD)
        self.assertTrue(report.is_download_safe, report.issues)
        self.assertIn("Data Analyst | Acme Ltd | 2022 - Present", safe)
        self.assertNotIn("AWS", strip_generation_annotations(safe))

    def test_visible_resume_strips_inline_internal_ids(self):
        visible = strip_generation_annotations(
            "- Built weekly SQL reports. (E003)\n"
            '  Evidence: E003 — "Built weekly SQL reports."\n'
            '  JD Match: R001 — "SQL required"'
        )

        self.assertNotIn("E003", visible)
        self.assertNotIn("R001", visible)
        self.assertEqual(visible, "- Built weekly SQL reports.")

    def test_premium_rebuilds_identity_and_generic_summary_from_source(self):
        ledger = build_evidence_ledger(RESUME)
        premium = enhance_resume_core_sections(
            "Jane Doe\n"
            "- +1 555 999 9999\n\n"
            "PROFESSIONAL SUMMARY\n"
            "Expert in analytics with proven ability to create actionable insights.\n\n"
            "PROFESSIONAL EXPERIENCE\n"
            "Data Analyst | Acme Ltd | 2022 - Present\n"
            "- +1 555 999 9999\n",
            ledger,
            target_pages=3,
        )
        matrix = build_evidence_matrix(JD, ledger)
        plans = allocate_role_bullet_targets(ledger, matrix)
        repaired = repair_grounded_resume_draft(
            premium,
            ledger,
            JD,
            plans,
        )
        visible = strip_generation_annotations(repaired)

        self.assertIn("jane@example.com", visible.split("PROFESSIONAL SUMMARY", 1)[0])
        self.assertNotIn("999 9999", visible)
        self.assertNotIn("Expert in analytics", visible)
        self.assertIn("Built Python and SQL reporting pipelines", visible)

    def test_premium_core_repair_restores_depth_skills_and_qualifications(self):
        resume = RESUME.replace(
            "SKILLS\nPython, SQL",
            (
                "PROFESSIONAL SUMMARY\n"
                "Data analyst focused on reliable reporting.\n\n"
                "SKILLS\nPython, SQL, Microsoft Excel, Power BI, Data Quality"
            ),
        ) + (
            "\nCERTIFICATIONS\n"
            "Microsoft Certified: Power BI Data Analyst Associate | 2024\n"
        )
        ledger = build_evidence_ledger(resume)
        matrix = build_evidence_matrix(JD, ledger)
        plans = allocate_role_bullet_targets(ledger, matrix)
        shallow = (
            "Jane Doe\njane@example.com\n\n"
            "PROFESSIONAL SUMMARY\n"
            "Data professional.\n\n"
            "CORE SKILLS\n"
            "SQL\n\n"
            "PROFESSIONAL EXPERIENCE\n"
            "Data Analyst | Acme Ltd | 2022 - Present\n"
            "- Built Python and SQL reporting pipelines used by 12 analysts.\n\n"
            "EDUCATION\n"
            "MSc Data Science | Fictional University | 2024"
        )
        repaired = repair_grounded_resume_draft(
            shallow,
            ledger,
            JD,
            plans,
        )
        premium = enhance_resume_core_sections(
            repaired,
            ledger,
            target_pages=3,
        )
        visible = strip_generation_annotations(premium)
        summary = visible.split("PROFESSIONAL SUMMARY", 1)[1].split(
            "CORE SKILLS", 1
        )[0]
        self.assertGreaterEqual(
            len(re.findall(r"(?<=[.!?])(?:\s+|$)", summary)),
            3,
        )
        self.assertIn("Tools & Technology:", visible)
        self.assertIn("Data & Analytics:", visible)
        self.assertIn("BSc Statistics | Example University | 2021", visible)
        self.assertIn(
            "Microsoft Certified: Power BI Data Analyst Associate | 2024",
            visible,
        )
        self.assertNotIn("Fictional University", visible)
        report = validate_grounded_resume_draft(premium, ledger, JD)
        self.assertTrue(report.is_download_safe, report.issues)

    def test_strict_output_removes_named_extra_sections_and_invented_education(self):
        ledger = build_evidence_ledger(RESUME)
        generated = """Jane Doe
jane@example.com

PROFESSIONAL SUMMARY
Data analyst focused on reporting.

CORE SKILLS
- Tools: Python | SQL

PROFESSIONAL EXPERIENCE
Data Analyst | Acme Ltd | 2022 - Present
- Built Python and SQL reporting pipelines used by 12 analysts.

EDUCATION
Diploma in Information Technology | Kabete National Polytechnic | 2019

PROJECTS
Automated forecasting engine

TRAINING & PROFESSIONAL DEVELOPMENT
AI Leadership Programme

CORE LEADERSHIP CAPABILITIES
Strategic leadership

SELECTED AI, AUTOMATION & ARCHITECTURE PORTFOLIO
Enterprise AI platform

LEADERSHIP & DELIVERY APPROACH
Executive stakeholder leadership

TECHNICAL ENVIRONMENT
Kubernetes | Terraform
"""
        cleaned = enhance_resume_core_sections(generated, ledger, target_pages=2)
        visible = strip_generation_annotations(cleaned)
        for forbidden in (
            "Kabete",
            "PROJECTS",
            "TRAINING & PROFESSIONAL DEVELOPMENT",
            "CORE LEADERSHIP CAPABILITIES",
            "SELECTED AI, AUTOMATION & ARCHITECTURE PORTFOLIO",
            "LEADERSHIP & DELIVERY APPROACH",
            "TECHNICAL ENVIRONMENT",
            "Kubernetes",
            "Terraform",
        ):
            self.assertNotIn(forbidden, visible)
        self.assertIn("BSc Statistics | Example University | 2021", visible)

    def test_education_is_omitted_when_candidate_source_has_none(self):
        source = """Jane Doe
jane@example.com

SKILLS
Python, SQL

EXPERIENCE
Data Analyst | Acme Ltd | 2022 - Present
- Built SQL reporting workflows.
"""
        ledger = build_evidence_ledger(source)
        generated = source + (
            "\nEDUCATION\n"
            "Diploma in Information Technology | Kabete National Polytechnic | 2019\n"
        )
        visible = strip_generation_annotations(
            enhance_resume_core_sections(generated, ledger, target_pages=1)
        )
        self.assertNotIn("EDUCATION", visible)
        self.assertNotIn("Kabete", visible)

    def test_premium_repair_keeps_only_simple_competitive_sections(self):
        resume = RESUME + (
            "\nTRAINING & PROFESSIONAL DEVELOPMENT\n"
            "Advanced Data Visualization | 2023\n\n"
            "AWARDS & HONORS\n"
            "Operations Insight Award | 2022\n\n"
            "PROFESSIONAL MEMBERSHIPS\n"
            "Data Management Association\n\n"
            "LANGUAGES\n"
            "English | Swahili\n"
            "\nPROJECTS\n"
            "Sales Reporting Redesign\n"
            "- Rebuilt source reporting workflows.\n"
            "\nCORE LEADERSHIP CAPABILITIES\n"
            "Team leadership | Executive communication\n"
        )
        ledger = build_evidence_ledger(resume)
        matrix = build_evidence_matrix(JD, ledger)
        plans = allocate_role_bullet_targets(ledger, matrix)
        safe = build_safe_evidence_resume(
            ledger,
            JD,
            plans,
            target_pages=3,
        )
        visible = strip_generation_annotations(safe)
        self.assertNotIn("TRAINING & PROFESSIONAL DEVELOPMENT", visible)
        self.assertNotIn("Advanced Data Visualization | 2023", visible)
        self.assertNotIn("AWARDS & HONORS", visible)
        self.assertNotIn("PROFESSIONAL MEMBERSHIPS", visible)
        self.assertNotIn("LANGUAGES", visible)
        self.assertNotIn("PROJECTS", visible)
        self.assertNotIn("CORE LEADERSHIP CAPABILITIES", visible)
        report = validate_grounded_resume_draft(safe, ledger, JD)
        self.assertTrue(report.is_download_safe, report.issues)

    def test_every_source_organization_is_retained_in_source_order(self):
        resume = """Jane Doe
jane@example.com

EXPERIENCE
Senior Analyst | Alpha Ltd | 2022 - Present
- Built SQL reporting workflows.
Analyst | Beta Ltd | 2019 - 2022
- Validated operational reports.
Assistant | Gamma Ltd | 2017 - 2019

EDUCATION
BSc Statistics | Example University | 2017
"""
        ledger = build_evidence_ledger(resume)
        matrix = build_evidence_matrix(JD, ledger)
        plans = allocate_role_bullet_targets(
            ledger,
            matrix,
            preferred_per_role=6,
            target_pages=1,
        )
        self.assertEqual(
            [plan.role_header for plan in plans],
            [role.header for role in ledger.profile.roles],
        )
        safe = strip_generation_annotations(
            build_safe_evidence_resume(
                ledger,
                JD,
                plans,
                target_pages=1,
            )
        )
        positions = [safe.index(role.header) for role in ledger.profile.roles]
        self.assertEqual(positions, sorted(positions))


if __name__ == "__main__":
    unittest.main()

"""
components/tab_premium.py — Premium Solutions tab: resume gen, cover letter, recruiter feedback.
"""

import re

import streamlit as st

from config.settings import get_provider_label, is_api_key_set
from prompts.templates import (
    BASE_SYSTEM_PROMPT,
    COVER_LETTER_PROMPT,
    CUSTOM_QUERY_PROMPT,
    INFER_FIELD_PROMPT,
    RESUME_WRITER_SYSTEM_PROMPT,
    build_cover_letter_refinement_prompt,
    build_grounded_resume_prompt,
    build_recruiter_prompt,
    build_resume_refinement_prompt,
    build_truth_audit_repair_prompt,
    get_recruiter_system_prompt,
)
from utils.ai_runtime import resume_output_limit, run_ai, user_safe_ai_error
from utils.ats_engine import AlignmentReport, analyze_alignment, top_requirement_text
from utils.docx_builder import make_docx_from_text, validate_docx_roundtrip
from utils.domain_profiles import (
    deterministic_field_label,
    domain_prompt_context,
    infer_domain_context,
    normalize_field_label,
)
from utils.evidence_engine import (
    ClaimValidationReport,
    allocate_role_bullet_targets,
    build_evidence_ledger,
    build_evidence_matrix,
    build_safe_evidence_resume,
    candidate_facing_grounding_context,
    compact_grounding_context,
    compact_optional_draft,
    compact_prompt_block,
    compact_requirement_context,
    enhance_resume_core_sections,
    repair_grounded_resume_draft,
    role_bullet_plan_context,
    strip_generation_annotations,
    validate_achievement_claims,
    validate_generated_claims,
    validate_grounded_resume_draft,
)
from utils.logger import log_usage
from utils.text_processing import (
    clean_resume_output,
    finalize_cover_letter,
    format_resume_for_display,
    sanitize_candidate_feedback,
    sanitize_display_text,
)
from utils.workspace_engine import build_positioning_strategies


def _display_md(text: str, **kwargs):
    st.markdown(sanitize_display_text(text), **kwargs)


def _call_ai(
    prompt: str,
    *,
    system_prompt: str = BASE_SYSTEM_PROMPT,
    temperature: float = 0.2,
    max_tokens: int | None = None,
    task: str = "query",
    show_error: bool = True,
) -> str:
    try:
        result = run_ai(
            prompt,
            system_prompt=system_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
            task=task,
        )
        if result.fallback_used:
            st.info(
                f"Primary AI route was unavailable; "
                f"{result.provider} / {result.model} completed this request."
            )
        st.session_state.pop("_last_call_ai_error", None)
        return result.text
    except Exception as exc:
        message = user_safe_ai_error(exc)
        st.session_state["_last_call_ai_error"] = {
            "message": message,
            "category": str(getattr(exc, "category", "")),
        }
        if show_error:
            st.error(f"AI request failed: {message}")
        return ""


def _validation_rank(report: ClaimValidationReport) -> tuple[int, int, int]:
    """Lower is better; deterministic safety outranks stylistic preference."""
    high = sum(issue.severity == "high" for issue in report.issues)
    medium = sum(issue.severity == "medium" for issue in report.issues)
    return high, medium, -report.supported_claims


def _is_request_size_error(error: object) -> bool:
    if not isinstance(error, dict):
        return False
    category = str(error.get("category", ""))
    message = str(error.get("message", "")).lower()
    return category == "request_too_large" or (
        category == "fallback_exhausted" and "too large" in message
    )


def _validation_findings(report: ClaimValidationReport, limit: int = 16) -> str:
    if not report.issues:
        return "No machine-detected issue. Complete the full editorial checklist."
    return "\n".join(
        f"- {issue.claim_id} | {issue.issue_type}: {issue.detail}"
        for issue in report.issues[:limit]
    )


EVIDENCE_INPUT_ISSUES = {
    "unsupported_metric",
    "unsupported_skill",
    "unsupported_credential",
    "document_unsupported_metric",
    "document_unsupported_skill",
    "document_unsupported_credential",
    "unsupported_education_record",
    "unsupported_certifications_record",
    "verification_placeholder",
}


def _truth_issue_action(issue_type: str) -> tuple[str, bool]:
    """Return plain-language repair guidance and whether candidate input can help."""
    if issue_type in {
        "missing_evidence_citation",
        "missing_evidence_id",
        "unknown_evidence_id",
        "missing_source_quote",
        "source_quote_mismatch",
    }:
        return (
            "Automatic fix: rebuild the hidden evidence ID and exact source quotation.",
            False,
        )
    if issue_type in {
        "missing_jd_mapping",
        "missing_requirement_id",
        "unknown_requirement_id",
        "unsupported_jd_mapping",
        "requirement_quote_mismatch",
    }:
        return (
            "Automatic fix: recalculate the supported JD mapping and insert the exact "
            "requirement wording, or mark the bullet as having no supported JD match.",
            False,
        )
    if issue_type == "unsupported_role_header":
        return (
            "Automatic fix: restore the exact title, employer, location, and date header "
            "from the parsed source role.",
            False,
        )
    if issue_type in EVIDENCE_INPUT_ISSUES:
        return (
            "Evidence needed: add a factual statement you can personally verify, attach "
            "it to the correct role, and confirm it. Otherwise AI will remove the claim.",
            True,
        )
    return (
        "Automatic safe fix: rewrite from supported evidence or remove the unsupported "
        "fragment if no evidence exists.",
        False,
    )


def _update_repaired_resume_output(
    rout: dict,
    *,
    annotated_resume: str,
    ledger,
    validation: ClaimValidationReport,
    role_plans,
    preferred_bullets: int,
    review_pass: str,
    issues_before: int,
) -> None:
    visible = clean_resume_output(strip_generation_annotations(annotated_resume))
    achievements = _achievement_examples_from_resume(
        annotated_resume,
        sum(plan.target for plan in role_plans) or preferred_bullets,
    )
    updated = dict(rout)
    updated.update(
        {
            "resume": visible,
            "annotated_resume": annotated_resume,
            "achievements": achievements,
            "achievement_validation": (
                validate_achievement_claims(
                    achievements,
                    ledger,
                    st.session_state.get("jd", ""),
                )
                if achievements
                else None
            ),
            "validation": validation,
            "validation_mode": "ai_assisted_truth_repair",
            "review_pass": review_pass,
            "source_hash": ledger.source_hash,
            "role_bullet_plan": role_plans,
            "truth_repair_summary": {
                "issues_before": issues_before,
                "issues_after": len(validation.issues),
                "download_safe": validation.is_download_safe,
            },
        }
    )
    st.session_state["premium_resume_output"] = updated
    st.session_state["ideal_resume"] = visible
    st.session_state["claim_validation"] = validation
    st.session_state.pop("truth_audit_resume_text", None)


def _run_ai_truth_repair(
    rout: dict,
    ledger,
    *,
    preferred_bullets: int,
    prefs: dict,
) -> bool:
    """Run AI repair, deterministic normalization, and a guaranteed safe fallback."""
    if not _api_guard(prefs):
        return False
    jd_text = st.session_state.get("jd", "")
    matrix = build_evidence_matrix(jd_text, ledger)
    role_plans = allocate_role_bullet_targets(
        ledger,
        matrix,
        preferred_per_role=preferred_bullets,
    )
    grounding = compact_grounding_context(ledger, matrix)
    current_annotated = rout.get("annotated_resume") or repair_grounded_resume_draft(
        rout.get("resume", ""),
        ledger,
        jd_text,
        role_plans,
    )
    current_validation = validate_grounded_resume_draft(
        current_annotated,
        ledger,
        jd_text,
    )
    try:
        prompt = build_truth_audit_repair_prompt(
            draft=current_annotated,
            candidate_evidence=grounding,
            deterministic_findings=_validation_findings(
                current_validation,
                limit=30,
            ),
            role_bullet_plan=role_bullet_plan_context(role_plans),
        )
    except ValueError as exc:
        st.error(str(exc))
        return False

    with st.spinner("AI is repairing unsupported claims and rebuilding evidence links…"):
        ai_draft = clean_resume_output(
            _call_ai(
                prompt,
                system_prompt=RESUME_WRITER_SYSTEM_PROMPT,
                temperature=0.0,
                task="resume",
            )
        )
    if not ai_draft:
        return False

    repaired = repair_grounded_resume_draft(
        ai_draft,
        ledger,
        jd_text,
        role_plans,
    )
    repaired = enhance_resume_core_sections(
        repaired,
        ledger,
        target_pages=rout.get("target_pages", 3),
    )
    repaired = repair_grounded_resume_draft(
        repaired,
        ledger,
        jd_text,
        role_plans,
    )
    repaired_validation = validate_grounded_resume_draft(
        repaired,
        ledger,
        jd_text,
    )
    review_pass = "ai_truth_repair"

    # AI never overrides the audit. If unsafe content remains, use the source-only
    # deterministic recovery so the user is not trapped behind an opaque block.
    if not repaired_validation.is_download_safe:
        safe_version = build_safe_evidence_resume(
            ledger,
            jd_text,
            role_plans,
            target_pages=rout.get("target_pages", 3),
        )
        safe_validation = validate_grounded_resume_draft(
            safe_version,
            ledger,
            jd_text,
        )
        if safe_validation.is_download_safe:
            repaired = safe_version
            repaired_validation = safe_validation
            review_pass = "ai_truth_repair_safe_fallback"

    _update_repaired_resume_output(
        rout,
        annotated_resume=repaired,
        ledger=ledger,
        validation=repaired_validation,
        role_plans=role_plans,
        preferred_bullets=preferred_bullets,
        review_pass=review_pass,
        issues_before=len(current_validation.issues),
    )
    log_usage(
        "repair_resume_truth_audit",
        status=f"{len(current_validation.issues)}_issues_before",
    )
    return True


def _achievement_examples_from_resume(
    annotated_resume: str, limit: int
) -> str:
    """Reuse audited resume bullets instead of spending tokens on another generation."""
    lines = annotated_resume.splitlines()
    positions = [
        index
        for index, line in enumerate(lines)
        if re.match(r"^\s*[•*\-–—]\s+\S", line)
    ]
    blocks: list[str] = []
    for item_index, position in enumerate(positions):
        end = positions[item_index + 1] if item_index + 1 < len(positions) else len(lines)
        evidence_lines = [
            line.strip()
            for line in lines[position + 1 : end]
            if line.strip().lower().startswith("evidence:")
        ]
        if not evidence_lines:
            continue
        blocks.append(
            lines[position].strip()
            + "\n  "
            + evidence_lines[0]
            + "\n  Status: supported"
        )
        if len(blocks) >= max(1, limit):
            break
    return "\n\n".join(blocks)


def _alignment_markdown(report: AlignmentReport) -> str:
    lines = [
        f"### Job Alignment Score: {report.score}%",
        f"**Confidence:** {report.confidence}",
        "",
        "| Dimension | Score | Explanation |",
        "|---|---:|---|",
    ]
    for item in report.dimensions:
        explanation = item.explanation.replace("|", "/").replace("\n", " ")
        lines.append(
            f"| {item.label} | {item.score:.1f}/{item.maximum:.0f} | {explanation} |"
        )
    lines.extend(["", "#### Required requirement gaps"])
    if report.missing_required:
        lines.extend(f"- {item}" for item in report.missing_required[:10])
    else:
        lines.append("- No required gaps were detected from the extracted text.")
    if report.missing_preferred:
        lines.extend(["", "#### Preferred requirement gaps"])
        lines.extend(f"- {item}" for item in report.missing_preferred[:8])
    if report.matched_phrases:
        lines.extend(
            [
                "",
                "#### Matched multi-word phrases",
                ", ".join(report.matched_phrases[:25]),
            ]
        )
    if report.section_matches:
        lines.extend(["", "#### Match provenance"])
        for section, terms in report.section_matches.items():
            lines.append(f"- **{section.title()}:** {', '.join(terms[:20])}")
    lines.extend([
        "",
        "> This is an explainable job-alignment estimate, not a score produced by a specific ATS vendor.",
    ])
    return "\n".join(lines)


def _recruiter_alignment_context(report: AlignmentReport, matrix) -> str:
    lines = [
        f"Authoritative Job Alignment Score: {report.score}/100",
        f"Confidence: {report.confidence}",
    ]
    lines.extend(
        f"- {dimension.label}: {dimension.score:.1f}/{dimension.maximum:.0f}"
        for dimension in report.dimensions
    )
    lines.append("Authoritative requirement statuses:")
    lines.extend(
        f"- {row.status.upper()}: {row.requirement}"
        for row in matrix.rows
    )
    return "\n".join(lines)


def _infer_field(jd_text: str, prefs: dict) -> str:
    if prefs.get("target_field", "").strip():
        return prefs["target_field"].strip()
    if prefs.get("auto_infer_field") and jd_text.strip():
        label = deterministic_field_label(jd_text)
        if not label and is_api_key_set():
            resp = _call_ai(
                INFER_FIELD_PROMPT.format(jd=jd_text),
                temperature=0.0,
                task="classification",
            )
            label = normalize_field_label(resp)
        label = label or "General"
        st.session_state["inferred_field"] = label
        return label
    return st.session_state.get("inferred_field", "General")


def _api_guard(prefs: dict) -> bool:
    if not prefs["api_ready"]:
        st.error(f"🔑 Enter your {get_provider_label()} API key in the sidebar.")
        return False
    return True


def _jd_resume_guard() -> bool:
    if not st.session_state.get("jd", "").strip() or not st.session_state.get("resume", "").strip():
        st.error("📋 Provide both JD and resume in the **Analyze** tab first.")
        return False
    return True


# ──────────────────────────────────────────────────────────────────────────────
# Main render
# ──────────────────────────────────────────────────────────────────────────────

def render_tab_premium(prefs: dict):
    """Render all premium solution sections."""

    st.markdown(
        '<p class="section-label">💎 Premium Solutions</p>',
        unsafe_allow_html=True,
    )
    st.caption("All actions use the JD & resume you provided in the Analyze tab.")

    # ── Section 1: Tools ──────────────────────────────────────────────────────
    with st.expander("🛠️ 1 · Tools & Quick Actions", expanded=True):
        _render_tools(prefs)

    # ── Section 2: Resume Generation ─────────────────────────────────────────
    with st.expander("📄 2 · Resume Generation", expanded=False):
        _render_resume_gen(prefs)

    # ── Section 3: Cover Letter ───────────────────────────────────────────────
    with st.expander("✉️ 3 · Cover Letter Generation", expanded=False):
        _render_cover_letter(prefs)

    # ── Section 4: Custom Query ───────────────────────────────────────────────
    with st.expander("💬 4 · Custom Query", expanded=False):
        _render_custom_query(prefs)


# ──────────────────────────────────────────────────────────────────────────────
# Section renderers
# ──────────────────────────────────────────────────────────────────────────────

def _render_tools(prefs: dict):
    col1, col2, col3 = st.columns([1, 1, 1], gap="medium")

    with col1:
        st.markdown("**📊 Job Alignment Score**")
        st.caption("Transparent scoring from extracted requirements and resume evidence.")
        if st.button("Run ATS Match", key="btn_pct_match", width="stretch"):
            if _jd_resume_guard():
                with st.spinner("Calculating evidence-backed alignment…"):
                    result = analyze_alignment(
                        st.session_state["jd"], st.session_state["resume"]
                    )
                st.session_state.setdefault("premium_tools_output", {})["percentage_match"] = result
                log_usage("percentage_match", fields=prefs.get("target_field", ""))

    with col2:
        st.markdown("**🎯 Recruiter Feedback**")
        st.caption("Brutally honest mock recruiter review with a scored rubric.")
        if st.button("Get Recruiter Feedback", key="btn_recruiter", width="stretch"):
            if _api_guard(prefs) and _jd_resume_guard():
                fields_ctx = _infer_field(st.session_state.get("jd", ""), prefs)
                ledger = build_evidence_ledger(
                    st.session_state["resume"],
                    st.session_state.get("clarification_answers", {}),
                )
                matrix = build_evidence_matrix(st.session_state["jd"], ledger)
                alignment = analyze_alignment(
                    st.session_state["jd"], st.session_state["resume"]
                )
                grounding = candidate_facing_grounding_context(
                    ledger,
                    matrix,
                    alignment_score=alignment.score,
                    confidence=alignment.confidence,
                )
                with st.spinner("Sarah Chen is reviewing your resume… (30-60 s)"):
                    result = sanitize_candidate_feedback(
                        _call_ai(
                            build_recruiter_prompt(
                                fields=fields_ctx,
                                jd=st.session_state["jd"],
                                resume=grounding,
                                alignment_context=_recruiter_alignment_context(
                                    alignment, matrix
                                ),
                            ),
                            system_prompt=get_recruiter_system_prompt()
                            + " "
                            + BASE_SYSTEM_PROMPT,
                            temperature=0.1,
                            task="recruiter",
                        ),
                        st.session_state["resume"],
                    )
                if result:
                    st.session_state.setdefault("premium_tools_output", {})["recruiter_feedback"] = result
                    log_usage("recruiter_feedback", fields=fields_ctx)

    with col3:
        st.markdown("**❓ Quick Tool Question**")
        st.caption("Ask anything about the JD vs resume.")
        quick_q = st.text_input("e.g. 'What are my top 3 gaps?'", key="tools_quick_q")
        if st.button("Ask", key="btn_tool_q", width="stretch"):
            if _api_guard(prefs) and _jd_resume_guard():
                if not quick_q.strip():
                    st.error("Enter a question first.")
                else:
                    ledger = build_evidence_ledger(
                        st.session_state["resume"],
                        st.session_state.get("clarification_answers", {}),
                    )
                    matrix = build_evidence_matrix(st.session_state["jd"], ledger)
                    with st.spinner("Thinking…"):
                        result = _call_ai(
                            CUSTOM_QUERY_PROMPT.format(
                                custom_query=quick_q,
                                jd=st.session_state["jd"],
                                text=compact_grounding_context(ledger, matrix),
                            ),
                            task="query",
                        )
                    if result:
                        st.session_state.setdefault("premium_tools_output", {})["tool_query"] = result
                        log_usage("tool_query")

    # Display tool results
    tool_out = st.session_state.get("premium_tools_output", {})
    if tool_out:
        st.divider()
        if "percentage_match" in tool_out:
            st.markdown("##### 📊 Alignment Result")
            result = tool_out["percentage_match"]
            if isinstance(result, AlignmentReport):
                _display_md(_alignment_markdown(result))
            else:
                _display_md(str(result))
            st.divider()
        if "recruiter_feedback" in tool_out:
            st.markdown("##### 🎯 Recruiter Feedback")
            _display_md(tool_out["recruiter_feedback"])
            feedback_bytes = make_docx_from_text(
                tool_out["recruiter_feedback"],
                name="Senior Recruiter Review",
            )
            export_a, export_b = st.columns(2)
            with export_a:
                st.download_button(
                    "📥 Download Recruiter Review DOCX",
                    data=feedback_bytes,
                    file_name="Senior_Recruiter_Review.docx",
                    mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    width="stretch",
                    key="download_recruiter_docx",
                )
            with export_b:
                st.download_button(
                    "📥 Download Recruiter Review Markdown",
                    data=tool_out["recruiter_feedback"].encode("utf-8"),
                    file_name="senior_recruiter_review.md",
                    mime="text/markdown",
                    width="stretch",
                    key="download_recruiter_md",
                )
            st.divider()
        if "tool_query" in tool_out:
            st.markdown("##### 💬 Query Answer")
            _display_md(tool_out["tool_query"])


def _render_resume_gen(prefs: dict):
    jd_ok = bool(st.session_state.get("jd", "").strip())
    res_ok = bool(st.session_state.get("resume", "").strip())

    if not jd_ok:
        st.info("Paste the Job Description in the Analyze tab first.")
    if res_ok:
        st.success("✅ Will use your resume as foundation.")
    else:
        st.warning(
            "No resume evidence found — AI resume generation is disabled. "
            "Add your resume in Analyze first."
        )

    with st.form("resume_gen_form"):
        col_a, col_b = st.columns(2)
        with col_a:
            job_title_input = st.text_input("Target Job Title (optional)", key="rg_job_title")
        with col_b:
            preferred_bullets = st.select_slider(
                "Bullet density (auto-balanced per role)",
                [2, 3, 4, 5, 6],
                value=max(2, min(6, prefs["achievements_count"])),
                help=(
                    "Sets the average target. Every parsed role receives a fair baseline; "
                    "extra bullets follow available evidence and job relevance."
                ),
            )
        target_pages = st.select_slider(
            "Target resume length",
            options=[1, 2, 3, 4],
            value=3,
            format_func=lambda pages: (
                "1 page"
                if pages == 1
                else f"{pages} pages"
                if pages < 4
                else "4 pages maximum"
            ),
            help=(
                "The generator respects this ceiling without padding. Actual pagination "
                "depends on verified evidence and the final Word layout."
            ),
        )
        available_strategies = st.session_state.get("positioning_strategies", [])
        strategy_names = [strategy.name for strategy in available_strategies]
        selected_strategy_name = st.selectbox(
            "Positioning strategy",
            strategy_names or ["Direct evidence fit"],
            key="resume_positioning_strategy",
            help="Configure and compare strategies in the Application Workspace.",
        )
        include_phone = st.checkbox("Keep contact placeholders if missing", value=True)
        verified_two_pass = st.checkbox(
            "Verified two-pass generation",
            value=True,
            help=(
                "Recommended: drafts once, then runs a lower-temperature evidence, "
                "JD-mapping, and specificity review. Disable only to conserve API tokens."
            ),
        )
        submitted = st.form_submit_button("✨ Generate ATS-Optimized Resume", type="primary", width="stretch")

    existing_rout = st.session_state.get("premium_resume_output", {})
    regenerate_requested = False
    safe_repair_requested = False
    if existing_rout:
        st.caption(
            "Improve the current version or recover a download-safe source-only version "
            "without decoding audit IDs."
        )
        regen_col, repair_col = st.columns(2)
        with regen_col:
            regenerate_requested = st.button(
                "🔁 Regenerate & improve",
                key="regenerate_resume_improve",
                type="primary",
                width="stretch",
                help=(
                    "Uses the current version as editorial context, then re-runs grounded "
                    "generation, deterministic citation repair, and truth audit."
                ),
            )
        with repair_col:
            safe_repair_requested = st.button(
                "🛠️ Create safe evidence-only version",
                key="safe_resume_repair",
                width="stretch",
                help=(
                    "Restores exact source roles, evidence, JD mappings, dates, and records. "
                    "Use this when you want a source-only version with no unresolved claims."
                ),
            )

    if safe_repair_requested:
        current_ledger = build_evidence_ledger(
            st.session_state.get("resume", ""),
            st.session_state.get("clarification_answers", {}),
        )
        current_matrix = build_evidence_matrix(
            st.session_state.get("jd", ""), current_ledger
        )
        role_plans = allocate_role_bullet_targets(
            current_ledger,
            current_matrix,
            preferred_per_role=preferred_bullets,
        )
        safe_annotated = build_safe_evidence_resume(
            current_ledger,
            st.session_state.get("jd", ""),
            role_plans,
            target_pages=existing_rout.get("target_pages", 3),
        )
        safe_validation = validate_grounded_resume_draft(
            safe_annotated,
            current_ledger,
            st.session_state.get("jd", ""),
        )
        safe_visible = strip_generation_annotations(safe_annotated)
        safe_achievements = _achievement_examples_from_resume(
            safe_annotated,
            sum(plan.target for plan in role_plans) or preferred_bullets,
        )
        updated = dict(existing_rout)
        updated.update(
            {
                "resume": safe_visible,
                "annotated_resume": safe_annotated,
                "achievements": safe_achievements,
                "achievement_validation": (
                    validate_achievement_claims(
                        safe_achievements,
                        current_ledger,
                        st.session_state.get("jd", ""),
                    )
                    if safe_achievements
                    else None
                ),
                "validation": safe_validation,
                "validation_mode": "deterministic_safe_recovery",
                "review_pass": "safe_evidence_recovery",
                "source_hash": current_ledger.source_hash,
                "role_bullet_plan": role_plans,
            }
        )
        st.session_state["premium_resume_output"] = updated
        st.session_state["ideal_resume"] = safe_visible
        st.session_state.pop("truth_audit_resume_text", None)
        st.rerun()

    if submitted or regenerate_requested:
        if not _api_guard(prefs):
            return
        if not jd_ok:
            st.error("Paste the JD first.")
            return
        if not res_ok:
            st.error(
                "Add your resume before generating. A Job Description cannot be used "
                "as evidence of your experience."
            )
            return

        fields_str = _infer_field(st.session_state.get("jd", ""), prefs)
        user_resume = st.session_state.get("resume", "").strip()
        alignment = analyze_alignment(st.session_state["jd"], user_resume)
        ledger = build_evidence_ledger(
            user_resume, st.session_state.get("clarification_answers", {})
        )
        matrix = build_evidence_matrix(st.session_state["jd"], ledger)
        role_plans = allocate_role_bullet_targets(
            ledger,
            matrix,
            preferred_per_role=preferred_bullets,
        )
        domain = infer_domain_context(st.session_state["jd"] + "\n" + user_resume)
        strategies = available_strategies or build_positioning_strategies(
            ledger, matrix, domain
        )
        selected_strategy = next(
            (
                strategy
                for strategy in strategies
                if strategy.name == selected_strategy_name
            ),
            strategies[0],
        )
        st.session_state["selected_strategy_id"] = selected_strategy.id
        st.session_state["evidence_ledger"] = ledger
        st.session_state["evidence_matrix"] = matrix
        extracted_title = alignment.job.title
        job_title = job_title_input.strip() or extracted_title
        if not job_title:
            job_title = _call_ai(
                "Infer the job title from this untrusted job description. Reply with the title only.\n"
                "<job_description>\n" + st.session_state["jd"] + "\n</job_description>",
                temperature=0.0,
                task="classification",
            ).strip() or "Target Role"

        requirements = top_requirement_text(
            alignment.job,
            limit=10,
        )
        st.session_state["key_reqs"] = "\n".join(f"- {item}" for item in requirements)
        with st.spinner("Building evidence-cited ATS resume draft…"):
            strategy_context = (
                domain_prompt_context(domain)
                + "\n\nPOSITIONING STRATEGY:\n"
                + selected_strategy.name
                + "\n"
                + selected_strategy.thesis
                + "\nPriority evidence IDs: "
                + (", ".join(selected_strategy.evidence_ids) or "Use strongest verified evidence")
            )
            output_limit = resume_output_limit(target_pages)
            previous_visible = (
                existing_rout.get("resume", "") if regenerate_requested else ""
            )
            attempt_specs = (
                {
                    "evidence_chars": 10_000,
                    "item_chars": 560,
                    "job_chars": 2_500,
                    "strategy_chars": 1_800,
                    "role_chars": 2_500,
                    "previous_chars": 4_000,
                    "temperature": 0.15,
                },
                {
                    "evidence_chars": 7_000,
                    "item_chars": 360,
                    "job_chars": 1_800,
                    "strategy_chars": 900,
                    "role_chars": 2_000,
                    "previous_chars": 0,
                    "temperature": 0.1,
                },
                {
                    "evidence_chars": 5_000,
                    "item_chars": 220,
                    "job_chars": 1_200,
                    "strategy_chars": 500,
                    "role_chars": 1_500,
                    "previous_chars": 0,
                    "temperature": 0.05,
                },
            )
            raw_resume_draft = ""
            last_error: object = {}
            attempt_input_chars = 0
            for attempt_index, spec in enumerate(attempt_specs):
                if attempt_index:
                    st.info(
                        f"Groq payload recovery {attempt_index}/2: retaining the "
                        "highest-priority verified evidence in a smaller request."
                    )
                attempt_grounding = compact_grounding_context(
                    ledger,
                    matrix,
                    max_chars=spec["evidence_chars"],
                    max_item_chars=spec["item_chars"],
                )
                attempt_job = compact_requirement_context(
                    matrix,
                    job_title=job_title,
                    max_chars=spec["job_chars"],
                )
                attempt_strategy = compact_prompt_block(
                    strategy_context,
                    max_chars=spec["strategy_chars"],
                    omission_message="Additional positioning detail omitted.",
                )
                attempt_role_plan = role_bullet_plan_context(
                    role_plans,
                    max_chars=spec["role_chars"],
                )
                attempt_previous = (
                    compact_optional_draft(
                        previous_visible,
                        max_chars=spec["previous_chars"],
                    )
                    if previous_visible and spec["previous_chars"]
                    else ""
                )
                try:
                    attempt_prompt = build_grounded_resume_prompt(
                        fields=fields_str,
                        job_description=attempt_job,
                        candidate_evidence=attempt_grounding,
                        strategy_context=attempt_strategy,
                        role_bullet_plan=attempt_role_plan,
                        previous_draft=attempt_previous,
                        target_pages=target_pages,
                    )
                except ValueError as exc:
                    st.error(str(exc))
                    return
                attempt_input_chars = len(
                    RESUME_WRITER_SYSTEM_PROMPT + attempt_prompt
                )
                raw_resume_draft = _call_ai(
                    attempt_prompt,
                    system_prompt=RESUME_WRITER_SYSTEM_PROMPT,
                    temperature=spec["temperature"],
                    max_tokens=output_limit,
                    task="resume",
                    show_error=False,
                )
                if raw_resume_draft:
                    break
                last_error = st.session_state.get("_last_call_ai_error", {})
                if not _is_request_size_error(last_error):
                    message = (
                        last_error.get(
                            "message", "The AI request could not be completed."
                        )
                        if isinstance(last_error, dict)
                        else "The AI request could not be completed."
                    )
                    st.error(f"AI request failed: {message}")
                    break

            capacity_safe_fallback = False
            if not raw_resume_draft and _is_request_size_error(last_error):
                raw_resume_draft = build_safe_evidence_resume(
                    ledger,
                    st.session_state["jd"],
                    role_plans,
                    target_pages=target_pages,
                )
                capacity_safe_fallback = True
                st.warning(
                    "Groq rejected all three bounded payloads. The app created a "
                    "download-safe evidence-only resume instead of blocking generation. "
                    "You can regenerate its wording later without losing verified facts."
                )
            st.session_state["last_resume_request"] = {
                "target_pages": target_pages,
                "output_limit": output_limit,
                "final_input_estimate": max(1, attempt_input_chars // 4),
                "capacity_safe_fallback": capacity_safe_fallback,
            }

            resume_draft = clean_resume_output(raw_resume_draft)
        if not resume_draft:
            return
        resume_draft = repair_grounded_resume_draft(
            resume_draft,
            ledger,
            st.session_state["jd"],
            role_plans,
        )
        resume_draft = enhance_resume_core_sections(
            resume_draft,
            ledger,
            target_pages=target_pages,
        )
        resume_draft = repair_grounded_resume_draft(
            resume_draft,
            ledger,
            st.session_state["jd"],
            role_plans,
        )
        first_validation = validate_grounded_resume_draft(
            resume_draft, ledger, st.session_state["jd"]
        )
        review_pass = (
            "capacity_safe_evidence_recovery"
            if capacity_safe_fallback
            else "single_pass"
        )
        validation = first_validation
        if verified_two_pass and not capacity_safe_fallback:
            refinement_prompt = build_resume_refinement_prompt(
                draft=resume_draft,
                candidate_evidence=attempt_grounding,
                deterministic_findings=_validation_findings(first_validation),
            )
            with st.spinner("Reviewing evidence, JD mappings, and specificity…"):
                reviewed_raw = _call_ai(
                    refinement_prompt,
                    system_prompt=RESUME_WRITER_SYSTEM_PROMPT,
                    temperature=0.05,
                    max_tokens=output_limit,
                    task="resume",
                    show_error=False,
                )
                reviewed_draft = clean_resume_output(reviewed_raw)
            if not reviewed_draft:
                review_error = st.session_state.get("_last_call_ai_error", {})
                if _is_request_size_error(review_error):
                    st.info(
                        "The resume draft was generated successfully. The optional "
                        "second review pass was skipped because its combined draft and "
                        "evidence payload exceeded provider capacity."
                    )
                elif isinstance(review_error, dict) and review_error.get("message"):
                    st.warning(
                        "The resume draft was generated successfully, but the optional "
                        f"review pass was unavailable: {review_error['message']}"
                    )
                st.session_state.pop("last_ai_error", None)
                st.session_state.pop("_last_call_ai_error", None)
            if reviewed_draft:
                reviewed_draft = repair_grounded_resume_draft(
                    reviewed_draft,
                    ledger,
                    st.session_state["jd"],
                    role_plans,
                )
                reviewed_draft = enhance_resume_core_sections(
                    reviewed_draft,
                    ledger,
                    target_pages=target_pages,
                )
                reviewed_draft = repair_grounded_resume_draft(
                    reviewed_draft,
                    ledger,
                    st.session_state["jd"],
                    role_plans,
                )
                reviewed_validation = validate_grounded_resume_draft(
                    reviewed_draft, ledger, st.session_state["jd"]
                )
                if _validation_rank(reviewed_validation) <= _validation_rank(
                    first_validation
                ):
                    resume_draft = reviewed_draft
                    validation = reviewed_validation
                    review_pass = "two_pass_reviewed"
                else:
                    review_pass = "two_pass_rejected_unsafe_revision"

        # A model draft never leaves the user trapped behind the download gate.
        # If unsupported content remains after both repair stages, switch to the
        # polished source-only version and keep all mandatory candidate sections.
        if not validation.is_download_safe:
            safe_draft = build_safe_evidence_resume(
                ledger,
                st.session_state["jd"],
                role_plans,
                target_pages=target_pages,
            )
            safe_validation = validate_grounded_resume_draft(
                safe_draft,
                ledger,
                st.session_state["jd"],
            )
            if safe_validation.is_download_safe:
                resume_draft = safe_draft
                validation = safe_validation
                review_pass = "automatic_premium_safe_recovery"
        achievements = _achievement_examples_from_resume(
            resume_draft, sum(plan.target for plan in role_plans) or preferred_bullets
        )
        achievement_validation = (
            validate_achievement_claims(
                achievements, ledger, st.session_state["jd"]
            )
            if achievements
            else None
        )
        ideal_resume = clean_resume_output(
            strip_generation_annotations(resume_draft)
        )

        if not include_phone:
            for ph in [r"\[Your Phone Number\]", r"\[Your Email\]", r"\[LinkedIn Profile URL\]", r"\[City, State/Country\]"]:
                ideal_resume = re.sub(ph, "", ideal_resume, flags=re.IGNORECASE)
            ideal_resume = re.sub(r"\s*\|\s*\|\s*", " | ", ideal_resume)
            ideal_resume = re.sub(r"^\s*\|\s*$", "", ideal_resume, flags=re.MULTILINE)

        st.session_state["premium_resume_output"] = {
            "job_title": job_title,
            "fields": fields_str,
            "achievements": achievements,
            "achievement_validation": achievement_validation,
            "resume": ideal_resume,
            "annotated_resume": resume_draft,
            "used_resume": True,
            "candidate_name": alignment.resume.candidate_name,
            "validation": validation,
            "validation_mode": (
                "deterministic_capacity_recovery"
                if capacity_safe_fallback
                else "evidence_cited_generation"
            ),
            "review_pass": review_pass,
            "source_hash": ledger.source_hash,
            "strategy_id": selected_strategy.id,
            "strategy_name": selected_strategy.name,
            "domain": domain.profile.label,
            "role_bullet_plan": role_plans,
            "target_pages": target_pages,
        }
        st.session_state["ideal_resume"] = ideal_resume
        st.session_state.pop("truth_audit_resume_text", None)
        log_usage("generate_resume", fields=fields_str, job_title=job_title)

    # Show results
    rout = st.session_state.get("premium_resume_output", {})
    if rout:
        current_ledger = build_evidence_ledger(
            st.session_state.get("resume", ""),
            st.session_state.get("clarification_answers", {}),
        )
        source_changed = rout.get("source_hash") != current_ledger.source_hash
        existing_validation = rout.get("validation")
        if (
            not source_changed
            and isinstance(existing_validation, ClaimValidationReport)
        ):
            validation = existing_validation
        else:
            annotated_resume = rout.get("annotated_resume", "")
            if not annotated_resume and not source_changed:
                current_matrix = build_evidence_matrix(
                    st.session_state.get("jd", ""), current_ledger
                )
                role_plans = allocate_role_bullet_targets(
                    current_ledger,
                    current_matrix,
                    preferred_per_role=preferred_bullets,
                )
                annotated_resume = repair_grounded_resume_draft(
                    rout.get("resume", ""),
                    current_ledger,
                    st.session_state.get("jd", ""),
                    role_plans,
                )
                rout["annotated_resume"] = annotated_resume
            validation = validate_grounded_resume_draft(
                annotated_resume or rout.get("resume", ""),
                current_ledger,
                st.session_state.get("jd", ""),
            )
            rout["validation"] = validation
        if rout.get("achievements"):
            rout["achievement_validation"] = validate_achievement_claims(
                rout["achievements"],
                current_ledger,
                st.session_state.get("jd", ""),
            )
        st.session_state["claim_validation"] = validation
        st.divider()
        badge = "✅ Built from your resume + JD" if rout.get("used_resume") else "⚠️ Template (no resume provided)"
        st.info(
            f"{badge}  |  **Role:** {rout.get('job_title')}  |  "
            f"**Domain:** {rout.get('domain', rout.get('fields'))}  |  "
            f"**Strategy:** {rout.get('strategy_name', 'Direct evidence fit')}"
        )
        if rout.get("review_pass") == "two_pass_reviewed":
            st.caption(
                "Quality control: second-pass evidence, JD-mapping, and specificity "
                "review completed."
            )
        elif rout.get("review_pass") == "two_pass_rejected_unsafe_revision":
            st.warning(
                "The second-pass revision scored worse in the deterministic truth audit, "
                "so the safer first draft was retained."
            )
        elif rout.get("review_pass") == "safe_evidence_recovery":
            st.success(
                "Premium safe recovery applied: the summary, grouped skills, role "
                "coverage, qualifications, citations, and JD mappings now come from "
                "verified candidate evidence."
            )
        elif rout.get("review_pass") in {
            "capacity_safe_evidence_recovery",
            "automatic_premium_safe_recovery",
        }:
            st.success(
                "Automatic premium recovery passed the truth audit. The app retained "
                "the candidate's full section structure and used source-backed wording "
                "so downloads remain available."
            )
        elif rout.get("review_pass") == "ai_truth_repair":
            st.success(
                "AI-assisted truth repair completed and passed the deterministic audit."
            )
        elif rout.get("review_pass") == "ai_truth_repair_safe_fallback":
            st.success(
                "AI repair was completed. A few unsupported statements remained, so the "
                "app automatically used the verified evidence-only recovery to unlock "
                "downloads safely."
            )
        repair_summary = rout.get("truth_repair_summary")
        if isinstance(repair_summary, dict):
            st.caption(
                f"Truth repair: {repair_summary.get('issues_before', 0)} issue(s) before · "
                f"{repair_summary.get('issues_after', 0)} after."
            )
        role_plan = rout.get("role_bullet_plan", ())
        if role_plan:
            st.caption(
                "Fair role coverage: "
                + " · ".join(
                    f"{plan.role_header} ({plan.target})" for plan in role_plan
                )
            )
        visible_resume = rout.get("resume", "")
        visible_upper = visible_resume.upper()
        retained_sections = [
            label
            for label in (
                "PROFESSIONAL SUMMARY",
                "CORE SKILLS",
                "PROFESSIONAL EXPERIENCE",
                "EDUCATION",
                "CERTIFICATIONS",
                "PROJECTS",
            )
            if label in visible_upper
        ]
        if retained_sections:
            st.caption(
                "Premium structure retained: " + " · ".join(retained_sections)
            )
        summary_match = re.search(
            r"(?ims)^PROFESSIONAL SUMMARY\s*$\s*(.*?)"
            r"(?=^(?:CORE SKILLS|PROFESSIONAL EXPERIENCE|EDUCATION|"
            r"CERTIFICATIONS|PROJECTS)\s*$|\Z)",
            visible_resume,
        )
        skills_match = re.search(
            r"(?ims)^CORE SKILLS\s*$\s*(.*?)"
            r"(?=^(?:PROFESSIONAL EXPERIENCE|EDUCATION|CERTIFICATIONS|"
            r"PROJECTS)\s*$|\Z)",
            visible_resume,
        )
        summary_sentences = (
            len(
                [
                    value
                    for value in re.split(
                        r"(?<=[.!?])\s+",
                        summary_match.group(1).strip(),
                    )
                    if value.strip()
                ]
            )
            if summary_match
            else 0
        )
        skill_groups = (
            len(
                [
                    line
                    for line in skills_match.group(1).splitlines()
                    if ":" in line
                ]
            )
            if skills_match
            else 0
        )
        profile = current_ledger.profile
        if profile:
            st.caption(
                f"Depth check: {summary_sentences} summary sentence(s) · "
                f"{skill_groups} skill group(s) · {len(profile.roles)} exact role(s) · "
                f"{len(profile.education_records)} education record(s) · "
                f"{len(profile.certification_records)} certification record(s)."
            )
        if isinstance(validation, ClaimValidationReport):
            if source_changed:
                st.error(
                    "The source resume or verified evidence changed after this document "
                    "was generated. Regenerate before submitting it; review downloads "
                    "remain available."
                )
            elif validation.is_download_safe:
                st.success(
                    f"Truth audit passed: {validation.supported_claims}/"
                    f"{validation.claims_checked} checked claims have no detected issues."
                )
            else:
                st.error(
                    "Truth audit found unsupported claims. Use **Regenerate & improve** to "
                    "rewrite them, or **Create safe evidence-only version** before "
                    "submitting. Downloads remain enabled for your review."
                )
                with st.expander("View truth-audit issues", expanded=True):
                    for issue in validation.issues:
                        st.markdown(
                            f"- **{issue.claim_id} · {issue.issue_type}:** {issue.detail}"
                        )
                    st.caption(
                        "Citation, JD quote, mapping, and role-header codes are repaired "
                        "automatically. A remaining metric, skill, credential, education, "
                        "or date issue means the wording is not present in your source resume."
                    )

        tabs = st.tabs(
            ["📄 Resume Preview", "💡 Achievement Examples", "🛡️ Truth Audit & Edit"]
        )
        with tabs[0]:
            formatted = format_resume_for_display(rout.get("resume", ""))
            st.markdown(formatted, unsafe_allow_html=True)

        with tabs[1]:
            achievement_validation = rout.get("achievement_validation")
            if not rout.get("achievements"):
                st.info(
                    "No evidence-grounded achievement candidates are available for this resume."
                )
            elif (
                isinstance(achievement_validation, ClaimValidationReport)
                and achievement_validation.is_download_safe
            ):
                st.success(
                    f"Achievement truth audit passed: "
                    f"{achievement_validation.supported_claims}/"
                    f"{achievement_validation.claims_checked} checked claims."
                )
            elif isinstance(achievement_validation, ClaimValidationReport):
                st.error(
                    "These achievement examples contain unsupported content and must "
                    "not be copied into the resume."
                )
                for issue in achievement_validation.issues:
                    st.markdown(
                        f"- **{issue.claim_id} · {issue.issue_type}:** {issue.detail}"
                    )
            _display_md(rout.get("achievements", ""))

        with tabs[2]:
            st.caption(
                "Edit the visible wording below. The app will rebuild hidden citations, "
                "exact JD quotations, and source role headers before re-auditing."
            )
            if (
                isinstance(validation, ClaimValidationReport)
                and not validation.is_download_safe
                and not source_changed
            ):
                st.markdown("#### 🤖 Guided truth repair")
                st.write(
                    "AI can repair supported wording and remove claims that cannot be "
                    "verified. The deterministic audit—not the AI—still controls downloads."
                )
                if st.button(
                    "Fix all current issues with AI",
                    key="ai_truth_repair_all",
                    type="primary",
                    width="stretch",
                ):
                    if _run_ai_truth_repair(
                        rout,
                        current_ledger,
                        preferred_bullets=preferred_bullets,
                        prefs=prefs,
                    ):
                        st.rerun()

                evidence_claims = {}
                with st.expander("Issue-by-issue repair checklist", expanded=True):
                    for issue in validation.issues:
                        action, needs_evidence = _truth_issue_action(
                            issue.issue_type
                        )
                        st.markdown(
                            f"**{issue.claim_id} · {issue.issue_type}**  \n"
                            f"{issue.detail}  \n"
                            f"_{action}_"
                        )
                        if needs_evidence:
                            evidence_claims.setdefault(issue.claim_id, issue)

                if evidence_claims:
                    st.markdown("##### Add missing verified evidence")
                    st.caption(
                        "Only add facts you can defend in an interview or reference check. "
                        "Confirmed evidence becomes part of this application session and is "
                        "attached to the selected source role."
                    )
                    roles = (
                        list(current_ledger.profile.roles)
                        if current_ledger.profile
                        else []
                    )
                    role_options = [role.id for role in roles] or [""]
                    role_labels = {
                        role.id: role.header for role in roles
                    } | {"": "General candidate evidence"}
                    with st.form("truth_audit_evidence_form"):
                        evidence_inputs = {}
                        for claim_id, issue in evidence_claims.items():
                            st.markdown(
                                f"**{claim_id}: {issue.issue_type}**"
                            )
                            st.caption(issue.claim[:350])
                            selected_role_id = st.selectbox(
                                f"Attach {claim_id} evidence to role",
                                role_options,
                                format_func=lambda value: role_labels[value],
                                key=f"audit_evidence_role_{claim_id}",
                            )
                            evidence_text = st.text_area(
                                f"Verified evidence for {claim_id}",
                                key=f"audit_evidence_text_{claim_id}",
                                placeholder=(
                                    "State where and when this happened, what you personally "
                                    "did, the tool or skill used, and the exact measured "
                                    "outcome if one exists."
                                ),
                                height=110,
                            )
                            confirmed = st.checkbox(
                                "I confirm this statement is accurate and can be defended.",
                                key=f"audit_evidence_confirm_{claim_id}",
                            )
                            evidence_inputs[claim_id] = (
                                issue,
                                selected_role_id,
                                evidence_text,
                                confirmed,
                            )
                        save_evidence = st.form_submit_button(
                            "Save verified evidence & run AI repair",
                            type="primary",
                            width="stretch",
                        )
                    if save_evidence:
                        errors = []
                        additions = {}
                        for claim_id, (
                            issue,
                            role_id,
                            evidence_text,
                            confirmed,
                        ) in evidence_inputs.items():
                            clean_evidence = re.sub(
                                r"\s+", " ", evidence_text
                            ).strip()
                            if not clean_evidence:
                                continue
                            if not confirmed:
                                errors.append(
                                    f"{claim_id}: confirm the evidence before saving."
                                )
                                continue
                            if len(clean_evidence.split()) < 6:
                                errors.append(
                                    f"{claim_id}: add a more specific statement with at "
                                    "least the role/context and action."
                                )
                                continue
                            if "metric" in issue.issue_type:
                                unsupported_numbers = re.findall(
                                    r"(?:[$£€]\s*)?\d[\d,.]*(?:\s?%|\+)?",
                                    issue.detail + " " + issue.claim,
                                )
                                if (
                                    unsupported_numbers
                                    and not any(
                                        number.strip() in clean_evidence
                                        for number in unsupported_numbers
                                    )
                                ):
                                    errors.append(
                                        f"{claim_id}: include the exact metric being "
                                        "verified or leave this field blank so AI removes it."
                                    )
                                    continue
                            evidence_key = (
                                f"AUDIT-{role_id or 'GENERAL'}-{claim_id}-"
                                f"{issue.issue_type}"
                            )
                            additions[evidence_key] = clean_evidence
                        if errors:
                            for message in errors:
                                st.error(message)
                        elif not additions:
                            st.error(
                                "Add and confirm at least one evidence statement, or use "
                                "**Fix all current issues with AI** to remove unsupported claims."
                            )
                        else:
                            answers = dict(
                                st.session_state.get(
                                    "clarification_answers", {}
                                )
                            )
                            answers.update(additions)
                            st.session_state["clarification_answers"] = answers
                            updated_ledger = build_evidence_ledger(
                                st.session_state.get("resume", ""),
                                answers,
                            )
                            if _run_ai_truth_repair(
                                rout,
                                updated_ledger,
                                preferred_bullets=preferred_bullets,
                                prefs=prefs,
                            ):
                                st.rerun()

            with st.form("truth_audit_editor"):
                edited_resume = st.text_area(
                    "Editable optimized resume",
                    value=rout.get("resume", ""),
                    height=520,
                    key="truth_audit_resume_text",
                )
                apply_edit = st.form_submit_button(
                    "Apply edits and run truth audit",
                    type="primary",
                    width="stretch",
                )
            if apply_edit:
                edited_resume = clean_resume_output(edited_resume)
                current_matrix = build_evidence_matrix(
                    st.session_state.get("jd", ""), current_ledger
                )
                role_plans = allocate_role_bullet_targets(
                    current_ledger,
                    current_matrix,
                    preferred_per_role=preferred_bullets,
                )
                edited_annotated = repair_grounded_resume_draft(
                    edited_resume,
                    current_ledger,
                    st.session_state.get("jd", ""),
                    role_plans,
                )
                edited_annotated = enhance_resume_core_sections(
                    edited_annotated,
                    current_ledger,
                    target_pages=rout.get("target_pages", 3),
                )
                edited_annotated = repair_grounded_resume_draft(
                    edited_annotated,
                    current_ledger,
                    st.session_state.get("jd", ""),
                    role_plans,
                )
                edited_validation = validate_grounded_resume_draft(
                    edited_annotated,
                    current_ledger,
                    st.session_state.get("jd", ""),
                )
                edited_visible = strip_generation_annotations(edited_annotated)
                edited_achievements = _achievement_examples_from_resume(
                    edited_annotated,
                    sum(plan.target for plan in role_plans) or preferred_bullets,
                )
                updated = dict(rout)
                updated["resume"] = edited_visible
                updated["annotated_resume"] = edited_annotated
                updated["achievements"] = edited_achievements
                updated["achievement_validation"] = (
                    validate_achievement_claims(
                        edited_achievements,
                        current_ledger,
                        st.session_state.get("jd", ""),
                    )
                    if edited_achievements
                    else None
                )
                updated["validation"] = edited_validation
                updated["validation_mode"] = "manual_edit_with_deterministic_repair"
                updated["source_hash"] = current_ledger.source_hash
                updated["role_bullet_plan"] = role_plans
                st.session_state["premium_resume_output"] = updated
                st.session_state["ideal_resume"] = edited_visible
                st.session_state["claim_validation"] = edited_validation
                st.rerun()

        # Downloads
        docx_bytes = make_docx_from_text(
            rout.get("resume", ""), name=rout.get("candidate_name", "")
        )
        docx_parse = validate_docx_roundtrip(
            rout.get("resume", ""), docx_bytes
        )
        source_alignment = analyze_alignment(
            st.session_state.get("jd", ""), rout.get("resume", "")
        )
        extracted_alignment = analyze_alignment(
            st.session_state.get("jd", ""), docx_parse.extracted_text
        )
        score_delta = extracted_alignment.score - source_alignment.score
        docx_alignment_consistent = abs(score_delta) <= 2
        rout["docx_parseability"] = docx_parse
        rout["docx_extracted_alignment"] = extracted_alignment

        if docx_parse.is_safe and docx_alignment_consistent:
            st.success(
                f"DOCX round-trip passed: {docx_parse.score}/100 parseability; "
                f"extracted alignment {extracted_alignment.score}% "
                f"({score_delta:+d} points from preview)."
            )
        else:
            st.warning(
                "DOCX validation found an extraction or alignment warning. The download "
                "remains available so you can review it in Word; inspect the warnings "
                "below before submitting the resume."
            )
            for issue in docx_parse.issues:
                st.markdown(f"- {issue}")
            if not docx_alignment_consistent:
                st.markdown(
                    f"- Extracted alignment changed from {source_alignment.score}% "
                    f"to {extracted_alignment.score}%."
                )

        truth_warning = (
            isinstance(validation, ClaimValidationReport)
            and not validation.is_download_safe
        )
        if source_changed or truth_warning:
            st.warning(
                "Download is enabled for review. The file represents the generated "
                "version currently shown above; resolve any source-change or truth-audit "
                "warning before using it in an application."
            )
        download_ready = bool(rout.get("resume", "").strip()) and bool(docx_bytes)
        candidate_slug = re.sub(
            r"[^A-Za-z0-9]+",
            "_",
            rout.get("candidate_name", "").strip(),
        ).strip("_")
        docx_name = (
            f"{candidate_slug}_ATS_Resume.docx"
            if candidate_slug
            else "ATS_Optimized_Resume.docx"
        )
        dl1, dl2 = st.columns(2)
        with dl1:
            st.download_button(
                "📥 Download DOCX",
                data=docx_bytes,
                file_name=docx_name,
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                width="stretch",
                disabled=not download_ready,
            )
        with dl2:
            st.download_button(
                "📥 Download Markdown",
                data=rout.get("resume", "").encode(),
                file_name="ats_optimized_resume.md",
                mime="text/markdown",
                width="stretch",
                disabled=not download_ready,
            )

        # Comparison — use a toggle button instead of a nested expander
        if rout.get("used_resume"):
            st.divider()
            if st.button(
                "🔄 Toggle Side-by-Side Comparison",
                key="toggle_comparison",
                width="stretch",
            ):
                st.session_state["show_comparison"] = not st.session_state.get("show_comparison", False)

            if st.session_state.get("show_comparison", False):
                with st.container():
                    st.markdown("#### 🔄 Original vs Optimized")
                    cc1, cc2 = st.columns(2, gap="large")
                    orig = st.session_state.get("resume", "")
                    opt = rout.get("resume", "")
                    jd_text = st.session_state.get("jd", "")

                    with cc1:
                        st.markdown("**📄 Original**")
                        st.caption(f"{len(orig.split())} words · {len(orig.splitlines())} lines")
                        st.text_area("orig", value=orig, height=420, disabled=True, label_visibility="collapsed")
                    with cc2:
                        st.markdown("**✨ Optimized**")
                        st.caption(f"{len(opt.split())} words · {len(opt.splitlines())} lines")
                        st.text_area("opt", value=opt, height=420, disabled=True, label_visibility="collapsed")

                    if jd_text:
                        m1, m2, m3 = st.columns(3)
                        original_alignment = analyze_alignment(jd_text, orig)
                        optimized_alignment = analyze_alignment(jd_text, opt)
                        os_ = original_alignment.score
                        ots = optimized_alignment.score
                        with m1:
                            st.metric(
                                "Job Alignment Score",
                                f"{ots}%",
                                delta=f"{ots-os_:+d} points",
                            )
                        with m2:
                            st.metric("Words", len(opt.split()), delta=len(opt.split()) - len(orig.split()))
                        with m3:
                            orig_b = orig.count("•") + len(re.findall(r"^\s*[-\*]\s", orig, re.M))
                            opt_b = opt.count("•") + len(re.findall(r"^\s*[-\*]\s", opt, re.M))
                            st.metric("Bullets", opt_b, delta=opt_b - orig_b)


def _render_cover_letter(prefs: dict):
    with st.form("cover_gen_form"):
        tone = st.selectbox(
            "Tone",
            ["Confident & Direct", "Warm & Collaborative", "Humble & Impact-Focused"],
            key="cg_tone",
        )
        snippet = st.text_area(
            "Short Resume Snippet (optional — 1-3 lines)",
            height=80,
            key="cg_snip",
            placeholder="e.g. 5 years in digital marketing, led campaigns generating $2M in pipeline…",
        )
        verified_two_pass = st.checkbox(
            "Verified two-pass review",
            value=True,
            key="cover_verified_two_pass",
            help=(
                "Recommended for final applications. Disable to use fewer API tokens."
            ),
        )
        submitted = st.form_submit_button("✉️ Generate Cover Letter", type="primary", width="stretch")

    if submitted:
        if not _api_guard(prefs):
            return
        if not st.session_state.get("jd", "").strip():
            st.error("Paste the JD in the Analyze tab first.")
            return

        raw_resume = st.session_state.get("resume", "")
        if not raw_resume.strip() and not snippet.strip():
            st.error("Add your resume or a verified resume snippet before generating a cover letter.")
            return
        cover_answers = dict(
            st.session_state.get("clarification_answers", {})
        )
        if snippet.strip():
            cover_answers["cover-letter-snippet"] = snippet.strip()
        cover_ledger = build_evidence_ledger(raw_resume, cover_answers)
        if not cover_ledger.items:
            st.error(
                "The supplied resume evidence is too short to support a cover letter."
            )
            return
        cover_matrix = build_evidence_matrix(st.session_state["jd"], cover_ledger)
        cover_evidence = compact_grounding_context(
            cover_ledger, cover_matrix, max_chars=6000
        )
        snippet_use = cover_evidence
        with st.spinner("Writing cover letter…"):
            letter = _call_ai(
                COVER_LETTER_PROMPT.format(
                    tone=tone, jd=st.session_state["jd"], resume_snippet=snippet_use
                ),
                system_prompt=RESUME_WRITER_SYSTEM_PROMPT,
                temperature=0.2,
                task="cover_letter",
            )
        if letter:
            cover_source_text = "\n".join(item.text for item in cover_ledger.items)
            cover_name = (
                cover_ledger.profile.candidate_name
                if cover_ledger.profile
                else ""
            )
            letter = finalize_cover_letter(
                letter,
                cover_source_text,
                cover_name,
            )
            first_cover_validation = validate_generated_claims(
                letter, cover_ledger, st.session_state["jd"]
            )
            cover_validation = first_cover_validation
            review_pass = "single_pass"
            if verified_two_pass:
                refinement_prompt = build_cover_letter_refinement_prompt(
                    draft=letter,
                    tone=tone,
                    candidate_evidence=cover_evidence,
                    requirement_context="\n".join(
                        f"[{row.id}] {row.status} | {row.requirement}"
                        for row in cover_matrix.rows[:10]
                        if row.status in {"direct", "equivalent", "transferable"}
                    ),
                    deterministic_findings=_validation_findings(
                        first_cover_validation
                    ),
                )
                with st.spinner(
                    "Reviewing evidence fit, role relevance, and generic phrasing…"
                ):
                    reviewed_letter = _call_ai(
                        refinement_prompt,
                        system_prompt=RESUME_WRITER_SYSTEM_PROMPT,
                        temperature=0.05,
                        task="cover_letter",
                        show_error=False,
                    )
                review_pass = "two_pass_unavailable"
                if reviewed_letter:
                    reviewed_letter = finalize_cover_letter(
                        reviewed_letter,
                        cover_source_text,
                        cover_name,
                    )
                    reviewed_cover_validation = validate_generated_claims(
                        reviewed_letter, cover_ledger, st.session_state["jd"]
                    )
                    if _validation_rank(
                        reviewed_cover_validation
                    ) <= _validation_rank(first_cover_validation):
                        letter = reviewed_letter
                        cover_validation = reviewed_cover_validation
                        review_pass = "two_pass_reviewed"
                    else:
                        review_pass = "two_pass_rejected_unsafe_revision"
                else:
                    st.session_state.pop("last_ai_error", None)
                    st.session_state.pop("_last_call_ai_error", None)
            st.session_state["premium_cover_output"] = {
                "tone": tone,
                "letter": letter,
                "validation": cover_validation,
                "review_pass": review_pass,
            }
            log_usage("generate_cover_letter")

    cov = st.session_state.get("premium_cover_output", {})
    if cov:
        st.divider()
        st.markdown(f"*Tone: {cov.get('tone')}*")
        if cov.get("review_pass") == "two_pass_reviewed":
            st.caption(
                "Quality control: second-pass evidence, role-relevance, and "
                "genericity review completed."
            )
        elif cov.get("review_pass") == "two_pass_rejected_unsafe_revision":
            st.warning(
                "The reviewed letter introduced more truth-audit risk, so the safer "
                "first draft was retained."
            )
        elif cov.get("review_pass") == "two_pass_unavailable":
            st.caption(
                "The optional review pass was unavailable; the completed, grounded "
                "first pass was retained."
            )
        _display_md(cov.get("letter", ""))
        cover_validation = cov.get("validation")
        if isinstance(cover_validation, ClaimValidationReport):
            if cover_validation.is_download_safe:
                st.success("Cover-letter truth audit passed.")
            else:
                st.error(
                    "The cover letter contains unsupported claims. Downloads remain "
                    "available for review, but resolve these issues before submission."
                )
                for issue in cover_validation.issues:
                    st.markdown(f"- **{issue.issue_type}:** {issue.detail}")

        cover_ready = bool(cov.get("letter", "").strip())
        dl1, dl2 = st.columns(2)
        with dl1:
            st.download_button(
                "📥 Download DOCX",
                data=make_docx_from_text(cov.get("letter", "")),
                file_name="Cover_Letter.docx",
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                width="stretch",
                disabled=not cover_ready,
            )
        with dl2:
            st.download_button(
                "📥 Download Markdown",
                data=cov.get("letter", "").encode(),
                file_name="cover_letter.md",
                mime="text/markdown",
                width="stretch",
                disabled=not cover_ready,
            )


def _render_custom_query(prefs: dict):
    custom_q = st.text_input(
        "Your question",
        key="premium_custom_q",
        placeholder="e.g. What are my top 3 gaps? / How should I tailor my summary?",
    )
    if st.button("💬 Ask", key="btn_custom_q", type="primary", width="stretch"):
        if not _api_guard(prefs):
            return
        if not _jd_resume_guard():
            return
        if not custom_q.strip():
            st.error("Enter a question first.")
            return
        ledger = build_evidence_ledger(
            st.session_state["resume"],
            st.session_state.get("clarification_answers", {}),
        )
        matrix = build_evidence_matrix(st.session_state["jd"], ledger)
        with st.spinner("Thinking…"):
            answer = _call_ai(
                CUSTOM_QUERY_PROMPT.format(
                    custom_query=custom_q,
                    jd=st.session_state["jd"],
                    text=compact_grounding_context(ledger, matrix),
                ),
                task="query",
            )
        if answer:
            st.session_state["premium_custom_output"] = answer
            log_usage("custom_query")

    if st.session_state.get("premium_custom_output"):
        st.divider()
        custom_output = sanitize_candidate_feedback(
            st.session_state["premium_custom_output"],
            st.session_state.get("resume", ""),
        )
        _display_md(custom_output)
        custom_docx = make_docx_from_text(
            custom_output,
            name="ATS Resume Studio Advisory",
        )
        q1, q2 = st.columns(2)
        with q1:
            st.download_button(
                "📥 Download Advisory DOCX",
                data=custom_docx,
                file_name="ATS_Resume_Studio_Advisory.docx",
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                width="stretch",
                key="download_custom_advisory_docx",
            )
        with q2:
            st.download_button(
                "📥 Download Advisory Markdown",
                data=custom_output.encode("utf-8"),
                file_name="ats_resume_studio_advisory.md",
                mime="text/markdown",
                width="stretch",
                key="download_custom_advisory_md",
            )

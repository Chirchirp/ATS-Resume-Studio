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
    get_recruiter_system_prompt,
)
from utils.ai_runtime import run_ai, user_safe_ai_error
from utils.ats_engine import AlignmentReport, analyze_alignment, top_requirement_text
from utils.docx_builder import make_docx_from_text, validate_docx_roundtrip
from utils.domain_profiles import domain_prompt_context, infer_domain_context
from utils.evidence_engine import (
    ClaimValidationReport,
    build_evidence_ledger,
    build_evidence_matrix,
    compact_grounding_context,
    strip_generation_annotations,
    validate_achievement_claims,
    validate_generated_claims,
    validate_grounded_resume_draft,
)
from utils.logger import log_usage
from utils.text_processing import (
    clean_resume_output,
    format_resume_for_display,
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
            st.info(f"Primary provider was unavailable; {result.provider} completed this request.")
        return result.text
    except Exception as exc:
        st.error(f"AI request failed: {user_safe_ai_error(exc)}")
        return ""


def _validation_rank(report: ClaimValidationReport) -> tuple[int, int, int]:
    """Lower is better; deterministic safety outranks stylistic preference."""
    high = sum(issue.severity == "high" for issue in report.issues)
    medium = sum(issue.severity == "medium" for issue in report.issues)
    return high, medium, -report.supported_claims


def _validation_findings(report: ClaimValidationReport, limit: int = 16) -> str:
    if not report.issues:
        return "No machine-detected issue. Complete the full editorial checklist."
    return "\n".join(
        f"- {issue.claim_id} | {issue.issue_type}: {issue.detail}"
        for issue in report.issues[:limit]
    )


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


def _infer_field(jd_text: str, prefs: dict) -> str:
    if prefs.get("target_field", "").strip():
        return prefs["target_field"].strip()
    if prefs.get("auto_infer_field") and jd_text.strip() and is_api_key_set():
        resp = _call_ai(
            INFER_FIELD_PROMPT.format(jd=jd_text),
            temperature=0.0,
            task="classification",
        )
        label = resp.strip().splitlines()[0][:40].strip("\"' ")
        st.session_state["inferred_field"] = label
        return label or "General"
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
                grounding = compact_grounding_context(ledger, matrix)
                with st.spinner("Sarah Chen is reviewing your resume… (30-60 s)"):
                    result = _call_ai(
                        build_recruiter_prompt(
                            fields=fields_ctx,
                            jd=st.session_state["jd"],
                            resume=grounding,
                        ),
                        system_prompt=get_recruiter_system_prompt() + " " + BASE_SYSTEM_PROMPT,
                        temperature=0.2,
                        task="recruiter",
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
            bullets_count = st.select_slider(
                "Bullets per role", [3, 4, 5, 6, 7], value=prefs["achievements_count"]
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

    if submitted:
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
        grounding = compact_grounding_context(ledger, matrix)
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
            try:
                resume_prompt = build_grounded_resume_prompt(
                    fields=fields_str,
                    job_description=st.session_state["jd"],
                    candidate_evidence=grounding,
                    strategy_context=strategy_context,
                )
            except ValueError as exc:
                st.error(str(exc))
                return
            resume_draft = clean_resume_output(
                _call_ai(
                    resume_prompt,
                    system_prompt=RESUME_WRITER_SYSTEM_PROMPT,
                    temperature=0.15,
                    task="resume",
                )
            )
        if not resume_draft:
            return
        first_validation = validate_grounded_resume_draft(
            resume_draft, ledger, st.session_state["jd"]
        )
        review_pass = "single_pass"
        validation = first_validation
        if verified_two_pass:
            refinement_prompt = build_resume_refinement_prompt(
                draft=resume_draft,
                candidate_evidence=grounding,
                deterministic_findings=_validation_findings(first_validation),
            )
            with st.spinner("Reviewing evidence, JD mappings, and specificity…"):
                reviewed_draft = clean_resume_output(
                    _call_ai(
                        refinement_prompt,
                        system_prompt=RESUME_WRITER_SYSTEM_PROMPT,
                        temperature=0.05,
                        task="resume",
                    )
                )
            if reviewed_draft:
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
        achievements = _achievement_examples_from_resume(
            resume_draft, bullets_count
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
            "used_resume": True,
            "candidate_name": alignment.resume.candidate_name,
            "validation": validation,
            "validation_mode": "evidence_cited_generation",
            "review_pass": review_pass,
            "source_hash": ledger.source_hash,
            "strategy_id": selected_strategy.id,
            "strategy_name": selected_strategy.name,
            "domain": domain.profile.label,
        }
        st.session_state["ideal_resume"] = ideal_resume
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
            validation = validate_generated_claims(
                rout.get("resume", ""),
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
        if isinstance(validation, ClaimValidationReport):
            if source_changed:
                st.error(
                    "The source resume or verified evidence changed after this document "
                    "was generated. Regenerate it before downloading."
                )
            elif validation.is_download_safe:
                st.success(
                    f"Truth audit passed: {validation.supported_claims}/"
                    f"{validation.claims_checked} checked claims have no detected issues."
                )
            else:
                st.error(
                    "Truth audit found unsupported claims. Downloads are disabled until the "
                    "document is regenerated or the underlying evidence is verified."
                )
                with st.expander("View truth-audit issues", expanded=True):
                    for issue in validation.issues:
                        st.markdown(
                            f"- **{issue.claim_id} · {issue.issue_type}:** {issue.detail}"
                        )

        tabs = st.tabs(
            ["📄 Resume Preview", "💡 Achievement Examples", "🛡️ Truth Audit & Edit"]
        )
        with tabs[0]:
            formatted = format_resume_for_display(rout.get("resume", ""))
            st.markdown(
                '<div style="background:white; padding:28px 32px; border-radius:10px; '
                'border:1px solid #e0e0e0; font-family:Georgia,serif; line-height:1.7;">',
                unsafe_allow_html=True,
            )
            st.markdown(formatted)
            st.markdown("</div>", unsafe_allow_html=True)

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
                "Edit unsupported statements or add verified evidence in the Evidence & Truth tab, then re-audit."
            )
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
                edited_validation = validate_generated_claims(
                    edited_resume,
                    current_ledger,
                    st.session_state.get("jd", ""),
                )
                updated = dict(rout)
                updated["resume"] = edited_resume
                updated["validation"] = edited_validation
                updated["validation_mode"] = "manual_edit"
                updated["source_hash"] = current_ledger.source_hash
                st.session_state["premium_resume_output"] = updated
                st.session_state["ideal_resume"] = edited_resume
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
            st.error(
                "DOCX round-trip validation found an extraction risk. DOCX download "
                "is disabled; Markdown remains available when the truth audit passes."
            )
            for issue in docx_parse.issues:
                st.markdown(f"- {issue}")
            if not docx_alignment_consistent:
                st.markdown(
                    f"- Extracted alignment changed from {source_alignment.score}% "
                    f"to {extracted_alignment.score}%."
                )

        dl1, dl2 = st.columns(2)
        with dl1:
            st.download_button(
                "📥 Download DOCX",
                data=docx_bytes,
                file_name="ATS_Optimized_Resume.docx",
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                width="stretch",
                disabled=source_changed
                or not docx_parse.is_safe
                or not docx_alignment_consistent
                or (
                    isinstance(validation, ClaimValidationReport)
                    and not validation.is_download_safe
                ),
            )
        with dl2:
            st.download_button(
                "📥 Download Markdown",
                data=rout.get("resume", "").encode(),
                file_name="ats_optimized_resume.md",
                mime="text/markdown",
                width="stretch",
                disabled=source_changed
                or (
                    isinstance(validation, ClaimValidationReport)
                    and not validation.is_download_safe
                ),
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
                    )
                review_pass = "two_pass_unavailable"
                if reviewed_letter:
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
        _display_md(cov.get("letter", ""))
        cover_validation = cov.get("validation")
        if isinstance(cover_validation, ClaimValidationReport):
            if cover_validation.is_download_safe:
                st.success("Cover-letter truth audit passed.")
            else:
                st.error("Downloads are disabled because the cover letter contains unsupported claims.")
                for issue in cover_validation.issues:
                    st.markdown(f"- **{issue.issue_type}:** {issue.detail}")

        dl1, dl2 = st.columns(2)
        with dl1:
            st.download_button(
                "📥 Download DOCX",
                data=make_docx_from_text(cov.get("letter", "")),
                file_name="Cover_Letter.docx",
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                width="stretch",
                disabled=isinstance(cover_validation, ClaimValidationReport)
                and not cover_validation.is_download_safe,
            )
        with dl2:
            st.download_button(
                "📥 Download Markdown",
                data=cov.get("letter", "").encode(),
                file_name="cover_letter.md",
                mime="text/markdown",
                width="stretch",
                disabled=isinstance(cover_validation, ClaimValidationReport)
                and not cover_validation.is_download_safe,
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
        _display_md(st.session_state["premium_custom_output"])

"""
components/tab_analyze.py — Analyze tab: JD + resume input, keyword match, expert analysis.
"""

import streamlit as st
from prompts.templates import (
    BASE_SYSTEM_PROMPT,
    EXPERT_ANALYSIS_PROMPT,
    INFER_FIELD_PROMPT,
    RESUME_QUALITY_SYSTEM_PROMPT,
    RESUME_WRITER_SYSTEM_PROMPT,
    build_achievement_prompt,
    build_achievement_refinement_prompt,
    build_resume_quality_prompt,
)
from utils.ats_engine import (
    analyze_alignment,
    extract_resume_profile,
    top_requirement_text,
)
from utils.ai_runtime import run_ai, user_safe_ai_error
from utils.domain_profiles import deterministic_field_label, normalize_field_label
from utils.evidence_engine import (
    achievement_grounding_context,
    build_evidence_ledger,
    build_evidence_matrix,
    compact_grounding_context,
    validate_achievement_claims,
)
from utils.logger import log_usage
from utils.resume_quality_engine import ResumeQualityReport, analyze_resume_quality
from utils.text_processing import (
    extract_text_from_pdf,
    sanitize_display_text,
)
from config.settings import get_provider_label, is_api_key_set


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
            st.info(
                f"Primary AI route was unavailable; "
                f"{result.provider} / {result.model} completed this request."
            )
        return result.text
    except Exception as exc:
        st.error(f"AI request failed: {user_safe_ai_error(exc)}")
        return ""


def _claim_validation_rank(report) -> tuple[int, int, int]:
    high = sum(issue.severity == "high" for issue in report.issues)
    medium = sum(issue.severity == "medium" for issue in report.issues)
    return high, medium, -report.supported_claims


def _infer_field(jd_text: str, prefs: dict) -> str:
    """Infer field from JD or return the user-set field."""
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


def _quality_findings_context(report: ResumeQualityReport) -> str:
    findings = [
        f"Overall deterministic score: {report.score}/100 ({report.grade})",
        "Detected sections: " + (", ".join(report.detected_sections) or "none"),
    ]
    findings.extend(
        f"- [{issue.severity.upper()}] {issue.category}: {issue.message} "
        f"Evidence: {issue.evidence}"
        for issue in report.issues[:12]
    )
    return "\n".join(findings)


def _render_quality_report(
    report: ResumeQualityReport,
    ai_feedback: str,
    current_resume: str,
):
    st.markdown("### 🩺 Resume Quality Review")
    st.caption(
        "Standalone review — structure, language, dates, career continuity, and ATS readability "
        "before matching the resume to a job."
    )
    current_hash = analyze_resume_quality(current_resume).source_hash
    if current_hash != report.source_hash:
        st.warning(
            "The resume has changed since this review was created. Run Resume Quality Review again "
            "before applying these recommendations."
        )

    score_col, grade_col, issue_col, words_col = st.columns(4)
    score_col.metric("Resume quality", f"{report.score}/100")
    grade_col.metric("Readiness", report.grade)
    issue_col.metric(
        "High-priority issues",
        sum(issue.severity == "high" for issue in report.issues),
    )
    words_col.metric("Extracted words", report.word_count)
    st.progress(report.score / 100)

    dimension_columns = st.columns(4)
    for column, dimension in zip(dimension_columns, report.dimensions):
        with column:
            st.markdown(f"**{dimension.label}**")
            st.markdown(f"### {dimension.score}/{dimension.maximum}")
            st.caption(dimension.explanation)

    priority_tab, dates_tab, structure_tab, strengths_tab = st.tabs(
        ["Priority fixes", "Dates & gaps", "Structure & ATS", "What already works"]
    )
    with priority_tab:
        if report.issues:
            for index, issue in enumerate(report.issues[:10], start=1):
                severity = {
                    "high": "🔴 High",
                    "medium": "🟠 Medium",
                    "low": "🔵 Polish",
                }[issue.severity]
                st.markdown(
                    f"**{index}. {issue.message}**  \n"
                    f"`{severity}` · {issue.category}  \n"
                    f"**Evidence:** {issue.evidence}  \n"
                    f"**Fix:** {issue.recommendation}"
                )
                if index < min(10, len(report.issues)):
                    st.divider()
        else:
            st.success("No material deterministic issues were detected.")

    with dates_tab:
        date_issues = [
            issue for issue in report.issues if issue.category == "Dates & chronology"
        ]
        if report.date_ranges:
            st.markdown("**Detected employment ranges**")
            for date_range in report.date_ranges:
                st.markdown(
                    f"- `{date_range.start_label} {date_range.separator} "
                    f"{date_range.end_label}` — {date_range.source_line}"
                )
        else:
            st.info("No reliable employment date ranges were found in the extracted text.")
        if date_issues:
            st.markdown("**Items to verify**")
            for issue in date_issues:
                st.markdown(f"- **{issue.message}** {issue.recommendation}")
        st.caption(
            "This checks date format and sequence in extracted text. Confirm visual right-edge "
            "alignment, tabs, and columns in the original PDF or DOCX."
        )

    with structure_tab:
        structural = [
            issue
            for issue in report.issues
            if issue.category in {"Structure", "ATS readability"}
        ]
        st.markdown(
            "**Detected sections:** "
            + (", ".join(name.title() for name in report.detected_sections) or "None")
        )
        if structural:
            for issue in structural:
                st.markdown(f"- **{issue.message}** {issue.recommendation}")
        else:
            st.success("No material structure or plain-text ATS risks were detected.")
        st.caption(
            "Plain-text review cannot reliably detect font size, margins, color contrast, headers, "
            "footers, or exact page count."
        )

    with strengths_tab:
        if report.strengths:
            for strength in report.strengths:
                st.markdown(f"- {strength}")
        else:
            st.info(
                "The review did not find enough reliable structural signals to name a strength yet."
            )

    st.markdown("#### ✍️ Line-level grammar and editorial feedback")
    if ai_feedback:
        _display_md(ai_feedback)
    else:
        st.info(
            "The deterministic review above is complete. Add an AI provider key to receive "
            "line-specific grammar corrections and an editorial action plan."
        )


def render_tab_analyze(prefs: dict):
    """Render the Analyze tab."""

    # ── Input section ──────────────────────────────────────────────────────────
    st.markdown(
        '<p class="section-label">📋 Input — Resume First, Then Target Job</p>',
        unsafe_allow_html=True,
    )

    left, right = st.columns([3, 2], gap="large")

    with left:
        uploaded = st.file_uploader(
            "Upload Resume (PDF)",
            type=["pdf"],
            key="upload_pdf",
            help="We'll extract the text automatically.",
        )
        extracted = ""
        if uploaded:
            with st.spinner("Extracting PDF text…"):
                extracted = extract_text_from_pdf(uploaded)
            if not extracted:
                st.warning("Could not extract text from this PDF — paste your resume below instead.")

        resume_raw = st.text_area(
            "Or Paste Resume Text",
            value=extracted,
            height=200,
            key="resume_raw",
            placeholder="Paste resume text here (or upload PDF above)…",
        )
        resume = resume_raw or extracted or ""
        st.session_state["resume"] = resume
        st.session_state["resume_profile"] = (
            extract_resume_profile(resume) if resume.strip() else None
        )

        jd_raw = st.text_area(
            "Paste Job Description (for steps 2–4)",
            height=230,
            key="jd_raw",
            placeholder="Optional for Resume Quality Review. Paste it when you are ready to match a role…",
            help="The resume-only quality review does not require this. Later actions use it for job alignment.",
        )

        # Sanitize
        jd = "" if ("{" in jd_raw and "}" in jd_raw and "background" in jd_raw.lower()) else jd_raw
        st.session_state["jd"] = jd

    with right:
        st.markdown("#### 📊 Live Match Preview")
        jd_ok = bool(st.session_state.get("jd", "").strip())
        res_ok = bool(st.session_state.get("resume", "").strip())

        if jd_ok and res_ok:
            report = analyze_alignment(
                st.session_state["jd"], st.session_state["resume"]
            )
            st.session_state["resume_profile"] = report.resume
            score = report.score
            matched = report.matched_terms
            missing = report.missing_required + report.missing_preferred
            # Score gauge
            colour = "#22c55e" if score >= 70 else "#f59e0b" if score >= 50 else "#ef4444"
            st.markdown(
                f"""
                <div style="text-align:center; padding:16px; background:#f8faff;
                            border-radius:12px; border:1px solid #e0e8ff; margin-bottom:12px;">
                    <div style="font-size:52px; font-weight:800; color:{colour}; line-height:1;">
                        {score}%
                    </div>
                    <div style="font-size:13px; color:#666; margin-top:4px;">Job Alignment Score</div>
                </div>
                """,
                unsafe_allow_html=True,
            )
            st.progress(score / 100)

            col_a, col_b = st.columns(2)
            with col_a:
                st.metric("Matched", f"{len(matched)} keywords")
            with col_b:
                st.metric("Confidence", report.confidence)

            with st.expander(f"✅ Matched terms ({len(matched)})"):
                st.write(", ".join(matched[:50]) or "—")
                if report.matched_phrases:
                    st.markdown(
                        "**Matched 2-3 word phrases:** "
                        + ", ".join(report.matched_phrases[:25])
                    )
            with st.expander("📍 Match provenance by resume section"):
                if report.section_matches:
                    for section, terms in report.section_matches.items():
                        st.markdown(
                            f"**{section.title()}:** "
                            + ", ".join(terms[:25])
                        )
                else:
                    st.write("No section-level matches were detected.")
            with st.expander(f"⚠️ Requirement gaps ({len(missing)})"):
                for item in missing[:15]:
                    st.markdown(f"- {item}")
                if report.missing_terms:
                    st.caption(
                        "Unmatched normalized terms/phrases: "
                        + ", ".join(report.missing_terms[:30])
                    )
            with st.expander("How this score was calculated"):
                for dimension in report.dimensions:
                    st.markdown(
                        f"**{dimension.label}: {dimension.score:.1f}/{dimension.maximum:.0f}**  \n"
                        f"{dimension.explanation}"
                    )
                st.caption(
                    "This is a transparent job-alignment estimate, not a score from a specific ATS vendor."
                )
        else:
            profile = st.session_state.get("resume_profile")
            if res_ok and profile:
                parsed_bullets = sum(
                    len(role.bullets) for role in profile.roles
                )
                st.info(
                    f"Resume structured: {len(profile.roles)} role(s), "
                    f"{parsed_bullets} role bullet(s), "
                    f"{len(profile.declared_skills)} declared skill(s). "
                    "Add a Job Description to calculate alignment."
                )
                if profile.parse_warnings:
                    st.warning(" ".join(profile.parse_warnings))
            else:
                st.info(
                    "Paste a Job Description **and** resume on the left to see "
                    "your live match score."
                )

    st.divider()

    # ── Action buttons ─────────────────────────────────────────────────────────
    st.markdown("#### ⚡ Quick Actions")
    with st.container(border=True):
        action_text, action_button = st.columns([3, 2], vertical_alignment="center")
        with action_text:
            st.markdown("##### 1 · Resume Quality Review — start here")
            st.caption(
                "Review structure, grammar signals, date consistency, possible career gaps, "
                "and ATS readability. No job description is required."
            )
        with action_button:
            if st.button(
                "🩺 Review Resume Quality",
                width="stretch",
                type="primary",
            ):
                if not st.session_state.get("resume", "").strip():
                    st.error("Upload or paste your resume first. A job description is not required.")
                else:
                    st.session_state["do_resume_quality"] = True

    st.markdown("##### Next · Compare and optimize for a target role")
    c1, c2, c3 = st.columns(3)

    with c1:
        if st.button("2 · 🔍 Quick Keyword Match", width="stretch"):
            if not st.session_state.get("jd", "").strip() or not st.session_state.get("resume", "").strip():
                st.error("Provide both JD and resume first.")
            else:
                report = analyze_alignment(
                    st.session_state["jd"], st.session_state["resume"]
                )
                st.success(
                    f"Job Alignment Score: **{report.score}%** ({report.confidence} confidence) — "
                    f"{len(report.matched_terms)} matched terms/phrases and "
                    f"{len(report.missing_required)} required gaps."
                )
                st.session_state["last_match"] = report
                log_usage("quick_keyword_match", fields=prefs.get("target_field", ""))

    with c2:
        if st.button("3 · 🧠 Run Expert Analysis", width="stretch"):
            if not prefs["api_ready"]:
                st.error(f"Enter your {get_provider_label()} API key in the sidebar first.")
            elif not st.session_state.get("jd", "").strip() or not st.session_state.get("resume", "").strip():
                st.error("Provide both JD and resume first.")
            else:
                st.session_state["do_analysis"] = True

    with c3:
        if st.button("4 · ⚡ Quick Fix Bullets", width="stretch"):
            if not prefs["api_ready"]:
                st.error(f"Enter your {get_provider_label()} API key in the sidebar first.")
            elif not st.session_state.get("jd", "").strip() or not st.session_state.get("resume", "").strip():
                st.error("Provide both JD and resume first.")
            else:
                st.session_state["do_quickfix"] = True

    # ── Standalone resume quality review ─────────────────────────────────────
    if st.session_state.get("do_resume_quality"):
        resume_v = st.session_state.get("resume", "")
        with st.spinner("Checking structure, language, dates, and career continuity…"):
            quality_report = analyze_resume_quality(resume_v)
        ai_feedback = ""
        if prefs["api_ready"]:
            quality_ledger = build_evidence_ledger(resume_v)
            quality_matrix = build_evidence_matrix("", quality_ledger)
            quality_prompt = build_resume_quality_prompt(
                resume_v,
                _quality_findings_context(quality_report),
                compact_grounding_context(
                    quality_ledger, quality_matrix, max_chars=7000
                ),
            )
            with st.spinner("Adding line-level grammar and editorial feedback…"):
                ai_feedback = _call_ai(
                    quality_prompt,
                    system_prompt=RESUME_QUALITY_SYSTEM_PROMPT,
                    temperature=0.1,
                    task="resume_quality",
                )
        st.session_state["last_resume_quality"] = quality_report
        st.session_state["last_resume_quality_ai"] = ai_feedback
        st.session_state["do_resume_quality"] = False
        log_usage("resume_quality_review", fields="resume_only")

    quality_report = st.session_state.get("last_resume_quality")
    if isinstance(quality_report, ResumeQualityReport):
        _render_quality_report(
            quality_report,
            st.session_state.get("last_resume_quality_ai", ""),
            st.session_state.get("resume", ""),
        )

    # ── Expert analysis ────────────────────────────────────────────────────────
    if st.session_state.get("do_analysis"):
        fields_str = _infer_field(st.session_state.get("jd", ""), prefs)
        analysis_ledger = build_evidence_ledger(
            st.session_state.get("resume", ""),
            st.session_state.get("clarification_answers", {}),
        )
        analysis_matrix = build_evidence_matrix(
            st.session_state.get("jd", ""), analysis_ledger
        )
        prompt = EXPERT_ANALYSIS_PROMPT.format(
            fields=fields_str,
            jd=st.session_state.get("jd", ""),
            text=compact_grounding_context(analysis_ledger, analysis_matrix),
        )
        with st.spinner("Running expert analysis…"):
            analysis = _call_ai(prompt, task="analysis")

        if analysis:
            st.markdown(f"### 🧠 Expert Analysis — *{fields_str}*")
            _display_md(analysis)
            st.session_state["last_analysis"] = analysis
        st.session_state["do_analysis"] = False
        log_usage("expert_analysis", fields=fields_str)

    # ── Quick fix bullets ──────────────────────────────────────────────────────
    if st.session_state.get("do_quickfix"):
        jd_v = st.session_state.get("jd", "")
        res_v = st.session_state.get("resume", "")
        report = analyze_alignment(jd_v, res_v)
        requirements = top_requirement_text(report.job, limit=8)
        st.session_state["key_reqs"] = "\n".join(f"- {item}" for item in requirements)
        ledger = build_evidence_ledger(
            res_v, st.session_state.get("clarification_answers", {})
        )
        matrix = build_evidence_matrix(jd_v, ledger)
        grounding = achievement_grounding_context(ledger, matrix)

        fields_q = prefs.get("target_field", "").strip() or st.session_state.get("inferred_field", "General")
        fixes = ""
        if not grounding:
            st.error(
                "No experience, project, or confirmed clarification evidence was found. "
                "Achievement generation has been stopped because a JD alone is not evidence."
            )
        else:
            q_prompt = build_achievement_prompt(
                count=prefs.get("achievements_count", 4),
                key_requirements=st.session_state["key_reqs"],
                job_title=report.job.title or fields_q,
                achievement_evidence=grounding,
            )
            with st.spinner("Generating evidence-linked bullets…"):
                fixes = _call_ai(
                    q_prompt,
                    system_prompt=RESUME_WRITER_SYSTEM_PROMPT,
                    temperature=0.2,
                    task="rewrite",
                )
            if fixes:
                first_validation = validate_achievement_claims(
                    fixes, ledger, jd_v
                )
                refinement_prompt = build_achievement_refinement_prompt(
                    draft=fixes,
                    key_requirements=st.session_state["key_reqs"],
                    achievement_evidence=grounding,
                    count=prefs.get("achievements_count", 4),
                )
                with st.spinner(
                    "Checking evidence fit, JD relevance, and generic phrasing…"
                ):
                    refined_fixes = _call_ai(
                        refinement_prompt,
                        system_prompt=RESUME_WRITER_SYSTEM_PROMPT,
                        temperature=0.05,
                        task="rewrite",
                    )
                if refined_fixes:
                    refined_validation = validate_achievement_claims(
                        refined_fixes, ledger, jd_v
                    )
                    if _claim_validation_rank(
                        refined_validation
                    ) <= _claim_validation_rank(first_validation):
                        fixes = refined_fixes
                        first_validation = refined_validation

        if fixes:
            st.markdown("### ⚡ Evidence-Grounded Rewrite Candidates")
            validation = first_validation
            st.caption(
                "Two-pass review completed. Each candidate must cite a resume evidence ID; "
                "missing outcomes remain marked for verification."
            )
            if validation.is_download_safe:
                st.success(
                    f"Truth audit passed for {validation.supported_claims}/"
                    f"{validation.claims_checked} checked achievement claims."
                )
            else:
                st.error(
                    "Unsupported achievement content was detected. Do not copy these "
                    "bullets until the issues below are resolved."
                )
                with st.expander("Achievement truth-audit issues", expanded=True):
                    for issue in validation.issues:
                        st.markdown(
                            f"- **{issue.claim_id} · {issue.issue_type}:** {issue.detail}"
                        )
            _display_md(fixes)
            st.session_state["last_quickfix_validation"] = validation
        st.session_state["do_quickfix"] = False
        log_usage("quick_fix_bullets", fields=fields_q)

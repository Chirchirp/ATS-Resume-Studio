"""Evidence ledger, requirement coverage, clarification, and truth-audit UI."""

import hashlib

import streamlit as st

from utils.evidence_engine import (
    build_evidence_ledger,
    build_evidence_matrix,
    generate_clarification_questions,
    validate_generated_claims,
)


STATUS_LABELS = {
    "direct": "✅ Direct",
    "equivalent": "🟢 Equivalent",
    "transferable": "🟡 Transferable",
    "mention_only": "🟠 Mention only",
    "missing": "🔴 Missing",
}


def _current_evidence():
    resume = st.session_state.get("resume", "")
    jd = st.session_state.get("jd", "")
    base_hash = hashlib.sha256((resume + "\n" + jd).encode("utf-8")).hexdigest()[:16]
    previous_hash = st.session_state.get("clarification_source_hash", "")
    if previous_hash and previous_hash != base_hash:
        st.session_state["clarification_answers"] = {}
    st.session_state["clarification_source_hash"] = base_hash
    answers = st.session_state.get("clarification_answers", {})
    ledger = build_evidence_ledger(resume, answers)
    matrix = build_evidence_matrix(jd, ledger)
    st.session_state["evidence_ledger"] = ledger
    st.session_state["evidence_matrix"] = matrix
    st.session_state["resume_profile"] = ledger.profile
    return ledger, matrix


def render_tab_evidence():
    st.markdown(
        '<p class="section-label">🔐 Evidence & Truth Center</p>',
        unsafe_allow_html=True,
    )
    st.caption(
        "Inspect exactly what the application is allowed to claim. Candidate evidence—not the JD—is the source of truth."
    )

    if not st.session_state.get("resume", "").strip() or not st.session_state.get("jd", "").strip():
        st.info("Add both a job description and resume in the Analyze tab first.")
        return

    ledger, matrix = _current_evidence()
    questions = generate_clarification_questions(matrix, ledger)
    direct = sum(row.status in {"direct", "equivalent"} for row in matrix.rows)
    weak = sum(row.status in {"transferable", "mention_only"} for row in matrix.rows)

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Evidence items", len(ledger.items))
    m2.metric("Covered requirements", direct)
    m3.metric("Partial evidence", weak)
    m4.metric("Missing requirements", matrix.missing_count)

    profile = ledger.profile
    if profile:
        with st.expander("Structured Candidate Profile", expanded=True):
            s1, s2, s3, s4 = st.columns(4)
            s1.metric("Parsed roles", len(profile.roles))
            s2.metric(
                "Role bullets",
                sum(len(role.bullets) for role in profile.roles),
            )
            s3.metric("Declared skills", len(profile.declared_skills))
            s4.metric(
                "Education / credentials",
                len(profile.education_records)
                + len(profile.certification_records),
            )
            if profile.roles:
                st.dataframe(
                    [
                        {
                            "Role ID": role.id,
                            "Title": role.title or "Not separated",
                            "Employer": role.employer or "Not separated",
                            "Location": role.location or "—",
                            "Dates": role.date_text or "—",
                            "Bullets": len(role.bullets),
                            "Exact source header": role.header,
                        }
                        for role in profile.roles
                    ],
                    width="stretch",
                    hide_index=True,
                )
            if profile.declared_skills:
                st.caption(
                    "Declared skills: " + ", ".join(profile.declared_skills)
                )
            if profile.parse_warnings:
                for warning in profile.parse_warnings:
                    st.warning(warning)

    with st.expander("Candidate Evidence Ledger", expanded=True):
        st.caption(
            f"Ledger hash: {ledger.source_hash}. Clarification answers are marked user_confirmed."
        )
        rows = [
            {
                "ID": item.id,
                "Section": item.section,
                "Role": item.role,
                "Evidence": item.text,
                "Metrics": ", ".join(item.metrics),
                "Type": item.item_type,
                "Role ID": item.role_id,
                "Verification": item.verification,
            }
            for item in ledger.items
        ]
        st.dataframe(rows, width="stretch", hide_index=True)

    with st.expander("Requirement-to-Evidence Matrix", expanded=True):
        rows = [
            {
                "Requirement ID": row.id,
                "Priority": row.priority,
                "Coverage": STATUS_LABELS.get(row.status, row.status),
                "Requirement": row.requirement,
                "Evidence IDs": ", ".join(row.evidence_ids) or "—",
                "Missing terms": ", ".join(row.missing_terms) or "—",
            }
            for row in matrix.rows
        ]
        st.dataframe(rows, width="stretch", hide_index=True)
        st.caption(
            "A skills-section mention is not treated as equivalent to demonstrated experience."
        )

    with st.expander("Targeted Clarification Interview", expanded=bool(questions)):
        if not questions:
            st.success("No high-priority clarification questions remain.")
        else:
            st.write(
                "Answer only with facts you can defend in an interview. Blank answers are treated as no evidence."
            )
            existing = st.session_state.get("clarification_answers", {})
            with st.form(f"clarification_form_{ledger.source_hash}"):
                values = {}
                for question in questions:
                    st.markdown(f"**{question.id} · {question.reason}**")
                    values[question.id] = st.text_area(
                        question.prompt,
                        value=existing.get(question.id, ""),
                        height=100,
                        key=f"clarification_{ledger.source_hash}_{question.id}",
                    )
                submitted = st.form_submit_button(
                    "Save verified answers and rebuild evidence",
                    type="primary",
                    width="stretch",
                )
            if submitted:
                merged = dict(existing)
                for question_id, value in values.items():
                    if value.strip():
                        merged[question_id] = value.strip()
                    else:
                        merged.pop(question_id, None)
                st.session_state["clarification_answers"] = merged
                st.success("Evidence updated.")
                st.rerun()

            if existing and st.button(
                "Clear clarification answers",
                key="clear_clarifications",
            ):
                st.session_state["clarification_answers"] = {}
                st.rerun()

    with st.expander("Generated Document Truth Audit", expanded=False):
        generated = st.session_state.get("ideal_resume", "")
        if not generated:
            st.info("Generate an optimized resume to run its claim-level audit.")
        else:
            validation = validate_generated_claims(
                generated,
                ledger,
                st.session_state.get("jd", ""),
            )
            st.session_state["claim_validation"] = validation
            v1, v2, v3 = st.columns(3)
            v1.metric("Claims checked", validation.claims_checked)
            v2.metric("Clean claims", validation.supported_claims)
            v3.metric("Support rate", f"{validation.support_rate}%")
            if validation.is_download_safe:
                st.success("No high-severity unsupported claims were detected.")
            else:
                st.error(
                    "High-severity unsupported claims were detected. Resolve them before using this document."
                )
            if validation.issues:
                st.dataframe(
                    [
                        {
                            "Claim": issue.claim_id,
                            "Severity": issue.severity,
                            "Type": issue.issue_type,
                            "Detail": issue.detail,
                            "Text": issue.claim,
                        }
                        for issue in validation.issues
                    ],
                    width="stretch",
                    hide_index=True,
                )

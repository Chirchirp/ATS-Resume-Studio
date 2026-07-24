"""Phase 3 application workspace and career-positioning UI."""

from datetime import datetime, timezone

import streamlit as st

from utils.domain_profiles import domain_prompt_context, infer_domain_context
from utils.evidence_engine import build_evidence_ledger, build_evidence_matrix
from utils.workspace_engine import (
    DocumentVersion,
    build_interview_questions,
    build_positioning_strategies,
    build_recruiter_objections,
    compare_versions,
    create_document_version,
)


def _workspace_context():
    jd = st.session_state.get("jd", "")
    resume = st.session_state.get("resume", "")
    ledger = build_evidence_ledger(
        resume, st.session_state.get("clarification_answers", {})
    )
    matrix = build_evidence_matrix(jd, ledger)
    domain = infer_domain_context(jd + "\n" + resume)
    strategies = build_positioning_strategies(ledger, matrix, domain)
    st.session_state["domain_context"] = domain
    st.session_state["positioning_strategies"] = strategies
    return jd, resume, ledger, matrix, domain, strategies


def render_tab_workspace():
    st.markdown(
        '<p class="section-label">🗂️ Application Workspace</p>',
        unsafe_allow_html=True,
    )
    st.caption(
        "Choose a defensible positioning strategy, manage document versions, prepare for objections, and track outcomes."
    )
    if not st.session_state.get("jd", "").strip() or not st.session_state.get("resume", "").strip():
        st.info("Add both a job description and resume in Analyze to initialize this workspace.")
        return

    jd, resume, ledger, matrix, domain, strategies = _workspace_context()
    sector = ", ".join(domain.sector_signals) or "Cross-sector"
    st.info(
        f"**Career profile:** {domain.profile.label} · **Confidence:** {domain.confidence} · "
        f"**Sector context:** {sector}"
    )
    if domain.profile.id == "data_analytics":
        st.success(
            "Data Analytics specialization active: SQL/tool evidence, data quality, reporting, "
            "stakeholder translation, training, and verified decision impact receive additional emphasis."
        )

    sections = st.tabs(
        [
            "🎯 Positioning",
            "🧾 Versions & Impact",
            "🗣️ Interview & Objections",
            "🕶️ Blind Comparison",
            "📈 Outcomes",
        ]
    )

    with sections[0]:
        options = {strategy.name: strategy for strategy in strategies}
        current_id = st.session_state.get("selected_strategy_id", "direct_fit")
        current_name = next(
            (item.name for item in strategies if item.id == current_id),
            strategies[0].name,
        )
        selected_name = st.radio(
            "Resume positioning strategy",
            list(options),
            index=list(options).index(current_name),
            key="workspace_strategy_radio",
        )
        selected = options[selected_name]
        st.session_state["selected_strategy_id"] = selected.id
        st.markdown(f"**Thesis:** {selected.thesis}")
        st.markdown(f"**Best for:** {selected.best_for}")
        st.warning(f"**Integrity risk:** {selected.risk}")
        st.caption(
            "Priority evidence: "
            + (", ".join(selected.evidence_ids) if selected.evidence_ids else "No contextual evidence identified")
        )
        with st.expander("Domain writing guidance"):
            st.text(domain_prompt_context(domain))

    with sections[1]:
        versions: list[DocumentVersion] = list(
            st.session_state.get("document_versions", [])
        )
        optimized = st.session_state.get("ideal_resume", "")
        if optimized:
            selected_id = st.session_state.get("selected_strategy_id", "direct_fit")
            versions = create_document_version(
                versions,
                label=f"Optimized resume · {selected_id}",
                strategy_id=selected_id,
                text=optimized,
                jd_text=jd,
                ledger=ledger,
            )
            st.session_state["document_versions"] = versions

        if not versions:
            st.info("Generate an optimized resume to create the first managed version.")
        else:
            st.dataframe(
                [
                    {
                        "Version": version.id,
                        "Label": version.label,
                        "Strategy": version.strategy_id,
                        "Alignment": version.alignment_score,
                        "Claim support": f"{version.support_rate}%",
                        "Created UTC": version.created_at,
                    }
                    for version in versions
                ],
                width="stretch",
                hide_index=True,
            )
            selected_version_id = st.selectbox(
                "Preview version",
                [version.id for version in reversed(versions)],
                key="workspace_version_preview",
            )
            selected_version = next(
                version for version in versions if version.id == selected_version_id
            )
            st.text_area(
                "Version content",
                value=selected_version.text,
                height=360,
                disabled=True,
                key="workspace_version_content",
            )
            st.download_button(
                "Download selected version as text",
                data=selected_version.text.encode("utf-8"),
                file_name=f"{selected_version.id}_resume.txt",
                mime="text/plain",
                width="stretch",
            )

        if optimized:
            impact = compare_versions(resume, optimized, jd)
            i1, i2, i3, i4 = st.columns(4)
            i1.metric(
                "Alignment",
                f"{impact.optimized_score}%",
                delta=impact.optimized_score - impact.original_score,
            )
            i2.metric("Matched terms", "Change", delta=impact.matched_term_delta)
            i3.metric("Words", len(optimized.split()), delta=impact.word_delta)
            i4.metric("Numeric references", "Change", delta=impact.metric_delta)
            with st.expander("Change-impact report"):
                st.markdown("**Representative additions**")
                for line in impact.added_lines[:10]:
                    st.markdown(f"- {line}")
                st.markdown("**Representative removals**")
                for line in impact.removed_lines[:10]:
                    st.markdown(f"- {line}")

    with sections[2]:
        objections = build_recruiter_objections(matrix, ledger)
        st.markdown("#### Recruiter objection simulator")
        if not objections:
            st.success("No major evidence objections were detected.")
        for objection in objections:
            with st.expander(
                f"{objection.priority}: {objection.objection}",
                expanded=objection.priority == "Critical",
            ):
                st.markdown(f"**Current evidence response:** {objection.evidence_response}")
                st.markdown(f"**Preparation:** {objection.preparation}")

        st.markdown("#### Evidence-grounded interview pack")
        for index, question in enumerate(
            build_interview_questions(matrix, ledger, domain),
            start=1,
        ):
            st.markdown(f"**{index}. {question.question}**")
            st.caption(
                "Evidence: " + (", ".join(question.evidence_ids) or "Choose a verified example")
            )
            st.write(question.answer_plan)

    with sections[3]:
        optimized = st.session_state.get("ideal_resume", "")
        if not optimized:
            st.info("Generate an optimized resume to unlock blind comparison.")
        else:
            swap = int(ledger.source_hash[-1], 16) % 2 == 1
            version_a, version_b = (optimized, resume) if swap else (resume, optimized)
            a, b = st.columns(2)
            with a:
                st.markdown("**Version A**")
                st.text_area(
                    "Blind version A",
                    version_a,
                    height=360,
                    disabled=True,
                    label_visibility="collapsed",
                    key="blind_a",
                )
            with b:
                st.markdown("**Version B**")
                st.text_area(
                    "Blind version B",
                    version_b,
                    height=360,
                    disabled=True,
                    label_visibility="collapsed",
                    key="blind_b",
                )
            with st.form("blind_comparison_form"):
                choice = st.radio(
                    "Which version would you advance to interview?",
                    ["Version A", "Version B", "No preference"],
                    key="blind_choice",
                )
                reveal = st.form_submit_button("Lock choice and reveal")
            if reveal:
                preferred_optimized = (
                    (choice == "Version A" and swap)
                    or (choice == "Version B" and not swap)
                )
                st.session_state["blind_evaluations"] = list(
                    st.session_state.get("blind_evaluations", [])
                ) + [
                    {
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "choice": choice,
                        "optimized_selected": preferred_optimized,
                    }
                ]
                st.success(
                    f"Version {'A' if swap else 'B'} was the optimized resume. "
                    f"Your choice: {choice}."
                )

    with sections[4]:
        versions = st.session_state.get("document_versions", [])
        with st.form("application_outcome_form"):
            c1, c2 = st.columns(2)
            company = c1.text_input("Company")
            role = c2.text_input("Role", value=domain.profile.label)
            status = st.selectbox(
                "Current outcome",
                [
                    "Applied",
                    "Screening",
                    "Interview",
                    "Final interview",
                    "Offer",
                    "Rejected",
                    "Withdrawn",
                ],
            )
            version_id = st.selectbox(
                "Resume version",
                [version.id for version in versions] or ["Original"],
            )
            notes = st.text_area("Notes", height=80)
            add_outcome = st.form_submit_button(
                "Add application outcome",
                type="primary",
                width="stretch",
            )
        if add_outcome:
            records = list(st.session_state.get("application_outcomes", []))
            records.append(
                {
                    "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                    "company": company.strip(),
                    "role": role.strip(),
                    "status": status,
                    "version": version_id,
                    "notes": notes.strip(),
                }
            )
            st.session_state["application_outcomes"] = records
            st.success("Outcome recorded in this session.")

        outcomes = st.session_state.get("application_outcomes", [])
        if outcomes:
            o1, o2, o3 = st.columns(3)
            o1.metric("Applications", len(outcomes))
            o2.metric(
                "Interview progression",
                sum(item["status"] in {"Interview", "Final interview", "Offer"} for item in outcomes),
            )
            o3.metric("Offers", sum(item["status"] == "Offer" for item in outcomes))
            st.dataframe(outcomes, width="stretch", hide_index=True)


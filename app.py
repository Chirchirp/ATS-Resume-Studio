"""
app.py — ATS Resume Studio (Modular Edition)
Entry point: run with `streamlit run app.py`

Folder structure:
    app.py
    config/
        settings.py          API key & model config (no .env needed)
    components/
        sidebar.py           Sidebar with API key input
        tab_analyze.py       Analyze tab
        tab_premium.py       Premium Solutions tab
    prompts/
        templates.py         All prompt strings
    utils/
        ai_client.py         Multi-provider AI gateway
        docx_builder.py      DOCX export
        logger.py            CSV usage logging
        text_processing.py   PDF extraction, keyword match, sanitize
"""

import copy
import sys
import os

# Allow imports from the project root
sys.path.insert(0, os.path.dirname(__file__))

import streamlit as st

from components.sidebar import render_sidebar
from components.tab_analyze import render_tab_analyze
from components.tab_evidence import render_tab_evidence
from components.tab_premium import render_tab_premium
from components.tab_workspace import render_tab_workspace
from utils.auth import render_login_gate
from utils.logger import init_log_file
from utils.session_store import restore_workspace, save_workspace

# ──────────────────────────────────────────────────────────────
# Page config (must be first Streamlit call)
# ──────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="ATS Resume Studio",
    page_icon="📄",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ──────────────────────────────────────────────────────────────
# Global CSS
# ──────────────────────────────────────────────────────────────

st.markdown(
    """
    <style>
    /* ── Google Fonts ── */
    @import url('https://fonts.googleapis.com/css2?family=DM+Serif+Display&family=DM+Sans:wght@300;400;500;600;700&display=swap');

    /* ── Root variables ── */
    :root {
        --ink:        #0f1117;
        --ink-muted:  #4b5563;
        --accent:     #2563eb;
        --accent-lt:  #eff6ff;
        --success:    #16a34a;
        --warn:       #d97706;
        --danger:     #dc2626;
        --card-bg:    #ffffff;
        --page-bg:    #f1f5f9;
        --border:     #e2e8f0;
        --radius:     12px;
        --shadow:     0 2px 12px rgba(15,17,23,0.07);
    }

    /* ── Page background ── */
    .stApp {
        background: var(--page-bg);
        font-family: 'DM Sans', sans-serif;
    }

    /* ── Sidebar ── */
    section[data-testid="stSidebar"] {
        background: #0f1117 !important;
        border-right: 1px solid #1e2433;
    }
    section[data-testid="stSidebar"] * {
        color: #e2e8f0 !important;
    }
    section[data-testid="stSidebar"] .stButton button {
        background: #1e2433 !important;
        color: #e2e8f0 !important;
        border: 1px solid #2d3748 !important;
        border-radius: 8px !important;
    }
    section[data-testid="stSidebar"] .stButton button:hover {
        background: #2d3748 !important;
    }
    section[data-testid="stSidebar"] input,
    section[data-testid="stSidebar"] select,
    section[data-testid="stSidebar"] textarea {
        background: #1e2433 !important;
        border-color: #2d3748 !important;
        color: #e2e8f0 !important;
        border-radius: 8px !important;
    }
    section[data-testid="stSidebar"] .stSelectbox > div > div,
    section[data-testid="stSidebar"] div[data-baseweb="select"] > div {
        background: #1e2433 !important;
        color: #e2e8f0 !important;
        border-color: #334155 !important;
        box-shadow: none !important;
    }
    section[data-testid="stSidebar"] div[data-baseweb="select"] span,
    section[data-testid="stSidebar"] div[data-baseweb="select"] svg {
        color: #e2e8f0 !important;
        fill: #e2e8f0 !important;
    }
    section[data-testid="stSidebar"] [data-testid="stCheckbox"] label {
        background: transparent !important;
    }
    section[data-testid="stSidebar"] label[data-baseweb="checkbox"] > span:first-child,
    section[data-testid="stSidebar"] label[data-baseweb="checkbox"] > span:first-child > div,
    section[data-testid="stSidebar"] [data-testid="stCheckbox"]
        label[data-react-aria-pressable="true"] > div:first-of-type {
        background: #1e2433 !important;
        border: 1px solid #64748b !important;
    }
    section[data-testid="stSidebar"] label[data-baseweb="checkbox"] input:checked + div {
        background: #2563eb !important;
        border-color: #60a5fa !important;
    }
    section[data-testid="stSidebar"] [data-testid="stCheckbox"]
        label[data-react-aria-pressable="true"]:has(input:checked) > div:first-of-type {
        background: #2563eb !important;
        border-color: #60a5fa !important;
    }
    section[data-testid="stSidebar"] [data-testid="stTextInput"] > div > div {
        background: #1e2433 !important;
        border-color: #334155 !important;
    }
    section[data-testid="stSidebar"] [data-testid="stTextInput"] input::placeholder {
        color: #94a3b8 !important;
        opacity: 1 !important;
    }
    section[data-testid="stSidebar"] label,
    section[data-testid="stSidebar"] .stMarkdown p,
    section[data-testid="stSidebar"] .stMarkdown h2,
    section[data-testid="stSidebar"] .stMarkdown h4 {
        color: #94a3b8 !important;
    }
    section[data-testid="stSidebar"] .stSlider .st-emotion-cache-1inwz65 {
        color: #e2e8f0 !important;
    }
    section[data-testid="stSidebar"] code {
        background: #172033 !important;
        color: #93c5fd !important;
        border: 1px solid #334155 !important;
    }
    section[data-testid="stSidebar"] .stExpander,
    section[data-testid="stSidebar"] [data-testid="stExpander"] {
        background: #151b29 !important;
        border-color: #334155 !important;
        box-shadow: none !important;
    }
    section[data-testid="stSidebar"] .stExpander details,
    section[data-testid="stSidebar"] .stExpander summary,
    section[data-testid="stSidebar"] [data-testid="stExpanderDetails"] {
        background: #151b29 !important;
        color: #e2e8f0 !important;
    }
    section[data-testid="stSidebar"] .stExpander summary:hover {
        background: #1e293b !important;
    }

    /* BaseWeb mounts select menus outside the sidebar. Keep the opened menu
       consistent with the dark navigation surface and preserve contrast. */
    div[data-baseweb="popover"] ul,
    div[data-baseweb="popover"] [role="listbox"] {
        background: #1e2433 !important;
        border: 1px solid #334155 !important;
    }
    div[data-baseweb="popover"] li[role="option"] {
        background: #1e2433 !important;
        color: #e2e8f0 !important;
    }
    div[data-baseweb="popover"] li[role="option"]:hover,
    div[data-baseweb="popover"] li[role="option"][aria-selected="true"] {
        background: #334155 !important;
        color: #ffffff !important;
    }
    [data-testid="stSelectboxVirtualDropdown"],
    [data-testid="stSelectboxVirtualDropdown"] [role="listbox"] {
        background: #1e2433 !important;
        border-color: #334155 !important;
        color: #e2e8f0 !important;
    }
    [data-testid="stSelectboxVirtualDropdown"] [role="option"],
    [data-testid="stSelectboxVirtualDropdown"] [data-item-hl] {
        background: #1e2433 !important;
        color: #e2e8f0 !important;
    }
    [data-testid="stSelectboxVirtualDropdown"] [role="option"]:hover,
    [data-testid="stSelectboxVirtualDropdown"] [role="option"][aria-selected="true"],
    [data-testid="stSelectboxVirtualDropdown"] [role="option"][data-focused="true"] {
        background: #334155 !important;
        color: #ffffff !important;
    }

    /* ── Main header ── */
    .studio-header {
        background: linear-gradient(135deg, #0f1117 0%, #1e3a5f 60%, #2563eb 100%);
        padding: 36px 40px;
        border-radius: var(--radius);
        margin-bottom: 24px;
        position: relative;
        overflow: hidden;
    }
    .studio-header::before {
        content: '';
        position: absolute;
        top: -60px; right: -60px;
        width: 260px; height: 260px;
        border-radius: 50%;
        background: rgba(37,99,235,0.18);
    }
    .studio-header::after {
        content: '';
        position: absolute;
        bottom: -80px; left: -40px;
        width: 200px; height: 200px;
        border-radius: 50%;
        background: rgba(37,99,235,0.10);
    }
    .studio-header h1 {
        font-family: 'DM Serif Display', serif;
        font-size: 36px;
        color: #ffffff;
        margin: 0 0 6px 0;
        position: relative;
        z-index: 1;
    }
    .studio-header p {
        font-size: 15px;
        color: #94a3b8;
        margin: 0;
        position: relative;
        z-index: 1;
    }
    .studio-header .badge-row {
        display: flex;
        gap: 8px;
        margin-top: 16px;
        position: relative;
        z-index: 1;
        flex-wrap: wrap;
    }
    .badge {
        background: rgba(255,255,255,0.12);
        color: #cbd5e1;
        font-size: 12px;
        padding: 4px 10px;
        border-radius: 20px;
        border: 1px solid rgba(255,255,255,0.15);
        backdrop-filter: blur(4px);
    }

    /* ── Tab bar ── */
    .stTabs [data-baseweb="tab-list"] {
        background: transparent;
        gap: 4px;
        border-bottom: 2px solid var(--border);
        padding-bottom: 0;
    }
    .stTabs [data-baseweb="tab"] {
        font-family: 'DM Sans', sans-serif;
        font-weight: 600;
        font-size: 15px;
        padding: 10px 20px;
        border-radius: 8px 8px 0 0;
        color: var(--ink-muted);
        background: transparent;
    }
    .stTabs [aria-selected="true"] {
        color: var(--accent) !important;
        background: var(--card-bg) !important;
        border: 1px solid var(--border);
        border-bottom: 2px solid var(--card-bg);
        margin-bottom: -2px;
    }

    /* ── Cards / expanders ── */
    .stExpander {
        background: var(--card-bg);
        border: 1px solid var(--border) !important;
        border-radius: var(--radius) !important;
        box-shadow: var(--shadow);
        margin-bottom: 14px;
    }
    .stExpander summary {
        font-weight: 600 !important;
        font-size: 15px !important;
        color: var(--ink) !important;
        padding: 14px 16px !important;
    }

    /* ── Section labels ── */
    .section-label {
        font-family: 'DM Serif Display', serif;
        font-size: 22px;
        color: var(--ink);
        margin: 0 0 4px 0;
    }

    /* ── Buttons ── */
    .stButton button {
        font-family: 'DM Sans', sans-serif;
        font-weight: 600;
        border-radius: 8px !important;
        transition: all 0.18s ease;
    }
    .stButton button[kind="primary"] {
        background: var(--accent) !important;
        border-color: var(--accent) !important;
        color: #fff !important;
    }
    .stButton button[kind="primary"]:hover {
        background: #1d4ed8 !important;
        transform: translateY(-1px);
        box-shadow: 0 4px 12px rgba(37,99,235,0.3);
    }
    .stButton button:not([kind="primary"]):hover {
        border-color: var(--accent) !important;
        color: var(--accent) !important;
        transform: translateY(-1px);
    }

    /* ── Inputs ── */
    .stTextArea textarea,
    .stTextInput input {
        border-radius: 8px !important;
        border: 1.5px solid var(--border) !important;
        font-family: 'DM Sans', sans-serif !important;
        font-size: 14px !important;
        transition: border-color 0.18s;
    }
    .stTextArea textarea:focus,
    .stTextInput input:focus {
        border-color: var(--accent) !important;
        box-shadow: 0 0 0 3px rgba(37,99,235,0.12) !important;
    }

    /* ── Metrics ── */
    [data-testid="metric-container"] {
        background: var(--card-bg);
        border: 1px solid var(--border);
        border-radius: 10px;
        padding: 12px 16px;
    }

    /* ── Download buttons ── */
    .stDownloadButton button {
        font-weight: 600;
        border-radius: 8px !important;
        width: 100%;
    }

    /* ── Footer ── */
    .studio-footer {
        text-align: center;
        padding: 24px 0 12px 0;
        color: var(--ink-muted);
        font-size: 13px;
        border-top: 1px solid var(--border);
        margin-top: 32px;
    }

    /* ── Progress bar ── */
    .stProgress > div > div {
        background: linear-gradient(90deg, #2563eb, #06b6d4) !important;
        border-radius: 99px !important;
    }

    /* ── Info / warning / success boxes ── */
    .stAlert {
        border-radius: 10px !important;
    }

    /* ── Dividers ── */
    hr {
        border-color: var(--border) !important;
    }

    /* ── File uploader ── */
    [data-testid="stFileUploader"] {
        border-radius: 10px !important;
    }

    /* ── Form submit button ── */
    .stFormSubmitButton button {
        font-weight: 700;
        font-size: 15px;
        padding: 12px 24px;
        border-radius: 8px !important;
    }

    /* ── Selectbox ── */
    .stSelectbox > div > div {
        border-radius: 8px !important;
        border: 1.5px solid var(--border) !important;
    }

    /* ── Spinner ── */
    .stSpinner > div {
        border-top-color: var(--accent) !important;
    }

    /* ── API key hint box ── */
    .api-hint {
        background: var(--accent-lt);
        border: 1px solid #bfdbfe;
        border-radius: 10px;
        padding: 14px 16px;
        margin-bottom: 18px;
        font-size: 14px;
        color: #1e3a5f;
    }
    .api-hint strong { color: var(--accent); }

    /* mobile adjustments */
    @media (max-width: 768px) {
        .studio-header { padding: 20px; }
        .studio-header h1 { font-size: 24px; }
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# ──────────────────────────────────────────────────────────────
# Authentication gate
# ──────────────────────────────────────────────────────────────

if not render_login_gate():
    st.stop()

# A signed browser workspace ID lets a replacement Streamlit session recover the
# user's authored inputs and generated documents. Provider API keys are excluded.
restore_workspace(st.session_state)

# ──────────────────────────────────────────────────────────────
# Session state defaults
# ──────────────────────────────────────────────────────────────

DEFAULTS = {
    "jd": "",
    "resume": "",
    "inferred_field": "",
    "last_match": None,
    "last_analysis": "",
    "do_analysis": False,
    "do_quickfix": False,
    "usage_count": 0,
    "recent_usage": [],
    "premium_tools_output": {},
    "premium_resume_output": {},
    "premium_cover_output": {},
    "premium_custom_output": "",
    "ideal_resume": "",
    "key_reqs": "",
    "groq_api_key": "",
    "provider_api_keys": {},
    "clarification_answers": {},
    "resume_profile": None,
    "evidence_ledger": None,
    "evidence_matrix": None,
    "claim_validation": None,
    "ai_input_tokens": 0,
    "ai_output_tokens": 0,
    "ai_cached_tokens": 0,
    "last_ai_call": {},
    "domain_context": None,
    "positioning_strategies": [],
    "selected_strategy_id": "direct_fit",
    "document_versions": [],
    "blind_evaluations": [],
    "application_outcomes": [],
}

for k, v in DEFAULTS.items():
    if k not in st.session_state:
        st.session_state[k] = copy.deepcopy(v)

# ──────────────────────────────────────────────────────────────
# Init log file
# ──────────────────────────────────────────────────────────────

init_log_file()

# ──────────────────────────────────────────────────────────────
# Sidebar
# ──────────────────────────────────────────────────────────────

prefs = render_sidebar()

# ──────────────────────────────────────────────────────────────
# Header
# ──────────────────────────────────────────────────────────────

st.markdown(
    """
    <div class="studio-header">
        <h1>📄 ATS Resume Studio</h1>
        <p>Evidence-grounded resume analysis &amp; generation for any profession — Created by Pharaoh Chirchir</p>
        <div class="badge-row">
            <span class="badge">⚡ Explainable Job Alignment</span>
            <span class="badge">🔐 Claim Truth Audit</span>
            <span class="badge">🧠 Expert AI Analysis</span>
            <span class="badge">✉️ Cover Letter Gen</span>
            <span class="badge">📥 DOCX Export</span>
            <span class="badge">🌐 Universal — Any Field</span>
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)

# API key prompt banner (shown when key not set)
if not prefs["api_ready"]:
    provider_label = prefs.get("provider", "groq").title()
    st.markdown(
        f"""
        <div class="api-hint">
            🔑 <strong>Getting started:</strong> Configure a {provider_label} API key in the sidebar.
            Keys can also be supplied through Streamlit secrets or environment variables.
        </div>
        """,
        unsafe_allow_html=True,
    )

# ──────────────────────────────────────────────────────────────
# Main tabs
# ──────────────────────────────────────────────────────────────

tab_analyze, tab_evidence, tab_workspace, tab_premium, tab_help = st.tabs(
    [
        "🔍 Analyze",
        "🔐 Evidence & Truth",
        "🗂️ Application Workspace",
        "💎 Premium Solutions",
        "❓ How It Works",
    ]
)

with tab_analyze:
    render_tab_analyze(prefs)

with tab_evidence:
    render_tab_evidence()

with tab_workspace:
    render_tab_workspace()

with tab_premium:
    render_tab_premium(prefs)

with tab_help:
    st.markdown(
        """
        ## How to Use ATS Resume Studio

        ### Step 1 — Select a provider
        Choose **Groq**, **Google Gemini**, or **OpenRouter** in the sidebar and configure its key.
        Keys are held in server-side session state unless supplied through Streamlit secrets or environment variables.

        ---

        ### Step 2 — Go to the Analyze tab
        - **Upload your PDF resume** or paste it as text.
        - Start with **Resume Quality Review** to check structure, grammar, date consistency,
          possible career gaps, and ATS readability without needing a Job Description.
        - **Paste the Job Description** when you are ready to compare the resume with a target role.
        - Hit **Quick Keyword Match** to see an explainable Job Alignment Score with its calculation breakdown.
        - Hit **Run Expert Analysis** for a full AI-powered evaluation including strengths, weaknesses, rewrite suggestions, and your one-minute pitch.
        - Hit **Quick Fix Bullets** to generate bullet points that fill your keyword gaps.

        ---

        ### Step 3 — Verify evidence
        Use **Evidence & Truth** to inspect candidate evidence IDs, requirement coverage,
        and targeted clarification questions. Only add answers you can defend in an interview.

        ---

        ### Step 4 — Select your positioning
        Use **Application Workspace** to choose direct-fit, verified-impact, or
        transferable-growth positioning. The detected career profile adds domain guidance
        while preserving a universal fallback for other professions.

        ---

        ### Step 5 — Generate Premium Outputs
        Switch to the **Premium Solutions** tab:

        | Feature | What it does |
        |---|---|
        | 📊 Job Alignment Score | Transparent evidence-based scoring; not a claim to reproduce one ATS vendor |
        | 🎯 Recruiter Feedback | "Sarah Chen" gives brutally honest scored feedback |
        | 📄 Resume Generation | Full ATS-optimized resume built from yours + the JD |
        | ✉️ Cover Letter | Concise, tone-matched cover letter |
        | 💬 Custom Query | Ask any specific question about your fit |

        The workspace also provides document version history, change-impact reporting,
        recruiter objections, interview preparation, blind resume comparison, and
        session-based application outcome tracking.

        ---

        ### Tips for Best Results
        - Paste the **full** job description, not just the title.
        - Use your **complete** resume text for best tailoring.
        - Set a **Target Field** in the sidebar if the JD is short or generic.
        - Download the **DOCX** for a formatted, ATS-ready document.

        ---

        ### Privacy Note
        Your resume and job description are held in the app's server-side Streamlit session and
        in an encrypted recovery snapshot for this signed browser workspace. API keys are never
        written to the recovery snapshot. Your content is sent to your **selected AI provider**
        when you use an AI feature. Basic action metadata is written to
        a local usage log; resume and job-description text are not included in that log.
        Review your hosting setup and each provider's data terms before processing sensitive information.
        """
    )

# ──────────────────────────────────────────────────────────────
# Footer
# ──────────────────────────────────────────────────────────────

st.markdown(
    """
    <div class="studio-footer">
        ATS Resume Studio · Evidence-grounded multi-provider AI · 
        Resume text is processed in your server session and by your selected provider for AI actions
    </div>
    """,
    unsafe_allow_html=True,
)

# Save only when recoverable content changed, avoiding a database write on every
# Streamlit rerun while still capturing ordinary text edits and generated outputs.
try:
    save_workspace(st.session_state)
except (OSError, ValueError):
    # Recovery must never interrupt resume work. The sidebar will continue to show
    # the last successful save time when storage is temporarily unavailable.
    pass

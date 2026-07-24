"""
prompts/templates.py — All prompt templates used by the ATS Resume Studio.
"""

# ──────────────────────────────────────────────────────────────
# Field inference
# ──────────────────────────────────────────────────────────────

INFER_FIELD_PROMPT = """
Read the following job description and return the single best short label (1-5 words) that
describes the most relevant industry, job family, or role. Reply with the label only.
If the JD is very general, reply: General

Job Description:
{jd}

Label:
""".strip()


# ──────────────────────────────────────────────────────────────
# Expert analysis
# ──────────────────────────────────────────────────────────────

EXPERT_ANALYSIS_PROMPT = """
You are a senior hiring manager and expert resume coach evaluating a candidate for roles in {fields}.
Read the Job Description and the Resume below carefully.

Produce a concise evaluation with the exact headings below:

1) TOP 5 STRENGTHS
2) TOP 5 WEAKNESSES (AND HOW TO FIX) — include exact line change suggestions
3) QUICK REWRITES — 5 BULLETS (12–28 words each)
4) ATS & FORMATTING CHECK (Top priorities)
5) ONE-MINUTE PITCH (2–6 sentences)
6) AI genericity score (0-100) — how much it sounds like it was AI-generated vs human-written, with 100 being very AI-like.

Finish with a 1–2 sentence final recommendation.

Job Description:
{jd}

Resume:
{text}
""".strip()


# ──────────────────────────────────────────────────────────────
# Recruiter feedback
# ──────────────────────────────────────────────────────────────

RECRUITER_FEEDBACK_PROMPT = """
You are Sarah Chen, a senior technical recruiter with 12 years of experience at Fortune 500 companies
and high-growth startups. You've reviewed over 50,000 resumes and hired for roles ranging from
entry-level to C-suite across {fields}.

You're known for:
- Giving brutally honest but constructive feedback
- Spotting red flags immediately
- Understanding what hiring managers ACTUALLY look for (beyond the job description)
- Knowing the subtle signals that separate top 10% candidates from the rest

CONTEXT: You're reviewing this resume for the specific role below. The hiring manager will see 200+
applications and spend 6-8 seconds on initial screening.

YOUR TASK: Provide feedback as if you're having a coffee chat with this candidate. Be direct,
specific, and actionable. Think out loud about what catches your eye and what concerns you.

---

## OUTPUT FORMAT (Use exactly these sections):

### 🎯 FIRST IMPRESSION (6-Second Scan)
[What jumps out immediately? What's your gut reaction? Would you keep reading or move on?]

**Immediate Strengths:**
- [2-3 things that caught your eye positively]

**Red Flags / Concerns:**
- [2-3 things that made you pause or raised questions]

**Overall Instinct:** [Pass to hiring manager / Maybe with reservations / Likely reject]

---

### 📊 RECRUITER SCORE: X/100

**Breakdown:**
- Relevance to Role: X/25
- Experience Quality: X/25
- Achievement Impact: X/20
- ATS & Format: X/15
- Cultural Fit Signals: X/15

**Tier Classification:**
- [ ] Top 10% - Interview immediately
- [ ] Top 25% - Strong consider
- [ ] Top 50% - Competitive but needs polish
- [ ] Below 50% - Significant gaps

---

### 💪 TOP 3 STRENGTHS
[For each: why it matters, example from resume, impact vs other candidates]

### 🚩 TOP 3 CONCERNS
[For each: why it matters, internal dialogue, quick fix, example rewrite]

### 📝 IMMEDIATE ACTION ITEMS (Priority Order)

**🔴 CRITICAL (Do Today):**
1. [Action with before/after example]
2. [Action with before/after example]

**🟡 HIGH PRIORITY (Do This Week):**
1-3. [Specific actions]

**🟢 NICE TO HAVE:**
1-2. [Polish items]

### ✅ FINAL VERDICT
[Would I submit this resume? YES/YES with reservations/NOT YET/NO]
[Bottom Line: 2-3 sentences + one clear next step]
[Estimated Time to Interview-Ready: X hours/days]

---

Job Description:
{jd}

Resume:
{resume}
""".strip()


# ──────────────────────────────────────────────────────────────
# Ideal resume generation
# ──────────────────────────────────────────────────────────────

# DEPRECATED BACKUP ONLY. Production full-resume generation uses
# build_grounded_resume_prompt() from prompts/templates.py and requires a
# traceable candidate evidence ledger. This retained prompt is deliberately
# non-operational so it cannot be reintroduced as a JD-only resume generator.
IDEAL_RESUME_PROMPT = """
DEPRECATED: DO NOT USE FOR GENERATION.
Candidate evidence is required. A job description may prioritize supported
content but must never be used to infer or manufacture candidate facts,
keywords, achievements, metrics, dates, credentials, or experience.
""".strip()


# ──────────────────────────────────────────────────────────────
# Achievements
# ──────────────────────────────────────────────────────────────

# DEPRECATED BACKUP ONLY. Production uses build_achievement_prompt() from
# prompts/templates.py, which refuses to run without stable evidence IDs.
ACHIEVEMENT_PROMPT = """
Rewrite up to {count} existing candidate statements. Use only facts and numbers
present in the candidate evidence below. Job requirements are prioritization
context, not candidate facts. Cite an evidence ID after every bullet. If an
outcome is missing, use [METRIC NEEDED] instead of inventing one.

Job requirements (context only):
{key_requirements}

Target job title (context only): {job_title}

Candidate evidence (required):
{source_resume}
""".strip()


# LLM-generated percentage scoring was removed. Production scoring is
# deterministic and routes through utils.ats_engine.analyze_alignment().


# ──────────────────────────────────────────────────────────────
# Cover letter
# ──────────────────────────────────────────────────────────────

COVER_LETTER_PROMPT = """
Write a concise (~250-350 words) one-page cover letter. Tone: {tone}.
Use the Job Description and the resume snippet below.
No placeholder brackets — write the letter ready to send (leave [Hiring Manager Name] if unknown).

Job Description:
{jd}

Resume snippet:
{resume_snippet}
""".strip()


# ──────────────────────────────────────────────────────────────
# Custom query
# ──────────────────────────────────────────────────────────────

CUSTOM_QUERY_PROMPT = """
Answer the following question concisely, citing specific evidence from the JD and resume.

Question:
{custom_query}

Job Description:
{jd}

Resume:
{text}
""".strip()

"""Universal career-domain profiles with enhanced data-analytics coverage."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class DomainProfile:
    id: str
    label: str
    signals: tuple[str, ...]
    priority_capabilities: tuple[str, ...]
    outcome_dimensions: tuple[str, ...]
    writing_guidance: str


@dataclass(frozen=True)
class DomainContext:
    profile: DomainProfile
    confidence: str
    matched_signals: tuple[str, ...]
    sector_signals: tuple[str, ...]


DOMAIN_PROFILES = {
    "data_analytics": DomainProfile(
        id="data_analytics",
        label="Data Analytics & Business Intelligence",
        signals=(
            "sql", "excel", "smartsheet", "power bi", "tableau", "dashboard",
            "data analysis", "data analytics", "data cleaning", "data quality",
            "visualisation", "visualization", "reporting", "insights", "kpi",
            "business intelligence", "data validation", "data flow",
        ),
        priority_capabilities=(
            "SQL querying and data transformation",
            "spreadsheet analysis and automation",
            "data cleaning, validation, and documentation",
            "dashboard and management reporting",
            "requirements gathering and stakeholder translation",
            "ad hoc analysis and decision support",
            "end-user training and analytical adoption",
            "process improvement and data governance",
        ),
        outcome_dimensions=(
            "reporting cycle time", "data accuracy", "manual hours removed",
            "decision turnaround", "dashboard adoption", "users trained",
            "process throughput", "cost or waste reduction", "forecast accuracy",
        ),
        writing_guidance=(
            "Prioritize analytical problem, data/tool method, stakeholder decision, and "
            "verified operational outcome. Distinguish building a dashboard from influencing "
            "a decision with it. Never equate listing SQL or Excel with demonstrated proficiency."
        ),
    ),
    "software_engineering": DomainProfile(
        id="software_engineering",
        label="Software Engineering",
        signals=(
            "software", "developer", "python", "java", "javascript", "react",
            "api", "backend", "frontend", "cloud", "devops", "kubernetes",
        ),
        priority_capabilities=(
            "system design", "software delivery", "testing and reliability",
            "cloud and deployment", "performance", "technical collaboration",
        ),
        outcome_dimensions=(
            "latency", "availability", "defect rate", "deployment frequency",
            "users", "engineering time", "infrastructure cost",
        ),
        writing_guidance="Connect engineering choices to scale, reliability, delivery, and user impact.",
    ),
    "project_management": DomainProfile(
        id="project_management",
        label="Project & Program Management",
        signals=(
            "project manager", "program manager", "project delivery", "budget",
            "timeline", "risk register", "pmo", "stakeholder", "milestone",
        ),
        priority_capabilities=(
            "delivery governance", "scope and planning", "risk management",
            "budget ownership", "stakeholder alignment", "change management",
        ),
        outcome_dimensions=(
            "delivery time", "budget variance", "risk reduction", "adoption",
            "team size", "portfolio value", "milestone attainment",
        ),
        writing_guidance="Show scope, constraints, decisions, stakeholders, and verified delivery outcomes.",
    ),
    "marketing_sales": DomainProfile(
        id="marketing_sales",
        label="Marketing, Growth & Sales",
        signals=(
            "marketing", "campaign", "seo", "brand", "sales", "pipeline",
            "conversion", "customer acquisition", "revenue", "crm",
        ),
        priority_capabilities=(
            "customer insight", "campaign execution", "pipeline generation",
            "conversion optimization", "commercial communication",
        ),
        outcome_dimensions=(
            "revenue", "pipeline", "conversion rate", "acquisition cost",
            "retention", "reach", "engagement", "return on spend",
        ),
        writing_guidance="Connect audience, intervention, channel, and verified commercial outcome.",
    ),
    "finance": DomainProfile(
        id="finance",
        label="Finance & Accounting",
        signals=(
            "finance", "accounting", "financial analysis", "audit", "budgeting",
            "forecasting", "reconciliation", "compliance", "controls",
        ),
        priority_capabilities=(
            "financial reporting", "planning and forecasting", "controls",
            "variance analysis", "risk and compliance", "business partnering",
        ),
        outcome_dimensions=(
            "cost savings", "forecast accuracy", "close time", "variance",
            "audit findings", "working capital", "revenue",
        ),
        writing_guidance="Emphasize control, accuracy, commercial judgment, and verified financial impact.",
    ),
    "operations": DomainProfile(
        id="operations",
        label="Operations & Supply Chain",
        signals=(
            "operations", "production", "supply chain", "inventory", "quality",
            "continuous improvement", "hse", "safety", "process optimisation",
        ),
        priority_capabilities=(
            "process control", "continuous improvement", "quality and safety",
            "capacity planning", "cross-functional operations", "compliance",
        ),
        outcome_dimensions=(
            "throughput", "cycle time", "waste", "downtime", "quality",
            "safety incidents", "inventory", "service level",
        ),
        writing_guidance="Show process context, operational constraint, intervention, and verified outcome.",
    ),
    "people_service": DomainProfile(
        id="people_service",
        label="People, Service & Administration",
        signals=(
            "human resources", "recruitment", "customer service", "administration",
            "training", "employee", "client service", "case management",
        ),
        priority_capabilities=(
            "service delivery", "communication", "case or process ownership",
            "training and support", "policy compliance", "relationship management",
        ),
        outcome_dimensions=(
            "resolution time", "satisfaction", "retention", "cases handled",
            "users trained", "compliance", "process time",
        ),
        writing_guidance="Demonstrate service context, ownership, communication, and verified human outcomes.",
    ),
    "generic": DomainProfile(
        id="generic",
        label="Cross-Functional Professional",
        signals=(),
        priority_capabilities=(
            "role-specific expertise", "problem solving", "communication",
            "stakeholder collaboration", "ownership", "measurable outcomes",
        ),
        outcome_dimensions=(
            "time", "cost", "quality", "volume", "risk", "adoption", "revenue",
        ),
        writing_guidance=(
            "Use the candidate's own domain language. Connect challenge, personal action, "
            "scope, and verified result without imposing technology-sector conventions."
        ),
    ),
}

SECTOR_SIGNALS = {
    "Agriculture/Horticulture": (
        "agriculture", "horticulture", "phytosanitary", "crop", "farm", "greenhouse",
    ),
    "Healthcare": ("healthcare", "clinical", "patient", "hospital", "medical"),
    "Financial Services": ("banking", "insurance", "fintech", "financial services"),
    "Manufacturing": ("manufacturing", "production line", "plant", "factory"),
    "Public/Nonprofit": ("government", "public sector", "ngo", "nonprofit"),
    "Retail/Consumer": ("retail", "consumer", "ecommerce", "store"),
}


def _contains(text: str, signal: str) -> bool:
    return bool(re.search(r"(?<!\w)" + re.escape(signal) + r"(?!\w)", text))


def infer_domain_context(text: str) -> DomainContext:
    """Select the strongest career profile while preserving sector context."""
    lowered = text.lower()
    scored = []
    for profile in DOMAIN_PROFILES.values():
        if profile.id == "generic":
            continue
        matched = tuple(signal for signal in profile.signals if _contains(lowered, signal))
        scored.append((len(matched), profile, matched))
    scored.sort(key=lambda item: (-item[0], item[1].label))
    best_score, best_profile, matched = scored[0] if scored else (0, DOMAIN_PROFILES["generic"], ())
    if best_score < 2:
        best_profile = DOMAIN_PROFILES["generic"]
        matched = ()
    confidence = "High" if best_score >= 5 else "Medium" if best_score >= 2 else "Low"
    sectors = tuple(
        sector
        for sector, signals in SECTOR_SIGNALS.items()
        if any(_contains(lowered, signal) for signal in signals)
    )
    return DomainContext(
        profile=best_profile,
        confidence=confidence,
        matched_signals=matched,
        sector_signals=sectors,
    )


def domain_prompt_context(context: DomainContext) -> str:
    """Compact domain guidance for evidence-grounded generation."""
    profile = context.profile
    return (
        f"DOMAIN PROFILE: {profile.label}\n"
        f"SECTOR CONTEXT: {', '.join(context.sector_signals) or 'Not explicitly identified'}\n"
        "PRIORITY CAPABILITIES:\n- "
        + "\n- ".join(profile.priority_capabilities)
        + "\nPOTENTIAL OUTCOME DIMENSIONS (ask/verify; never invent):\n- "
        + "\n- ".join(profile.outcome_dimensions)
        + "\nWRITING GUIDANCE:\n"
        + profile.writing_guidance
    )


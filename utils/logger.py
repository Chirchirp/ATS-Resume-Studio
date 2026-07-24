"""
utils/logger.py — Session-based usage logging (CSV + session state).
"""

import csv
import logging
from datetime import datetime, timezone
from pathlib import Path

import streamlit as st

LOGGER = logging.getLogger(__name__)
LOG_FILE = Path(__file__).resolve().parent.parent / "usage_logs.csv"


def init_log_file():
    """Create the CSV log file with headers if it doesn't exist."""
    if not LOG_FILE.exists():
        try:
            with LOG_FILE.open("w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(["timestamp_utc", "action", "fields", "job_title", "status"])
        except OSError as exc:
            LOGGER.warning("Could not initialize usage log: %s", exc)


def log_usage(action: str, fields: str = "", job_title: str = "", status: str = "ok"):
    """Append a usage row to the CSV and update session state counters."""
    ts = datetime.now(timezone.utc).isoformat()
    try:
        with LOG_FILE.open("a", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow([ts, action, fields, job_title, status])
    except OSError as exc:
        LOGGER.warning("Could not append usage log: %s", exc)

    st.session_state["usage_count"] = st.session_state.get("usage_count", 0) + 1
    st.session_state["last_action"] = action
    logs = st.session_state.get("recent_usage", [])
    logs.insert(0, (ts, action, fields, job_title, status))
    st.session_state["recent_usage"] = logs[:50]

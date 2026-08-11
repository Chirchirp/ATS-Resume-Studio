"""Tiny trusted Streamlit v2 component for a signed browser session token."""

from __future__ import annotations

import streamlit as st


_STORAGE_JS = r"""
export default function({ data, setStateValue }) {
    const operation = data?.operation ?? "get";
    const storageKey = data?.storageKey ?? "";
    const suppliedValue = data?.value ?? "";
    const restoreRequestId = globalThis.crypto?.randomUUID?.() ??
        `${Date.now()}-${Math.random().toString(36).slice(2)}`;
    let value = "";

    const acceptParentRestore = (event) => {
        if (event.data?.type !== "ats-session-restore") return;
        // Streamlit can nest this component below its runtime iframe. Match the
        // one-time request nonce instead of assuming the Cloudflare shell is
        // this window's immediate parent.
        if (event.data?.requestId !== restoreRequestId) return;
        const restored = String(event.data?.token ?? "");
        if (!restored) return;
        try { window.localStorage.setItem(storageKey, restored); } catch (_error) {}
        setStateValue("value", restored);
    };
    window.addEventListener("message", acceptParentRestore);

    try {
        if (operation === "set" && storageKey) {
            window.localStorage.setItem(storageKey, suppliedValue);
            value = suppliedValue;
            if (window.parent !== window) {
                window.parent.postMessage(
                    { type: "ats-session-save", token: suppliedValue },
                    "*"
                );
            }
        } else if (operation === "remove" && storageKey) {
            window.localStorage.removeItem(storageKey);
            value = "";
            if (window.parent !== window) {
                window.parent.postMessage({ type: "ats-session-clear" }, "*");
            }
        } else if (storageKey) {
            value = window.localStorage.getItem(storageKey) ?? "";
            if (!value && window.parent !== window) {
                window.parent.postMessage(
                    { type: "ats-session-request", requestId: restoreRequestId },
                    "*"
                );
            }
        }
    } catch (_error) {
        value = "";
    }

    setStateValue("value", value);
    return () => window.removeEventListener("message", acceptParentRestore);
}
"""

_storage_component = st.components.v2.component(
    "ats_resume_browser_storage",
    html="<span></span>",
    js=_STORAGE_JS,
)


def browser_storage(
    operation: str,
    storage_key: str,
    value: str = "",
    *,
    key: str,
) -> str:
    """Read, write, or remove one localStorage value and return current state."""
    result = _storage_component(
        data={
            "operation": operation,
            "storageKey": storage_key,
            "value": value,
        },
        default={"value": ""},
        on_value_change=lambda: None,
        key=key,
        height=0,
    )
    return str(result.value or "")

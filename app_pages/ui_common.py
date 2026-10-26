"""Shared UI helpers, caching and styling for the TrustGuard Streamlit app."""
from __future__ import annotations

import streamlit as st

from config.settings import load_settings
from database.db import Database
from llm.ollama_client import list_models

STATUS_COLORS = {
    "SUPPORTED": "#1a7f37", "CONTRADICTED": "#b42318", "INSUFFICIENT_EVIDENCE": "#b54708",
    "VERIFICATION_ERROR": "#6941c6", "SAFE": "#1a7f37", "REVIEW": "#b54708", "BLOCK": "#b42318",
    "RELEASED": "#1a7f37", "WITHHELD": "#b42318",
}
STATUS_LABEL = {
    "SUPPORTED": "SUPPORTED", "CONTRADICTED": "CONTRADICTED",
    "INSUFFICIENT_EVIDENCE": "INSUFFICIENT EVIDENCE", "VERIFICATION_ERROR": "VERIFICATION ERROR",
}

CSS = """
<style>
  .main .block-container {max-width: 1150px; padding-top: 1.2rem;}
  .tg-title {font-size: 1.9rem; font-weight: 700; color: #0b3d2e; margin-bottom: 0;}
  .tg-sub {color: #5a6b7b; margin-top: 0.1rem; font-size: 0.95rem;}
  .tg-badge {display:inline-block; padding: 3px 12px; border-radius: 14px; color:#fff;
             font-weight:600; font-size:0.82rem; letter-spacing:0.02em;}
  /* Cards use fixed light backgrounds, so their text is pinned to a dark ink that stays readable
     regardless of the viewer's Streamlit theme (the earlier bug was inheriting light theme text). */
  .tg-card {border:1px solid #e3e8ee; border-radius:10px; padding:14px 16px; margin-bottom:12px;
            background:#ffffff; color:#1b2733;}
  .tg-card, .tg-card * {color:#1b2733;}
  .tg-evidence {border-left:4px solid #0b7285; background:#f6fbfd; padding:10px 14px; border-radius:6px;
                margin:8px 0; font-size:0.9rem; color:#17282d;}
  .tg-contra {border-left:4px solid #b42318; background:#fff5f4;}
  .tg-cite {color:#0b5a6b; font-size:0.8rem; font-weight:600;}
  .tg-claim {font-size:0.98rem; margin:4px 0 6px 0; color:#1b2733;}
  .tg-sig {display:inline-block; font-size:0.72rem; padding:1px 7px; border-radius:10px; margin:2px 4px 2px 0;
           border:1px solid #d0d7de; color:#2a3744;}
  .tg-sig-pass {background:#eaf7ef; border-color:#a6e3bd;}
  .tg-sig-fail {background:#fdeceb; border-color:#f3b4af;}
  .tg-answer {border:1px solid #cfe9dd; background:#f3fbf7; border-radius:10px; padding:16px 18px;
              font-size:1.02rem; color:#103527;}
  .tg-withheld {border:1px solid #f3c6c0; background:#fdf3f2; border-radius:10px; padding:16px 18px; color:#5a1a14;}
  /* keep the accent cite colour readable inside the (light) evidence/card surfaces */
  .tg-evidence .tg-cite {color:#0b5a6b;}
  /* title/sub sit on the page background, which follows the viewer's theme, so adapt them */
  @media (prefers-color-scheme: dark) {
    .tg-title {color:#7fe3c4;}
    .tg-sub {color:#9fb0bd;}
  }
</style>
"""


@st.cache_resource
def get_db() -> Database:
    settings = load_settings()
    return Database(settings.path("db_path"))


@st.cache_resource
def get_base_settings():
    return load_settings()


@st.cache_data(ttl=10)
def available_models(base_url: str) -> list[str]:
    return list_models(base_url)


def badge(text: str, status: str) -> str:
    color = STATUS_COLORS.get(status, "#5a6b7b")
    return f'<span class="tg-badge" style="background:{color}">{text}</span>'


def header(title: str, subtitle: str):
    st.markdown(CSS, unsafe_allow_html=True)
    st.markdown(f'<div class="tg-title">{title}</div><div class="tg-sub">{subtitle}</div>', unsafe_allow_html=True)
    st.write("")


def signal_chips(signals: list[dict]) -> str:
    chips = []
    for s in signals:
        passed = s.get("passed")
        cls = "tg-sig" + ("" if passed is None else (" tg-sig-pass" if passed else " tg-sig-fail"))
        mark = "–" if passed is None else ("pass" if passed else "FAIL")
        chips.append(f'<span class="{cls}" title="{s.get("detail","")}">{s["name"]}: {mark}</span>')
    return "".join(chips)

"""Reusable look-and-feel pieces for the web app: colours, CSS, headers, cards, badges.

Keeping all styling here means every page looks the same, and changing a
colour is a one-line edit. The base theme (fonts, sidebar colours) is in
.streamlit/config.toml; this file adds the finishing touches with CSS.
"""

import html
from string import Template

import pandas as pd
import streamlit as st

# One palette for the whole app (Tailwind-style slate + blue, with clear status colours).
COLORS = {
    "primary": "#2563EB", "primary_dark": "#1D4ED8", "text": "#0F172A", "muted": "#64748B",
    "border": "#E2E8F0", "card": "#FFFFFF", "page": "#F5F7FB",
    "success": "#15803D", "success_bg": "#DCFCE7",
    "warning": "#B45309", "warning_bg": "#FEF3C7",
    "danger": "#B91C1C", "danger_bg": "#FEE2E2",
    "info": "#1D4ED8", "info_bg": "#EFF6FF",
    "neutral": "#475569", "neutral_bg": "#F1F5F9",
}

# Template uses $names, so the CSS curly braces don't need escaping.
CSS = Template("""
<style>
/* --- Hide Streamlit's developer chrome ------------------------------------ */
#MainMenu, footer, [data-testid="stAppDeployButton"], [data-testid="stDecoration"] { display: none !important; }
[data-testid="stHeader"] { background: transparent; }
[data-testid="stMainBlockContainer"] { padding-top: 2.2rem; padding-bottom: 3rem; max-width: 1240px; }

/* --- Page header ----------------------------------------------------------- */
.sa-header { padding-bottom: 1.1rem; margin-bottom: 1.5rem; border-bottom: 1px solid $border; }
.sa-eyebrow { font-size: .74rem; font-weight: 600; letter-spacing: .09em; text-transform: uppercase;
              color: $primary; margin-bottom: .3rem; }
.sa-title { font-size: 1.85rem; font-weight: 700; color: $text; margin: 0; line-height: 1.2; }
.sa-subtitle { color: $muted; font-size: .98rem; margin: .45rem 0 0; max-width: 760px; }

/* --- Cards (containers created with card("name")) --------------------------- */
[class*="st-key-card-"] { background: $card; border: 1px solid $border; border-radius: 14px;
    padding: 1.25rem 1.4rem 1.35rem;
    box-shadow: 0 1px 2px rgba(15, 23, 42, .04), 0 8px 24px -12px rgba(15, 23, 42, .10); }
.sa-section { font-size: 1.02rem; font-weight: 600; color: $text; margin: 0 0 .1rem; }
.sa-caption { font-size: .86rem; color: $muted; margin: 0 0 .75rem; }

/* --- KPI tiles (st.metric) --------------------------------------------------- */
[data-testid="stMetric"] { background: $card; border: 1px solid $border; border-radius: 14px;
    padding: 1rem 1.2rem; box-shadow: 0 1px 2px rgba(15, 23, 42, .04); }
[data-testid="stMetricLabel"] p { font-size: .76rem; font-weight: 600; text-transform: uppercase;
    letter-spacing: .06em; color: $muted; }
[data-testid="stMetricValue"] { font-size: 1.85rem; font-weight: 700; color: $text; }

/* --- Badges ------------------------------------------------------------------- */
.sa-badge { display: inline-block; padding: .14rem .62rem; border-radius: 999px; font-size: .74rem;
            font-weight: 600; line-height: 1.5; white-space: nowrap; }
.sa-badge.success { background: $success_bg; color: $success; }
.sa-badge.warning { background: $warning_bg; color: $warning; }
.sa-badge.danger  { background: $danger_bg;  color: $danger; }
.sa-badge.info    { background: $info_bg;    color: $info; }
.sa-badge.neutral { background: $neutral_bg; color: $neutral; }
.sa-chip { display: inline-block; padding: .12rem .55rem; margin: 0 .3rem .3rem 0; border-radius: 6px;
           background: $neutral_bg; color: $neutral; font-size: .78rem; font-weight: 500; }

/* --- Notices -------------------------------------------------------------------- */
.sa-notice { background: $warning_bg; border: 1px solid #FDE68A; border-left: 4px solid #F59E0B;
             color: #78350F; padding: .7rem 1rem; border-radius: 10px; font-size: .9rem; margin: 0 0 1.25rem; }
.sa-notice.info { background: $info_bg; border-color: #BFDBFE; border-left-color: $primary; color: #1E3A8A; }

/* --- List rows ------------------------------------------------------------------- */
.sa-row { display: flex; justify-content: space-between; align-items: center; gap: 1rem;
          padding: .72rem 0; border-bottom: 1px solid #F1F5F9; }
.sa-row:last-child { border-bottom: none; }
.sa-row > div { min-width: 0; overflow-wrap: anywhere; }   /* long text wraps */
.sa-row > .sa-badge, .sa-row > .sa-key { flex-shrink: 0; white-space: nowrap; }
.sa-row > div:last-child:not(:first-child) { text-align: right; }
.sa-row-title { font-weight: 600; color: $text; font-size: .94rem; }
.sa-row-meta { color: $muted; font-size: .8rem; margin-top: .12rem; }

/* --- Numbered steps ---------------------------------------------------------------- */
.sa-step { display: flex; gap: .75rem; margin: .65rem 0; }
.sa-step-num { flex: 0 0 26px; height: 26px; border-radius: 50%; background: $info_bg; color: $primary;
               font-weight: 700; font-size: .8rem; display: flex; align-items: center; justify-content: center; }
.sa-step-text b { display: block; font-size: .9rem; color: $text; }
.sa-step-text span { font-size: .82rem; color: $muted; }

/* --- Empty states ------------------------------------------------------------------ */
.sa-empty { text-align: center; padding: 2rem 1rem; color: $muted; }
.sa-empty b { display: block; color: $text; font-size: 1rem; margin-bottom: .3rem; }

/* --- Sidebar ------------------------------------------------------------------------ */
.sa-side-label { font-size: .68rem; letter-spacing: .1em; text-transform: uppercase; color: #94A3B8;
                 font-weight: 600; margin: 1.2rem 0 .45rem; }
.sa-side-status { font-size: .82rem; color: #CBD5E1; display: flex; align-items: center; gap: .5rem; margin: .3rem 0; }
.sa-dot { width: 8px; height: 8px; border-radius: 50%; display: inline-block; }
.sa-dot.ok { background: #22C55E; } .sa-dot.off { background: #64748B; } .sa-dot.warn { background: #F59E0B; }
.sa-side-note { font-size: .76rem; color: #94A3B8; line-height: 1.45; margin-top: 1.2rem;
                padding-top: .9rem; border-top: 1px solid #1E293B; }

/* --- Widgets ------------------------------------------------------------------------- */
.stButton > button, .stDownloadButton > button, [data-testid="stFormSubmitButton"] > button { font-weight: 600; }
.stTabs [data-baseweb="tab-list"] { gap: .4rem; border-bottom: 1px solid $border; }
.stTabs [data-baseweb="tab"] { font-weight: 600; padding: .5rem .25rem; }
[data-testid="stDataFrame"] { border: 1px solid $border; border-radius: 10px; overflow: hidden; }
[data-testid="stExpander"] details { background: $card; border-radius: 10px; }
</style>
""")

# Status word -> badge colour, shared by tables and badges.
TONES = {
    "PASS": "success", "FAIL": "danger", "SKIP": "neutral",
    "high": "danger", "medium": "warning", "low": "info",
    "found": "neutral", "draft": "info", "approved": "warning", "sent": "success", "rejected": "danger",
}


def inject_css() -> None:
    """Add the app's CSS once per page run."""
    st.markdown(CSS.substitute(COLORS), unsafe_allow_html=True)


def esc(text: object) -> str:
    """Escape text before putting it inside HTML (titles may contain < or &)."""
    return html.escape(str(text))


def page_header(eyebrow: str, title: str, subtitle: str = "") -> None:
    """The title block at the top of every page."""
    sub = f'<p class="sa-subtitle">{esc(subtitle)}</p>' if subtitle else ""
    st.markdown(f'<div class="sa-header"><div class="sa-eyebrow">{esc(eyebrow)}</div>'
                f'<h1 class="sa-title">{esc(title)}</h1>{sub}</div>', unsafe_allow_html=True)


def card(name: str):
    """A white card. Use it with `with card("name"):`. The key gives it the card CSS class."""
    return st.container(key=f"card-{name}")


def section(title: str, caption: str = "") -> None:
    """A heading (and optional one-line explanation) inside a card."""
    cap = f'<p class="sa-caption">{esc(caption)}</p>' if caption else '<div style="height:.5rem"></div>'
    st.markdown(f'<p class="sa-section">{esc(title)}</p>{cap}', unsafe_allow_html=True)


def badge(text: str, tone: str | None = None) -> str:
    """HTML for a small coloured pill. Tone defaults to the colour for that status word."""
    return f'<span class="sa-badge {tone or TONES.get(text, "neutral")}">{esc(text)}</span>'


def chips(words: list[str]) -> str:
    return "".join(f'<span class="sa-chip">{esc(w)}</span>' for w in words if w)


def notice(text: str, tone: str = "warning") -> None:
    """A slim message bar. `text` may contain simple <b> tags (it is not user input)."""
    css_class = "sa-notice info" if tone == "info" else "sa-notice"
    st.markdown(f'<div class="{css_class}">{text}</div>', unsafe_allow_html=True)


def steps(items: list[tuple[str, str]]) -> None:
    """A numbered list of (title, description) steps."""
    rows = "".join(f'<div class="sa-step"><div class="sa-step-num">{n}</div>'
                   f'<div class="sa-step-text"><b>{esc(t)}</b><span>{esc(d)}</span></div></div>'
                   for n, (t, d) in enumerate(items, start=1))
    st.markdown(rows, unsafe_allow_html=True)


def empty_state(title: str, text: str) -> None:
    st.markdown(f'<div class="sa-empty"><b>{esc(title)}</b>{esc(text)}</div>', unsafe_allow_html=True)


def status_table(df: pd.DataFrame, columns: list[str]):
    """Colour the cells of status-like columns (PASS/FAIL, high/low, draft/sent...)."""
    def colour(value: object) -> str:
        tone = TONES.get(str(value))
        if not tone:
            return ""
        return (f"background-color: {COLORS[tone + '_bg']}; color: {COLORS[tone]}; "
                "font-weight: 600")
    return df.style.map(colour, subset=columns)

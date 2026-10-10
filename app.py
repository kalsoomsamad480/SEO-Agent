"""Streamlit web interface for the SEO Agent.

Run it with:   streamlit run app.py
Then open the address it prints (usually http://localhost:8501).

How Streamlit works (the one thing to know): every time you click a button,
Streamlit re-runs this whole file from top to bottom. Anything that must
survive a re-run (like the selected blog) is kept in `st.session_state`.

This file only sets up the page frame: sidebar menu, logo and status.
The pages themselves are in src/ui/views.py, the styling in src/ui/components.py,
and the theme colours in .streamlit/config.toml.
"""

import streamlit as st

import config
from src.ui import views
from src.ui.components import esc, inject_css

ASSETS = config.PROJECT_ROOT / "assets"


def sidebar_status() -> None:
    """Small status panel under the menu: which services are connected."""
    def line(label: str, state: str) -> str:
        return f'<div class="sa-side-status"><span class="sa-dot {state}"></span>{esc(label)}</div>'

    ai_state = "ok" if config.LLM_API_KEY else "warn"
    st.markdown(
        '<div class="sa-side-label">Status</div>'
        + line(f"AI · {config.LLM_MODEL}" if config.LLM_API_KEY else "AI key missing", ai_state)
        + line("PageSpeed", "ok" if config.PAGESPEED_API_KEY else "off")
        + line("Brave Search", "ok" if config.BRAVE_SEARCH_API_KEY else "off")
        + '<div class="sa-side-note">Human review is required before publishing. '
          "Nothing is ever published or sent automatically.</div>",
        unsafe_allow_html=True)


def main() -> None:
    st.set_page_config(page_title="SEO Agent", page_icon=":material/insights:", layout="wide")
    inject_css()
    st.logo(str(ASSETS / "logo.svg"), icon_image=str(ASSETS / "logo-icon.svg"), size="large")

    pages = {
        "dashboard": st.Page(views.dashboard_view, title="Dashboard", icon=":material/space_dashboard:",
                             default=True),
        "create": st.Page(views.create_blog_view, title="Create Blog", icon=":material/edit_note:",
                          url_path="create"),
        "library": st.Page(views.library_view, title="Blog Library", icon=":material/library_books:",
                           url_path="library"),
        "audit": st.Page(views.audit_view, title="Site Audit", icon=":material/travel_explore:",
                         url_path="audit"),
        "backlinks": st.Page(views.backlinks_view, title="Backlinks", icon=":material/link:",
                             url_path="backlinks"),
        "settings": st.Page(views.settings_view, title="Settings", icon=":material/settings:",
                            url_path="settings"),
    }
    st.session_state["pages"] = pages   # lets pages link to each other

    navigation = st.navigation({
        "Overview": [pages["dashboard"]],
        "Content": [pages["create"], pages["library"]],
        "Technical": [pages["audit"]],
        "Off-page": [pages["backlinks"]],
        "System": [pages["settings"]],
    })
    with st.sidebar:
        sidebar_status()
    navigation.run()


main()

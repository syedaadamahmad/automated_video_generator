"""
auth.py — Role-based authentication layer for Veo Studio
═══════════════════════════════════════════════════════════
Currently: hardcoded admin stub — no real auth.
To add real auth (Cognito, Supabase, LDAP, etc.):
  1. Implement the body of `authenticate_user(email, password)` below.
  2. Leave every other function and all call sites in veo_app.py unchanged.

Roles (lowest → highest privilege):
  viewer  — can watch generated videos, cannot generate or approve
  editor  — can generate and rerun, cannot approve for YouTube
  admin   — full access including approve, YouTube queue, metrics

Usage in veo_app.py:
  from auth import require_auth, has_permission, get_current_user
  require_auth()                        # call once at top of app
  if has_permission("approve"):         # guard individual actions
      ...
  user = get_current_user()             # {name, email, role}
"""

from typing import Optional
import streamlit as st

# ── Role permission map ────────────────────────────────────────────────────────
_PERMISSIONS: dict[str, list[str]] = {
    "viewer": [
        "view_videos",
    ],
    "editor": [
        "view_videos",
        "generate",
        "rerun",
        "reject",
        "download",
    ],
    "admin": [
        "view_videos",
        "generate",
        "rerun",
        "reject",
        "download",
        "approve",
        "youtube_queue",
        "view_metrics",
        "view_jobs",
    ],
}


# ── Stub user store — replace with DB/API lookup ───────────────────────────────
_STUB_USERS: dict[str, dict] = {
    "admin@veo.local": {
        "name":     "Admin",
        "email":    "admin@veo.local",
        "role":     "admin",
        "password": "admin",   # NEVER hardcode in production — use hashed secrets
    },
    "editor@veo.local": {
        "name":     "Editor",
        "email":    "editor@veo.local",
        "role":     "editor",
        "password": "editor",
    },
    "viewer@veo.local": {
        "name":     "Viewer",
        "email":    "viewer@veo.local",
        "role":     "viewer",
        "password": "viewer",
    },
}


def authenticate_user(email: str, password: str) -> Optional[dict]:
    """
    Validate credentials and return user dict or None.

    STUB: checks against _STUB_USERS.
    PRODUCTION: replace body with:
      - Supabase: supabase.auth.sign_in_with_password({"email": email, "password": password})
      - Cognito:  boto3 cognito_idp.initiate_auth(...)
      - LDAP:     ldap3 Connection(...)
      - Any OAuth: redirect flow, then fetch user from token
    """
    user = _STUB_USERS.get(email.lower().strip())
    if user and user["password"] == password:
        return {k: v for k, v in user.items() if k != "password"}
    return None


def get_current_user() -> Optional[dict]:
    """Return the currently logged-in user dict, or None."""
    return st.session_state.get("user")


def has_permission(action: str) -> bool:
    """
    Return True if the current user is allowed to perform `action`.
    Returns False if not logged in.
    """
    user = get_current_user()
    if not user:
        return False
    role = user.get("role", "viewer")
    return action in _PERMISSIONS.get(role, [])


def require_auth() -> None:
    """
    Call once at the top of veo_app.py.
    If no user is in session, renders the login page and stops execution.
    On successful login, stores user in session_state and reruns.
    """
    if st.session_state.get("user"):
        return   # already authenticated — let app continue

    _render_login_page()
    st.stop()   # halt the rest of veo_app.py until login succeeds


def logout() -> None:
    """Clear the session and trigger a rerun to show the login page."""
    for key in list(st.session_state.keys()):
        del st.session_state[key]
    st.rerun()


# ── Login page ─────────────────────────────────────────────────────────────────
def _render_login_page() -> None:
    st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600&display=swap');
html, body, [data-testid="stApp"] {
    background: #F5F5F7 !important;
    font-family: -apple-system, BlinkMacSystemFont, "SF Pro Display",
                 "Helvetica Neue", Arial, sans-serif !important;
}
#MainMenu, footer, header { visibility: hidden; }
[data-testid="stToolbar"] { display: none; }
.block-container { max-width: 420px; margin: 10vh auto 0; padding: 0 1.5rem; }
</style>
""", unsafe_allow_html=True)

    st.markdown("""
<div style="text-align:center; margin-bottom:2.5rem;">
  <div style="font-size:2rem; font-weight:700; color:#1D1D1F; letter-spacing:-0.03em;">
    Veo Studio
  </div>
  <div style="font-size:.95rem; color:#6E6E73; margin-top:.4rem;">
    Sign in to continue
  </div>
</div>
""", unsafe_allow_html=True)

    with st.form("login_form"):
        email    = st.text_input("Email", placeholder="you@example.com")
        password = st.text_input("Password", type="password", placeholder="••••••••")
        submit   = st.form_submit_button("Sign In", use_container_width=True)

    if submit:
        user = authenticate_user(email, password)
        if user:
            st.session_state.user = user
            st.rerun()
        else:
            st.error("Incorrect email or password.")

    st.markdown("""
<div style="text-align:center; margin-top:2rem; font-size:.8rem; color:#6E6E73;">
  Stub auth active — see auth.py to connect a real provider.
</div>
""", unsafe_allow_html=True)
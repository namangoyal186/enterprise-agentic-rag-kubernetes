"""
patch_streamlit_index.py
------------------------
Patches Streamlit's bundled index.html at startup to inject a pre-rendered
login card splash screen. The splash is pure HTML/CSS — visible from the
browser's very first response, before any WebSocket connection is made.

Flow:
  1. Browser hits URL → gets HTML with splash card already inside (instant)
  2. Streamlit WebSocket connects in the background (2-4s)
  3. When React app mounts, splash fades out (0.35s transition)
  4. Normal Streamlit app takes over

For already-logged-in users:
  - The JS cookie reader in auth.py detects the session cookie within ~50ms
  - Page redirects to ?session=... before Streamlit even finishes loading
  - Splash shows the card briefly during redirect (correct behaviour)
"""

import os
import urllib.parse


# ── Google Auth URL (built from environment variables) ──────────────────────

def _build_auth_url() -> str:
    client_id = os.getenv("GOOGLE_CLIENT_ID", "")
    redirect_uri = os.getenv("RENDER_EXTERNAL_URL", "")
    if not redirect_uri:
        redirect_uri = os.getenv("REDIRECT_URI", "http://localhost:8501")
    redirect_uri = redirect_uri.strip().rstrip("/")
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "access_type": "offline",
        "prompt": "select_account",
    }
    return "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode(params)


# ── Splash HTML ──────────────────────────────────────────────────────────────

def _build_splash(auth_url: str) -> str:
    return f"""
<!-- ═══════════ INSTANT SPLASH (injected by patch_streamlit_index.py) ═══════════ -->
<style id="st-splash-css">
  #st-splash {{
    position: fixed;
    top: 0; left: 0; right: 0; bottom: 0;
    background: #0e1117;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    z-index: 2147483647;          /* always on top */
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    transition: opacity 0.35s ease;
  }}
  #st-splash.fade-out {{ opacity: 0 !important; pointer-events: none !important; }}

  .sp-card {{
    max-width: 520px;
    width: 88%;
    padding: 38px 34px 28px 34px;
    background: rgba(255,255,255,0.03);
    border: 1px solid rgba(255,255,255,0.08);
    border-radius: 20px;
    text-align: center;
    backdrop-filter: blur(16px);
    -webkit-backdrop-filter: blur(16px);
    box-shadow: 0 12px 40px rgba(0,0,0,0.35);
  }}
  .sp-title {{
    font-size: 28px;
    font-weight: 700;
    color: #ffffff;
    margin: 0 0 8px 0;
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 10px;
  }}
  .sp-sub {{
    color: #9aa0a6;
    font-size: 14px;
    line-height: 1.55;
    margin-bottom: 22px;
  }}
  .sp-tags {{
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
    justify-content: center;
  }}
  .sp-tag {{
    background: rgba(255,255,255,0.05);
    color: #cbd5e1;
    font-size: 11.5px;
    padding: 4px 10px;
    border-radius: 8px;
    border: 1px solid rgba(255,255,255,0.06);
  }}
  .sp-btn-wrap {{
    display: flex;
    justify-content: center;
    margin-top: 28px;
  }}
  .sp-btn {{
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: 10px;
    background: #ffffff;
    color: #202124 !important;
    border: 1px solid #dadce0;
    border-radius: 10px;
    font-size: 15px;
    font-weight: 600;
    padding: 13px 28px;
    box-shadow: 0 4px 12px rgba(0,0,0,0.2);
    text-decoration: none !important;
    cursor: pointer;
    max-width: 340px;
    width: 88vw;
    transition: background 0.18s ease, box-shadow 0.18s ease, transform 0.18s ease;
  }}
  .sp-btn:hover {{
    background: #f1f3f4;
    box-shadow: 0 6px 16px rgba(0,0,0,0.3);
    transform: translateY(-1px);
    color: #202124 !important;
    text-decoration: none !important;
  }}
  @media (max-width: 600px) {{
    .sp-card {{ padding: 28px 18px 22px 18px; }}
    .sp-title {{ font-size: 22px; }}
  }}
</style>

<div id="st-splash" translate="no">
  <div class="sp-card">
    <div class="sp-title">&#9784;&#65039; Kubernetes Enterprise AI</div>
    <div class="sp-sub">
      Autonomous Cloud-Native IT Copilot powered by Multi-Agent LangGraph,<br>
      Qdrant Hybrid RAG, NeMo Guardrails &amp; Qwen 27B.
    </div>
    <div class="sp-tags">
      <span class="sp-tag">&#9889; Qwen 27B</span>
      <span class="sp-tag">&#128269; Qdrant Hybrid Vector RAG</span>
      <span class="sp-tag">&#128737;&#65039; NeMo Security Guardrails</span>
      <span class="sp-tag">&#128024; Neon PostgreSQL Memory</span>
      <span class="sp-tag">&#128678; Upstash Redis Limiter</span>
    </div>
  </div>
  <div class="sp-btn-wrap">
    <a href="{auth_url}" id="sp-google-btn" class="sp-btn" target="_self">
      &#128640; Continue with Google
    </a>
  </div>
</div>

<script id="st-splash-js">
(function() {{
  var splash = document.getElementById('st-splash');
  var removed = false;

  function removeSplash() {{
    if (removed) return;
    removed = true;
    if (!splash) return;
    splash.classList.add('fade-out');
    setTimeout(function() {{
      if (splash && splash.parentNode) splash.parentNode.removeChild(splash);
      var css = document.getElementById('st-splash-css');
      if (css && css.parentNode) css.parentNode.removeChild(css);
      var sc = document.getElementById('st-splash-js');
      if (sc && sc.parentNode) sc.parentNode.removeChild(sc);
    }}, 380);
  }}

  // --- Cookie reader: restore session from cookie without extra round-trip ---
  function getCookie(name) {{
    var m = document.cookie.match('(?:^|; )' + name + '=([^;]*)');
    return m ? decodeURIComponent(m[1]) : null;
  }}
  var sessionVal = getCookie('kube_rag_session');
  if (sessionVal) {{
    // Already logged in — redirect immediately (splash shows for <100ms then redirect)
    var url = new URL(window.location.href);
    if (!url.searchParams.get('session')) {{
      url.searchParams.set('session', sessionVal);
      window.location.replace(url.toString());
    }}
  }}

  // --- Remove splash when Streamlit's React app is ready ─────────────────
  var ticker = setInterval(function() {{
    var app = document.querySelector('[data-testid="stApp"]') ||
              document.querySelector('[data-testid="stAppViewContainer"]') ||
              document.querySelector('.main');
    if (app) {{
      clearInterval(ticker);
      removeSplash();
    }}
  }}, 80);

  // Safety: always remove after 90s (e.g. Render cold-start keep-alive)
  setTimeout(function() {{
    clearInterval(ticker);
    removeSplash();
  }}, 90000);
}})();
</script>
<!-- ═══════════════════════════════════════════════════════════════════════════ -->
"""


# ── Patcher ──────────────────────────────────────────────────────────────────

def patch_index_html() -> bool:
    """
    Locate Streamlit's bundled index.html and inject the splash card.
    Also sets lang="en" and adds notranslate meta to prevent browser translate popup.
    Safe to call multiple times — skips if already patched.
    Returns True on success, False if skipped or error.
    """
    try:
        import streamlit as st_module
        streamlit_dir = os.path.dirname(st_module.__file__)
        index_path = os.path.join(streamlit_dir, "static", "index.html")

        if not os.path.exists(index_path):
            print(f"[splash] ⚠ index.html not found at {index_path} — skipping patch.")
            return False

        with open(index_path, "r", encoding="utf-8") as fh:
            original = fh.read()

        if "st-splash" in original:
            print("[splash] Already patched — skipping.")
            return True

        import re

        patched = original

        # ── Fix 1: Set lang="en" on <html> tag to prevent browser translate popup ──
        # Streamlit's index.html may have lang="fr" or no lang attribute at all.
        patched = re.sub(r'<html([^>]*?)(?:\s+lang="[^"]*")?([^>]*)>',
                         r'<html\1 lang="en"\2>', patched, count=1)

        # ── Fix 2: Inject notranslate meta + charset in <head> ─────────────────
        no_translate_meta = (
            '<meta name="google" content="notranslate">'
            '<meta http-equiv="Content-Language" content="en">'
        )
        patched = re.sub(r'(<head[^>]*>)', r'\1' + no_translate_meta, patched, count=1)

        # ── Fix 3: Inject splash card right after <body> ────────────────────────
        auth_url = _build_auth_url()
        splash_html = _build_splash(auth_url)
        patched, count = re.subn(r"(<body[^>]*>)", r"\1" + splash_html, patched, count=1)

        if count == 0:
            print("[splash] ⚠ Could not find <body> tag — skipping patch.")
            return False

        with open(index_path, "w", encoding="utf-8") as fh:
            fh.write(patched)

        print(f"[splash] ✅ Patched Streamlit index.html — instant splash + lang=en active.")
        return True

    except Exception as exc:
        print(f"[splash] ⚠ Patch failed (non-fatal): {exc}")
        return False


if __name__ == "__main__":
    patch_index_html()

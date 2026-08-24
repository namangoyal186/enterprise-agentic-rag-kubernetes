#!/usr/bin/env python3
"""
start.py — Production startup entry point for the Streamlit UI.

Steps:
  1. Patch Streamlit's index.html with instant splash card
  2. Launch Streamlit (replaces the current process via os.execv)
"""

import os
import sys

# Ensure ui/ and project root are on the path
_ui_dir = os.path.dirname(os.path.abspath(__file__))
_root_dir = os.path.dirname(_ui_dir)
for _p in (_root_dir, _ui_dir):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# ── Step 1: Patch Streamlit's index.html ────────────────────────────────────
try:
    from patch_streamlit_index import patch_index_html
    patch_index_html()
except Exception as e:
    print(f"[start] Splash patch skipped: {e}")

# ── Step 2: Launch Streamlit (exec replaces this process — no wrapper overhead) ──
app_path = os.path.join(_ui_dir, "app.py")
port = os.getenv("PORT", "10000")   # Render sets PORT env var

cmd = [
    sys.executable, "-m", "streamlit", "run",
    app_path,
    "--server.port", port,
    "--server.address", "0.0.0.0",
    "--server.headless", "true",
    "--server.enableCORS", "false",
    "--server.enableXsrfProtection", "false",
    "--browser.gatherUsageStats", "false",
]

print(f"[start] Launching: {' '.join(cmd)}")
os.execv(sys.executable, cmd)

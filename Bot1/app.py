"""
Bot #1 App Entrypoint
Routes directly to Bot #1 Sunrise Ogle Master Command Panel (Port 8501)
"""
import os
import sys

_DIR = os.path.dirname(os.path.abspath(__file__))
if _DIR not in sys.path:
    sys.path.insert(0, _DIR)

panel_path = os.path.join(_DIR, "panel.py")
with open(panel_path, "r", encoding="utf-8") as f:
    exec(f.read(), globals())

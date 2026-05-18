"""
BetBot Launcher — compiled into BetBot.exe by PyInstaller.

Responsibilities:
  1. Set working directory to the install folder (so data/ paths resolve correctly)
  2. Add app/ to sys.path so all imports work
  3. Run gui.py from app/

This file is rarely updated. All business logic lives in app/ and is hot-updated.
"""

import sys
import os
import pathlib
import runpy

# ── Locate directories ────────────────────────────────────────────────────────
if getattr(sys, "frozen", False):
    # Running as compiled EXE
    BASE_DIR = pathlib.Path(sys.executable).parent
else:
    # Running as plain Python (development)
    BASE_DIR = pathlib.Path(__file__).parent

APP_DIR = BASE_DIR / "app"

# ── Set working directory so relative paths (data/, exports/) resolve ─────────
os.chdir(BASE_DIR)

# ── Add app/ to sys.path so all imports (models/, scrapers/, utils/) resolve ──
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

# ── Launch ────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    gui_path = APP_DIR / "gui.py"
    if not gui_path.exists():
        import tkinter.messagebox as mb
        mb.showerror("BetBot — Launch Error",
                     f"Cannot find app/gui.py\n\nExpected: {gui_path}\n\n"
                     "Please reinstall BetBot.")
        sys.exit(1)

    runpy.run_path(str(gui_path), run_name="__main__")

"""
Run this script before every release to generate update_manifest.json.

Usage:
    cd C:\\laragon\\www\\bet-bot
    python tools/generate_manifest.py

This creates update_manifest.json in the project root.
Commit it together with your code changes and push to GitHub.
The auto-updater in the app fetches this file to know which files to download.
"""

import json
import hashlib
import pathlib
import sys

# ── Config ────────────────────────────────────────────────────────────────────
GITHUB_USER   = "teoxtrm"
GITHUB_REPO   = "bet-bot"             # ← change this if repo name differs
GITHUB_BRANCH = "main"

RAW_BASE = f"https://raw.githubusercontent.com/{GITHUB_USER}/{GITHUB_REPO}/{GITHUB_BRANCH}"

# ── Paths ─────────────────────────────────────────────────────────────────────
PROJECT_ROOT = pathlib.Path(__file__).parent.parent
VERSION_FILE = PROJECT_ROOT / "version.txt"
OUTPUT_FILE  = PROJECT_ROOT / "update_manifest.json"

EXCLUDES = {
    "launcher.py",       # compiled into EXE — not hot-updated
    "bet-bot.spec",
    "build.bat",
    "requirements.txt",
    "explore_odds_api.py",
}

EXCLUDE_DIRS = {
    ".git", "__pycache__", "dist", "build", ".venv", "venv",
    "installer", "tools", "exports", "data", "logs", "assets",
}

# ── Collect files ─────────────────────────────────────────────────────────────
def collect_files():
    files = []

    def _add(src_path: pathlib.Path, rel_in_app: str):
        content = src_path.read_bytes()
        sha256  = hashlib.sha256(content).hexdigest()
        url     = f"{RAW_BASE}/{rel_in_app.replace(chr(92), '/')}"
        files.append({
            "path":   rel_in_app.replace("\\", "/"),
            "url":    url,
            "sha256": sha256,
            "size":   len(content),
        })

    # Root .py files (gui.py, updater.py, setup_wizard.py, ...)
    for f in sorted(PROJECT_ROOT.glob("*.py")):
        if f.name not in EXCLUDES:
            _add(f, f.name)

    # version.txt
    if VERSION_FILE.exists():
        _add(VERSION_FILE, "version.txt")

    # Subdirectory .py files
    for sub in sorted(["models", "scrapers", "utils"]):
        sub_dir = PROJECT_ROOT / sub
        if not sub_dir.exists():
            continue
        for f in sorted(sub_dir.rglob("*.py")):
            parts = f.relative_to(PROJECT_ROOT)
            rel   = str(parts)
            if any(p in EXCLUDE_DIRS for p in parts.parts):
                continue
            _add(f, rel)

    return files


def main():
    if not VERSION_FILE.exists():
        print("ERROR: version.txt not found. Create it with your current version number.")
        sys.exit(1)

    version = VERSION_FILE.read_text().strip()
    files   = collect_files()

    manifest = {
        "version":     version,
        "files":       files,
        "total_files": len(files),
        "total_bytes": sum(f["size"] for f in files),
    }

    OUTPUT_FILE.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    total_kb = manifest["total_bytes"] / 1024
    print(f"OK Generated update_manifest.json")
    print(f"  Version : {version}")
    print(f"  Files   : {len(files)}")
    print(f"  Size    : {total_kb:.1f} KB  (this is how much users download per update)")
    print()
    print("Next steps:")
    print("  1. git add update_manifest.json version.txt")
    print("  2. git commit -m 'Release v{version}'")
    print("  3. git push")
    print("  4. Users will see the update prompt on next launch.")


if __name__ == "__main__":
    main()

"""
Auto-updater: checks GitHub for a newer version and downloads only changed files.

On first install, all files are in app/.
Updates replace individual .py files — no full reinstall needed.
The EXE (launcher) is only replaced on major releases (new Python/library version).

Usage:
    from updater import check_for_update, download_update, restart_app
"""

import json
import hashlib
import pathlib
import shutil
import sys
import tempfile
from urllib.request import urlopen, urlretrieve
from urllib.error import URLError

# ── Config — fill in before first release ────────────────────────────────────
GITHUB_USER  = "teoxtrm"
GITHUB_REPO  = "bet-bot"
GITHUB_BRANCH = "main"

_RAW   = f"https://raw.githubusercontent.com/{GITHUB_USER}/{GITHUB_REPO}/{GITHUB_BRANCH}"
VERSION_URL  = f"{_RAW}/version.txt"
MANIFEST_URL = f"{_RAW}/update_manifest.json"

# ── Paths ─────────────────────────────────────────────────────────────────────
_APP_DIR = pathlib.Path(__file__).parent   # the app/ folder


def get_local_version() -> str:
    try:
        return (_APP_DIR / "version.txt").read_text(encoding="utf-8").strip()
    except Exception:
        return "0.0.0"


def get_remote_version(timeout: int = 5) -> str | None:
    try:
        with urlopen(VERSION_URL, timeout=timeout) as r:
            return r.read().decode().strip()
    except (URLError, OSError):
        return None


def check_for_update() -> tuple[bool, str, str]:
    """
    Returns (update_available, local_version, remote_version).
    remote_version is "" if the check failed (no internet / GitHub down).
    """
    local  = get_local_version()
    remote = get_remote_version()
    if remote and remote != local:
        return True, local, remote
    return False, local, remote or local


def download_update(progress_cb=None) -> tuple[bool, str]:
    """
    Download and apply patch files listed in update_manifest.json.

    progress_cb(current: int, total: int, filename: str) is called per file.
    Returns (success: bool, error_message: str).
    """
    try:
        with urlopen(MANIFEST_URL, timeout=15) as r:
            manifest = json.loads(r.read())
    except Exception as e:
        return False, f"Could not fetch update manifest: {e}"

    files  = manifest.get("files", [])
    total  = len(files)
    errors = []

    for i, entry in enumerate(files, 1):
        rel_path = entry["path"]          # e.g. "gui.py" or "models/watchlist.py"
        url      = entry["url"]           # raw GitHub URL
        expected = entry.get("sha256", "")

        dest = _APP_DIR / rel_path
        dest.parent.mkdir(parents=True, exist_ok=True)

        try:
            tmp = pathlib.Path(tempfile.mktemp(suffix=".tmp"))
            urlretrieve(url, str(tmp))

            if expected:
                actual = hashlib.sha256(tmp.read_bytes()).hexdigest()
                if actual != expected:
                    tmp.unlink(missing_ok=True)
                    errors.append(f"{rel_path}: hash mismatch")
                    continue

            shutil.move(str(tmp), str(dest))
        except Exception as e:
            errors.append(f"{rel_path}: {e}")

        if progress_cb:
            progress_cb(i, total, rel_path)

    # Update local version.txt to match manifest
    try:
        new_ver = manifest.get("version", "")
        if new_ver:
            (_APP_DIR / "version.txt").write_text(new_ver + "\n", encoding="utf-8")
    except Exception:
        pass

    if errors:
        return False, "\n".join(errors)
    return True, ""


def restart_app():
    """Restart the app by re-launching the current executable."""
    import os
    import subprocess
    exe  = sys.executable
    args = sys.argv[:]
    subprocess.Popen([exe] + args)
    sys.exit(0)

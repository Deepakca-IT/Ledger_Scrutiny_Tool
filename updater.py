"""Token-free updates from public GitHub Releases.

Once a day the app asks GitHub for the latest release. If it is newer, the
update ZIP is downloaded, checked against its published SHA-256, and unpacked
into update_staging/. run.bat / run_app.bat copy it over the app at the next
launch, before Python starts, then delete the staging folder.

Updates carry app code, the TDL and notes only. Launchers and the embedded
Python change only through the full installer: when a release needs different
Python packages, the app asks the user to run the new installer instead.
"""

import hashlib
import io
import json
import os
import re
import shutil
import zipfile
from datetime import date
from pathlib import Path

import requests

REPO = "Deepakca-IT/Ledger_Scrutiny_Tool"
API_LATEST = os.environ.get(
    "LSTOOL_UPDATE_API", f"https://api.github.com/repos/{REPO}/releases/latest")
RELEASES_PAGE = f"https://github.com/{REPO}/releases/latest"

APP_DIR = Path(__file__).resolve().parent
VERSION_FILE = APP_DIR / "version.txt"
REQUIREMENTS_FILE = APP_DIR / "requirements.txt"
STATE_FILE = APP_DIR / "update_state.json"
STAGING_DIR = APP_DIR / "update_staging"
READY_FLAG = APP_DIR / "update_ready.txt"

TIMEOUT = 8
MAX_ZIP_BYTES = 25 * 1024 * 1024
ASSET_RE = re.compile(r"^LS_Tool_update_[\d.]+\.zip$")
# Files an update may replace. Anything else in the ZIP is refused.
ALLOWED = re.compile(
    r"^(?:[A-Za-z0-9_]+\.py|engines/[A-Za-z0-9_]+\.py|tally_tdl/[A-Za-z0-9_.-]+\.(?:tdl|md)"
    r"|version\.txt|changelog\.txt|requirements\.txt|splash\.html|README\.md|LICENSE"
    r"|manifest\.json)$")


def dev_mode():
    """The development copy (a git checkout) never updates itself."""
    return (APP_DIR / ".git").exists() or (APP_DIR / "dev_mode.txt").exists()


def current_version():
    try:
        return VERSION_FILE.read_text(encoding="utf-8-sig").strip() or "0.0.0"
    except OSError:
        return "0.0.0"


def _vtuple(v):
    nums = re.findall(r"\d+", str(v))
    return tuple(int(n) for n in nums[:4]) or (0,)


def is_newer(latest, current):
    return _vtuple(latest) > _vtuple(current)


def _sha256(data):
    return hashlib.sha256(data).hexdigest()


def _requirements_hash():
    try:
        text = REQUIREMENTS_FILE.read_text(encoding="utf-8-sig")
    except OSError:
        return ""
    lines = sorted(l.strip().lower() for l in text.splitlines() if l.strip() and not l.startswith("#"))
    return _sha256("\n".join(lines).encode())


def _checked_today():
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8")).get("last_check") == date.today().isoformat()
    except (OSError, ValueError):
        return False


def _remember_check():
    try:
        STATE_FILE.write_text(json.dumps({"last_check": date.today().isoformat()}), encoding="utf-8")
    except OSError:
        pass


def _latest_release():
    r = requests.get(API_LATEST, timeout=TIMEOUT,
                     headers={"Accept": "application/vnd.github+json"})
    r.raise_for_status()
    rel = r.json()
    assets = {a["name"]: a["browser_download_url"] for a in rel.get("assets", [])}
    zips = [n for n in assets if ASSET_RE.match(n)]
    if len(zips) != 1 or zips[0] + ".sha256" not in assets:
        raise ValueError("The latest release has no valid update file.")
    return {
        "version": rel.get("tag_name", "").lstrip("vV"),
        "notes": rel.get("body") or "",
        "zip_url": assets[zips[0]],
        "sha_url": assets[zips[0] + ".sha256"],
    }


def check_for_update(force=False):
    """Return {'status': 'skipped'|'dev'|'up_to_date'|'update_available'|'error', ...}."""
    if dev_mode():
        return {"status": "dev"}
    if not force and _checked_today():
        return {"status": "skipped"}
    _remember_check()
    try:
        rel = _latest_release()
    except Exception as e:
        return {"status": "error", "message": f"Could not check for updates: {e}"}
    cur = current_version()
    if not is_newer(rel["version"], cur):
        return {"status": "up_to_date", "version": cur}
    return {"status": "update_available", "current": cur, "latest": rel["version"],
            "notes": rel["notes"], "release": rel}


def _download(url, limit):
    with requests.get(url, timeout=TIMEOUT * 4, stream=True) as r:
        r.raise_for_status()
        buf = io.BytesIO()
        for chunk in r.iter_content(64 * 1024):
            buf.write(chunk)
            if buf.tell() > limit:
                raise ValueError("Update file is larger than expected.")
        return buf.getvalue()


def stage_update(info):
    """Download, verify and unpack an available update for the next launch.

    Returns {'status': 'staged'|'installer_required'|'error', ...}.
    """
    if dev_mode():
        return {"status": "error", "message": "Updates are disabled in the development copy."}
    rel = info["release"]
    try:
        data = _download(rel["zip_url"], MAX_ZIP_BYTES)
        expected = _download(rel["sha_url"], 4096).decode("ascii", "ignore").split()[0].lower()
        if _sha256(data) != expected:
            raise ValueError("Update file failed its checksum.")
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            names = [n for n in z.namelist() if not n.endswith("/")]
            bad = [n for n in names if not ALLOWED.match(n)]
            if bad or "version.txt" not in names or "manifest.json" not in names:
                raise ValueError(f"Update file has unexpected contents: {bad[:3]}")
            manifest = json.loads(z.read("manifest.json"))
            if manifest.get("version") != rel["version"]:
                raise ValueError("Update file version does not match the release.")
            if manifest.get("requirements_sha256") != _requirements_hash():
                return {"status": "installer_required", "latest": rel["version"],
                        "url": RELEASES_PAGE}
            READY_FLAG.unlink(missing_ok=True)
            shutil.rmtree(STAGING_DIR, ignore_errors=True)
            STAGING_DIR.mkdir()
            for n in names:
                if n == "manifest.json":
                    continue
                dest = STAGING_DIR / n
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(z.read(n))
        READY_FLAG.write_text(rel["version"], encoding="utf-8")
        return {"status": "staged", "latest": rel["version"]}
    except Exception as e:
        READY_FLAG.unlink(missing_ok=True)
        shutil.rmtree(STAGING_DIR, ignore_errors=True)
        return {"status": "error", "message": f"Update download failed: {e}"}


def staged_version():
    try:
        return READY_FLAG.read_text(encoding="utf-8").strip()
    except OSError:
        return ""

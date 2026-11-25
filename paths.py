"""Central, year-scoped path resolver for the Ledger Scrutiny Tool.

Single source of truth for every on-disk location. Layout (full per-year
consistency):

    data/<company>/
        entity.json                  # company-level: year list + active-year pointers
        years/<fy>/
            extracted/
            consolidated/
            analysis/
            financials/   (+ masters/)
            msme/
            config/

`entity.json` stays at the company root because it indexes the years and holds
the active current_fy / previous_fy pointers. Everything else is per-year.

All helpers return pathlib.Path. They never create directories except
`ensure_year`, which scaffolds an empty year.
"""

import os
import json
import time
import shutil
import socket
import getpass
from pathlib import Path

# ── Configurable data root (LAN multi-user) ──────────────────────────────────
# Every PC installs the app but can share ONE data folder on the LAN. The shared
# root is stored per-machine in data_location.json beside this module (i.e. the
# install dir, e.g. %LOCALAPPDATA%\LS_Tool). When that file is absent the app
# falls back to the single-user home folder, so standalone installs are
# unchanged. Changing the location takes effect on the next app restart.
_DEFAULT_ROOT  = Path.home() / "Documents" / "LSTool"
_LOCATION_FILE = Path(__file__).resolve().parent / "data_location.json"


def data_location_file():
    return _LOCATION_FILE


def get_data_root():
    """LSTool root (folder holding data/ + profile.json). Reads the per-machine
    override; falls back to the single-user home folder."""
    try:
        if _LOCATION_FILE.exists():
            d = json.loads(_LOCATION_FILE.read_text(encoding="utf-8"))
            root = str(d.get("data_root") or "").strip()
            if root:
                return Path(root)
    except Exception:
        pass
    return _DEFAULT_ROOT


def set_data_root(path):
    """Persist the shared LSTool root for THIS machine. Takes effect on restart."""
    _LOCATION_FILE.write_text(
        json.dumps({"data_root": str(path).strip()}, indent=2), encoding="utf-8")


def is_data_location_configured():
    return _LOCATION_FILE.exists()


# Resolved once at import. Changing the location requires an app restart.
LSTOOL_ROOT = get_data_root()
BASE = LSTOOL_ROOT / "data"

# Files that are global (not per company / not per year) — listed for reference.
SYSTEM_SECTIONS = BASE / "system_sections.json"
WORD_RULES      = BASE / "word_rules.json"

# Marker dropped in a company folder once flat->nested migration has run.
MIGRATED_FLAG = "layout_migrated.flag"


# ── Company level ─────────────────────────────────────────────────────────────
def company_dir(company):
    return BASE / company

def entity_path(company):
    return company_dir(company) / "entity.json"

def migrated_flag_path(company):
    return company_dir(company) / MIGRATED_FLAG


# ── Year index ────────────────────────────────────────────────────────────────
def years_root(company):
    return company_dir(company) / "years"

def list_years(company):
    """FY folders present for a company, newest first (e.g. ['2025-26','2024-25'])."""
    r = years_root(company)
    if not r.exists():
        return []
    return sorted((p.name for p in r.iterdir() if p.is_dir()), reverse=True)

def year_dir(company, fy):
    return years_root(company) / str(fy).strip()


# ── Per-year sub-trees ────────────────────────────────────────────────────────
def extracted_dir(company, fy):
    return year_dir(company, fy) / "extracted"

def consolidated_dir(company, fy):
    return year_dir(company, fy) / "consolidated"

def analysis_dir(company, fy):
    return year_dir(company, fy) / "analysis"

def financials_dir(company, fy):
    return year_dir(company, fy) / "financials"

def masters_dir(company, fy):
    return financials_dir(company, fy) / "masters"

def msme_dir(company, fy):
    return year_dir(company, fy) / "msme"

def config_dir(company, fy):
    return year_dir(company, fy) / "config"

def config_path(company, fy, name):
    """A named JSON/file inside the per-year config folder."""
    return config_dir(company, fy) / name


# ── Scaffolding ───────────────────────────────────────────────────────────────
_SUBDIRS = (extracted_dir, consolidated_dir, analysis_dir,
            financials_dir, masters_dir, msme_dir, config_dir)

def ensure_year(company, fy):
    """Create an empty year tree (idempotent). Returns the year_dir Path."""
    for d in _SUBDIRS:
        d(company, fy).mkdir(parents=True, exist_ok=True)
    return year_dir(company, fy)


def latest_year_before(company, fy):
    """Newest existing year strictly older than `fy` (string compare works for
    'YYYY-YY'), or '' if none."""
    prior = [y for y in list_years(company) if y < str(fy).strip()]
    return prior[0] if prior else ''   # list_years is newest-first


def seed_config_from(company, src_fy, dst_fy):
    """Copy a previous year's config (ledger selections, TDS rules) + accounting
    policies forward into a new year. Never overwrites an existing file."""
    if not src_fy or str(src_fy).strip() == str(dst_fy).strip():
        return
    src_cfg, dst_cfg = config_dir(company, src_fy), config_dir(company, dst_fy)
    if src_cfg.exists():
        dst_cfg.mkdir(parents=True, exist_ok=True)
        for f in src_cfg.glob("*.json"):
            dst = dst_cfg / f.name
            if not dst.exists():
                shutil.copy2(f, dst)
    src_pol = financials_dir(company, src_fy) / "policies.json"
    if src_pol.exists():
        dst_pol = financials_dir(company, dst_fy) / "policies.json"
        dst_pol.parent.mkdir(parents=True, exist_ok=True)
        if not dst_pol.exists():
            shutil.copy2(src_pol, dst_pol)


# ── Atomic JSON write (LAN-safe) ──────────────────────────────────────────────
# On a shared network folder a plain open('w') truncates the file first, so a
# crash or another PC reading mid-write can see a half-written / empty file.
# Writing to a temp file in the same folder and os.replace()-ing it over the
# target is atomic on one filesystem (incl. a single SMB share), so a reader
# always sees either the old file or the complete new one — never a torn write.
def atomic_write_json(path, obj, **dump_kw):
    dump_kw.setdefault("indent", 2)
    dump_kw.setdefault("ensure_ascii", False)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp{os.getpid()}")
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(obj, f, **dump_kw)
            f.flush()
            try:
                os.fsync(f.fileno())
            except Exception:
                pass
        os.replace(tmp, path)
    finally:
        try:
            if tmp.exists():
                tmp.unlink()
        except Exception:
            pass


# ── Soft per-company edit lock (LAN multi-user) ───────────────────────────────
# Advisory only: warns when another PC is editing the same company, never blocks.
# A lock older than LOCK_STALE_SECONDS is ignored (treated as abandoned), so a
# crashed/closed app never permanently locks a company.
LOCK_STALE_SECONDS = 180


def company_lock_path(company):
    return company_dir(company) / ".edit_lock.json"


def _whoami():
    try:
        u = getpass.getuser()
    except Exception:
        u = "user"
    try:
        h = socket.gethostname()
    except Exception:
        h = "pc"
    return u, h


def check_company_lock(company):
    """Return the holder dict {user, host, ts, age_s} if a FRESH lock exists,
    else None. Stale locks are ignored."""
    try:
        d = json.loads(company_lock_path(company).read_text(encoding="utf-8"))
        age = time.time() - float(d.get("ts", 0))
        if age <= LOCK_STALE_SECONDS:
            d["age_s"] = int(age)
            return d
    except Exception:
        pass
    return None


def acquire_company_lock(company):
    """Refresh/take THIS PC's edit lock for a company. Returns (ok, other):
    `other` is the foreign holder dict when someone else holds a fresh lock
    (ok is still True — the lock is advisory, callers decide what to warn)."""
    u, h = _whoami()
    other = check_company_lock(company)
    if other and (other.get("user"), other.get("host")) == (u, h):
        other = None
    try:
        atomic_write_json(company_lock_path(company),
                          {"user": u, "host": h, "ts": time.time()})
    except Exception:
        pass
    return True, other


def release_company_lock(company):
    """Drop THIS PC's lock (no-op if someone else now holds it)."""
    u, h = _whoami()
    cur = check_company_lock(company)
    if cur and (cur.get("user"), cur.get("host")) != (u, h):
        return
    try:
        p = company_lock_path(company)
        if p.exists():
            p.unlink()
    except Exception:
        pass

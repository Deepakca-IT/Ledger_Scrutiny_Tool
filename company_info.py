import os
import json
from datetime import datetime
from pathlib import Path

import paths


def get_company_info(company_name: str, fy: str) -> dict:
    """
    Reads the file system to get last extract and consolidate info for a year.
    Returns dict with branch wise extract dates and last consolidate date.
    """
    info = {
        "branches"         : [],
        "last_consolidate" : None,
        "has_data"         : False
    }

    if not company_name or not fy:
        return info

    base_dir = paths.year_dir(company_name, fy)
    if not base_dir.exists():
        return info

    # ── Branch wise extract dates (Group Concern) ─────────────────────────────
    extracted_dir    = paths.extracted_dir(company_name, fy)
    consolidated_dir = paths.consolidated_dir(company_name, fy)
    if extracted_dir.exists():
        txn_files = sorted(
            extracted_dir.glob("*_Transactions.csv"),
            key=lambda f: f.stat().st_mtime,
            reverse=True
        )
        for f in txn_files:
            branch = f.name.replace("_Transactions.csv", "").replace("_", " ")
            modified = datetime.fromtimestamp(f.stat().st_mtime)
            info["branches"].append({
                "branch": branch,
                "date"  : modified.strftime("%d-%b-%Y %I:%M %p")
            })

    # ── Single Company: show last extracted date ──────────────────────────────
    single_txn = consolidated_dir / "Transactions_1.csv"
    if not info["branches"] and single_txn.exists():
        modified = datetime.fromtimestamp(single_txn.stat().st_mtime)
        info["branches"].append({
            "branch": "Single Company",
            "date"  : modified.strftime("%d-%b-%Y %I:%M %p")
        })

    # ── Last consolidate date ─────────────────────────────────────────────────
    log_file = consolidated_dir / "Export_Log.txt"
    conso_master = consolidated_dir / "Conso_MasterData.csv"

    if log_file.exists():
        try:
            with open(log_file, 'r') as f:
                first_line = f.readline().strip()
                # Format: "Export Date: 2026-05-02 10:35:00"
                date_str = first_line.replace("Export Date: ", "").strip()
                conso_dt = datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S.%f")
                info["last_consolidate"] = conso_dt.strftime("%d-%b-%Y %I:%M %p")
        except Exception:
            # Fallback to file modified date
            if conso_master.exists():
                modified = datetime.fromtimestamp(conso_master.stat().st_mtime)
                info["last_consolidate"] = modified.strftime("%d-%b-%Y %I:%M %p")
    elif conso_master.exists():
        modified = datetime.fromtimestamp(conso_master.stat().st_mtime)
        info["last_consolidate"] = modified.strftime("%d-%b-%Y %I:%M %p")

    info["has_data"] = bool(info["branches"]) or bool(info["last_consolidate"])
    return info


# ── Per-year config JSONs (saved under years/<fy>/config/) ────────────────────
def _cfg(company_name: str, fy: str, name: str) -> Path:
    p = paths.config_path(company_name, fy, name)
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _save_list(company_name, fy, name, value):
    paths.atomic_write_json(_cfg(company_name, fy, name), value)


def _load_list(company_name, fy, name):
    p = paths.config_path(company_name, fy, name)
    if p.exists():
        try:
            content = p.read_text().strip()
            return json.loads(content) if content else []
        except Exception:
            return []
    return []


def save_gst_selection(company_name, fy, selected_ledgers):
    _save_list(company_name, fy, "gst_selection.json", selected_ledgers)

def get_gst_selection(company_name, fy):
    return _load_list(company_name, fy, "gst_selection.json")

def save_tds_selection(company_name, fy, selected_ledgers):
    _save_list(company_name, fy, "tds_selection.json", selected_ledgers)

def get_tds_selection(company_name, fy):
    return _load_list(company_name, fy, "tds_selection.json")

def save_excluded_parties(company_name, fy, excluded):
    _save_list(company_name, fy, "excluded_parties.json", excluded)

def get_excluded_parties(company_name, fy):
    return _load_list(company_name, fy, "excluded_parties.json")

def save_related_parties(company_name, fy, selected_ledgers):
    _save_list(company_name, fy, "related_parties.json", selected_ledgers)

def get_related_parties(company_name, fy):
    return _load_list(company_name, fy, "related_parties.json")


def save_analysis_info(company_name, fy, reports):
    paths.atomic_write_json(_cfg(company_name, fy, "analysis_info.json"), {
        "last_run": datetime.now().strftime("%d-%b-%Y %I:%M %p"),
        "reports" : reports,
    })

def get_analysis_info(company_name, fy):
    p = paths.config_path(company_name, fy, "analysis_info.json")
    if p.exists():
        try:
            return json.loads(p.read_text())
        except Exception:
            return {}
    return {}

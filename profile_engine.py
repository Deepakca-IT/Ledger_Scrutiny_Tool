"""Firm / CA profile — stored once per installation (not per company).

Holds the audit firm's name + registration number and the list of CA partners
(name, membership no, designation). The NCE Master Data auditor block lets the
user pick the signing CA from this list and auto-fills firm/FRN/membership, so
those details aren't re-typed for every company.

Stored at ~/Documents/LSTool/profile.json (one level above the per-company data).
"""

import json
import paths


def _profile_path():
    return paths.BASE.parent / "profile.json"


def default_profile():
    return {"firm_name": "", "frn": "", "place": "", "partners": []}
    # partners: [{"name": str, "membership_no": str, "designation": str}]


def load_profile():
    p = _profile_path()
    d = default_profile()
    try:
        if p.exists():
            saved = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(saved, dict):
                d["firm_name"] = str(saved.get("firm_name", "") or "")
                d["frn"] = str(saved.get("frn", "") or "")
                d["place"] = str(saved.get("place", "") or "")
                parts = saved.get("partners")
                if isinstance(parts, list):
                    d["partners"] = [{"name": str(r.get("name", "") or ""),
                                      "membership_no": str(r.get("membership_no", "") or ""),
                                      "designation": str(r.get("designation", "") or "Partner")}
                                     for r in parts if isinstance(r, dict)]
    except Exception:
        pass
    return d


def save_profile(data):
    paths.atomic_write_json(_profile_path(), data)


def partner_names(profile=None):
    profile = profile or load_profile()
    return [p.get("name", "") for p in profile.get("partners", []) if p.get("name")]


def get_partner(profile, name):
    for p in (profile or {}).get("partners", []):
        if p.get("name") == name:
            return p
    return {}

"""
One-time, idempotent migration of a company's data from the old FLAT layout to
the new per-year nested layout (years/<fy>/...).

Old layout                              New layout
----------                              ----------
data/<co>/extracted/                ->  data/<co>/years/<fy>/extracted/
data/<co>/consolidated/             ->  data/<co>/years/<fy>/consolidated/
data/<co>/analysis/                 ->  data/<co>/years/<fy>/analysis/
data/<co>/{gst,tds,excluded,        ->  data/<co>/years/<fy>/config/
          related}_selection.json,
          analysis_info.json,
          tds_rules.json
data/<co>/financials/entity.json    ->  data/<co>/entity.json   (company root)
data/<co>/financials/<x>_<fy>.json  ->  data/<co>/years/<fy>/financials/<x>.json
data/<co>/financials/masters/        -> data/<co>/years/<fy>/financials/masters/master.csv
        master_<fy>.csv
data/<co>/financials/policies.json  ->  data/<co>/years/<cur_fy>/financials/policies.json
data/<co>/financials/grouping.json  ->  data/<co>/years/<cur_fy>/financials/grouping.json
data/<co>/financials/grouping_py.json-> data/<co>/years/<prev_fy>/financials/grouping.json
data/<co>/msme/<x>_<fy>.json|csv    ->  data/<co>/years/<fy>/msme/<x>.json|csv
data/<co>/msme/config.json          ->  data/<co>/years/<cur_fy>/msme/config.json

The single-period scrutiny folders (extracted/consolidated/analysis) and the flat
config JSONs are bucketed under the SCRUTINY year, inferred from the consolidated
transaction dates (falling back to the entity's current FY).

Everything is wrapped in try/except — a migration failure must never crash the app.
A `layout_migrated.flag` marker is written when done so it never re-runs.
"""

import os
import re
import json
import time
import shutil
import glob

import paths

# Flat config JSONs that move into the per-year config/ folder.
_FLAT_CONFIG = ["gst_selection.json", "tds_selection.json", "excluded_parties.json",
                "related_parties.json", "analysis_info.json", "tds_rules.json"]

# financials/<base>_<fy>.json  (suffix-tagged, distribute by year). Map each base
# to its new bare filename (note: 'aux' is a reserved Windows device name).
_FIN_SUFFIXED = {
    "grouping": "grouping.json",
    "aux":      "aux_data.json",
    "far":      "far.json",
    "checks":   "checks.json",
    "partners": "partners.json",
}
# msme/<base>_<fy>.(json|csv)
_MSME_SUFFIXED = ("msme_master", "msme_pending", "msme_verify")

_SUFFIX_RE = re.compile(r"^(?P<base>.+)_(?P<fy>\d{4}-\d{2})\.(?P<ext>json|csv)$")


def _move(src, dst, tries=8):
    """Move a file/dir only if src exists and dst does not (idempotent).

    Resilient to transient anti-virus / cloud-sync file locks on Windows: retries
    a rename, then falls back to copy+delete, with a short backoff between tries.
    """
    if not os.path.exists(src) or os.path.exists(dst):
        return
    last = None
    for _ in range(tries):
        # Re-create the target dir each attempt — on this filesystem an AV/sync
        # filter can momentarily make a freshly-created directory disappear.
        try:
            os.makedirs(os.path.dirname(dst), exist_ok=True)
        except OSError:
            pass
        # 1) atomic rename (fast path)
        try:
            os.rename(src, dst)
            return
        except OSError as e:
            last = e
        # 2) copy + verify + delete fallback (handles transient filter-driver
        #    failures from OneDrive sync / anti-virus on this filesystem).
        try:
            if os.path.isdir(src):
                shutil.copytree(src, dst, dirs_exist_ok=True)
                shutil.rmtree(src, ignore_errors=True)
                return
            # file: prefer copy2, fall back to a manual byte copy
            try:
                shutil.copy2(src, dst)
            except OSError:
                with open(src, "rb") as fi, open(dst, "wb") as fo:
                    fo.write(fi.read())
            # only remove the source once the destination is confirmed intact
            if os.path.exists(dst) and os.path.getsize(dst) == os.path.getsize(src):
                try:
                    os.remove(src)
                except OSError:
                    pass
                return
        except OSError as e:
            last = e
            try:                       # clear a partial dst before retrying
                if os.path.isfile(dst):
                    os.remove(dst)
            except OSError:
                pass
        time.sleep(0.3)
    if last:
        raise last


def _infer_scrutiny_fy(flat_consolidated):
    """Infer the Indian FY ('YYYY-YY') from the max $Date in the consolidated
    transaction files. Returns '' if undeterminable."""
    try:
        import pandas as pd
        files = glob.glob(os.path.join(flat_consolidated, "Transactions_*.csv"))
        mx = None
        for f in files:
            try:
                d = pd.read_csv(f)
            except Exception:
                continue
            if "$Date" not in d.columns:
                continue
            dt = pd.to_datetime(d["$Date"], errors="coerce").max()
            if dt is not None and (mx is None or dt > mx):
                mx = dt
        if mx is None:
            return ""
        y, m = mx.year, mx.month
        start = y if m >= 4 else y - 1
        return f"{start}-{str(start + 1)[-2:]}"
    except Exception:
        return ""


def _legacy_current_prev(company):
    """Read current_fy/previous_fy from entity.json — legacy financials/entity.json
    first, then the migrated company-root location (so a re-run after a partial
    migration still knows the years)."""
    for p in (os.path.join(str(paths.company_dir(company)), "financials", "entity.json"),
              str(paths.entity_path(company))):
        if os.path.exists(p):
            try:
                with open(p, encoding="utf-8") as f:
                    raw = json.load(f)
                return (raw.get("current_fy") or "", raw.get("previous_fy") or "")
            except Exception:
                continue
    return "", ""


def needs_migration(company):
    """True while the company still has ANY flat-layout artefact at its root.

    Independent of the migrated flag: migration is idempotent (it only moves what
    still exists), so re-running while leftovers remain lets a transient move
    failure (filter-driver/AV race) self-heal on a later launch. Empty legacy dirs
    are pruned at the end, so once everything has moved this returns False."""
    root = str(paths.company_dir(company))
    candidates = ["extracted", "consolidated", "analysis", "financials", "msme"] + _FLAT_CONFIG
    return any(os.path.exists(os.path.join(root, c)) for c in candidates)


def migrate_company(company):
    """Idempotent flat -> nested migration for one company. Safe to call every run."""
    try:
        if not company or not needs_migration(company):
            return
        root = str(paths.company_dir(company))
        cur_fy, prev_fy = _legacy_current_prev(company)

        # Scrutiny year: infer from consolidated txns, fall back to entity current FY.
        flat_conso = os.path.join(root, "consolidated")
        scr_fy = _infer_scrutiny_fy(flat_conso) or cur_fy
        scr_known = bool(scr_fy)

        # ── 1. Single-period scrutiny folders -> years/<scr_fy>/ ───────────────
        if scr_known:
            _move(os.path.join(root, "extracted"),    str(paths.extracted_dir(company, scr_fy)))
            _move(os.path.join(root, "consolidated"), str(paths.consolidated_dir(company, scr_fy)))
            _move(os.path.join(root, "analysis"),     str(paths.analysis_dir(company, scr_fy)))
            for name in _FLAT_CONFIG:
                _move(os.path.join(root, name), str(paths.config_path(company, scr_fy, name)))

        # ── 2. financials/ ─────────────────────────────────────────────────────
        fin = os.path.join(root, "financials")
        if os.path.isdir(fin):
            _move(os.path.join(fin, "entity.json"), str(paths.entity_path(company)))
            for fn in os.listdir(fin):
                full = os.path.join(fin, fn)
                if not os.path.isfile(full):
                    continue
                m = _SUFFIX_RE.match(fn)
                if m and m.group("base") in _FIN_SUFFIXED:
                    fy = m.group("fy")
                    _move(full, os.path.join(str(paths.financials_dir(company, fy)),
                                             _FIN_SUFFIXED[m.group("base")]))
            if cur_fy:
                _move(os.path.join(fin, "grouping.json"),
                      os.path.join(str(paths.financials_dir(company, cur_fy)), "grouping.json"))
                _move(os.path.join(fin, "policies.json"),
                      os.path.join(str(paths.financials_dir(company, cur_fy)), "policies.json"))
            elif scr_known:
                _move(os.path.join(fin, "policies.json"),
                      os.path.join(str(paths.financials_dir(company, scr_fy)), "policies.json"))
            if prev_fy:
                _move(os.path.join(fin, "grouping_py.json"),
                      os.path.join(str(paths.financials_dir(company, prev_fy)), "grouping.json"))
            mdir = os.path.join(fin, "masters")
            if os.path.isdir(mdir):
                for fn in os.listdir(mdir):
                    mm = re.match(r"^master_(\d{4}-\d{2})\.csv$", fn)
                    if mm:
                        fy = mm.group(1)
                        _move(os.path.join(mdir, fn),
                              os.path.join(str(paths.masters_dir(company, fy)), "master.csv"))

        # ── 3. msme/ ───────────────────────────────────────────────────────────
        msd = os.path.join(root, "msme")
        if os.path.isdir(msd):
            for fn in os.listdir(msd):
                full = os.path.join(msd, fn)
                if not os.path.isfile(full):
                    continue
                m = _SUFFIX_RE.match(fn)
                if m and m.group("base") in _MSME_SUFFIXED:
                    fy = m.group("fy")
                    _move(full, os.path.join(str(paths.msme_dir(company, fy)),
                                             f"{m.group('base')}.{m.group('ext')}"))
            if cur_fy or scr_known:
                _move(os.path.join(msd, "config.json"),
                      os.path.join(str(paths.msme_dir(company, cur_fy or scr_fy)), "config.json"))

        # ── 4. Remove now-empty legacy dirs + drop the migrated flag ───────────
        for d in ("financials", "msme", "extracted", "consolidated", "analysis"):
            p = os.path.join(root, d)
            if os.path.isdir(p):
                for sub, _, _ in os.walk(p, topdown=False):
                    try:
                        if not os.listdir(sub):
                            os.rmdir(sub)
                    except OSError:
                        pass

        if scr_known or not os.path.exists(os.path.join(root, "consolidated")):
            with open(str(paths.migrated_flag_path(company)), "w", encoding="utf-8") as f:
                f.write("migrated\n")
    except Exception as e:
        # Never let migration break the app; data is preserved (src kept on failure).
        print(f"[migrate] {company}: {e}")


def migrate_all():
    """Migrate every company under the data root (idempotent)."""
    base = str(paths.BASE)
    if not os.path.isdir(base):
        return
    for name in os.listdir(base):
        if os.path.isdir(os.path.join(base, name)):
            migrate_company(name)

"""
tds_rules_engine.py
Manages TDS section mapping per company.
Auto-maps expense ledgers using predefined word rules.
Applies rules to Final Merged Report.
"""

import json
from pathlib import Path

import paths

# ── System Sections (global, editable by user) ────────────────────────────────
SYSTEM_SECTIONS_FILE = paths.SYSTEM_SECTIONS

DEFAULT_SECTIONS = {
    "192"    : {"threshold": 0,       "type": "slab",   "default_rate": None},
    "194A"   : {"threshold": 40000,   "type": "annual", "default_rate": 0.10},
    "194C"   : {"threshold": 30000,   "type": "annual", "default_rate": 0.02},
    "194H"   : {"threshold": 15000,   "type": "annual", "default_rate": 0.05},
    "194I"   : {"threshold": 600000,  "type": "annual", "default_rate": 0.10},
    "194J"   : {"threshold": 50000,   "type": "annual", "default_rate": 0.10},
    "194M"   : {"threshold": 50000,   "type": "annual", "default_rate": 0.05},
    "194Q"   : {"threshold": 5000000, "type": "excess", "default_rate": 0.001},
    "NON-TDS": {"threshold": 0,       "type": "skip",   "default_rate": None}
}

# ── Predefined Word Rules ─────────────────────────────────────────────────────
WORD_RULES = [
    (['rent', 'lease', 'hiring', 'hire charges'],
     '194I', 0.10, 'TDS'),

    (['professional', 'consultation', 'consultancy',
      'legal', 'audit', 'technical', 'advisory',
      'retainer', 'management fees','certificate'],
     '194J', 0.10, 'TDS'),

    (['contract', 'labour', 'work order','transport',
      'fabrication', 'job work', 'sub contract','Maintenance','Courier','freight','loading','packing','forwarding','repair'],
     '194C', None, 'TDS'),  # rate by PAN

    (['interest'],
     '194A', 0.10, 'TDS'),

    (['commission', 'brokerage'],
     '194H', 0.05, 'TDS'),

    (['salary', 'wages', 'remuneration', 'staff','Bonus'],
     '192', None, 'TDS'),  # slab based

    (['dividend'],
     '194', 0.10, 'TDS'),
     
    (['Electricity','eb'],
     '194Q', 0.01, 'TDS'), 

    (['bank charges', 'bank charge', 'round off',
      'rounding','rounded', 'depreciation', 'penalty','phone',
      'late payment', 'bouncing', 'gst', 'tds','insurance',
      ],
     'NON-TDS', 0.0, 'NON-TDS'),
]

WORD_RULES_FILE = paths.WORD_RULES

def get_word_rules() -> list:
    if WORD_RULES_FILE.exists():
        try:
            with open(WORD_RULES_FILE) as f:
                data = json.load(f)
            return [
                (r['keywords'], r['section'], r['rate'], r['type'])
                for r in data
            ]
        except Exception:
            pass
    return WORD_RULES.copy()

def save_word_rules(rules: list):
    WORD_RULES_FILE.parent.mkdir(parents=True, exist_ok=True)
    data = [
        {"keywords": r[0], "section": r[1], "rate": r[2], "type": r[3]}
        for r in rules
    ]
    paths.atomic_write_json(WORD_RULES_FILE, data)
        
def get_merged_rules_df():
    """Returns merged word rules + section thresholds as DataFrame."""
    import pandas as pd
    word_rules = get_word_rules()
    sys_sections = get_system_sections()
    rows = []
    for kws, section, rate, typ in word_rules:
        thresh_info = sys_sections.get(section, {})
        rows.append({
            'Keywords'   : ', '.join(kws) if kws else '',
            'Section'    : section or '',
            'Rate_%'     : round(rate*100, 1) if rate else 0.0,
            'Threshold'  : thresh_info.get('threshold', 0),
            'Type'       : typ or 'TDS'
        })
    return pd.DataFrame(rows)

def save_merged_rules_df(df):
    """Save edited merged DataFrame back to word_rules + system_sections."""
    import pandas as pd
    word_rules = []
    sys_sections = get_system_sections()

    for _, row in df.iterrows():
        kws     = [k.strip().lower() for k in str(row['Keywords']).split(',') if k.strip()]
        section = str(row['Section']).strip().upper()
        rate    = float(row['Rate_%'])/100 if row['Rate_%'] else None
        thresh  = int(row['Threshold']) if row['Threshold'] else 0
        typ     = str(row['Type']).strip()

        word_rules.append((kws, section, rate, typ))

        # Update system sections threshold
        if section:
            if section not in sys_sections:
                sys_sections[section] = {}
            sys_sections[section]['threshold']    = thresh
            sys_sections[section]['type']         = 'skip' if typ == 'NON-TDS' else 'annual'
            sys_sections[section]['default_rate'] = rate

    save_word_rules(word_rules)
    save_system_sections(sys_sections)
    
def reapply_rates_from_word_rules(company_name: str, fy: str):
    """
    Keep existing section mappings but update rates from word rules.
    """
    saved = load_rules(company_name, fy)
    if not saved:
        return
    word_rules = get_word_rules()
    sys_sections = get_system_sections()

    # Build section→rate map from word rules
    section_rate_map = {}
    for kws, section, rate, typ in word_rules:
        if section and rate:
            section_rate_map[section] = rate

    # Also from system sections default_rate
    for sec, info in sys_sections.items():
        if sec not in section_rate_map and info.get('default_rate'):
            section_rate_map[sec] = info['default_rate']

    # Update rates in saved rules
    for ledger, rule in saved.items():
        section = rule.get('section')
        if section and section in section_rate_map:
            saved[ledger]['rate'] = section_rate_map[section]

    save_rules(company_name, saved)


# ── System Sections ───────────────────────────────────────────────────────────
def get_system_sections() -> dict:
    if SYSTEM_SECTIONS_FILE.exists():
        try:
            with open(SYSTEM_SECTIONS_FILE) as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return data
        except Exception:
            pass
    return DEFAULT_SECTIONS.copy()


def save_system_sections(sections: dict):
    paths.atomic_write_json(SYSTEM_SECTIONS_FILE, sections)


def get_flat_threshold(section: str) -> int:
    sections = get_system_sections()
    return sections.get(section, {}).get('threshold', 0)


def get_section_type(section: str) -> str:
    sections = get_system_sections()
    return sections.get(section, {}).get('type', 'annual')


# ── Per Company + Year Rules ──────────────────────────────────────────────────
def get_rules_path(company_name: str, fy: str) -> Path:
    return paths.config_path(company_name, fy, "tds_rules.json")


def load_rules(company_name: str, fy: str) -> dict:
    """Load saved rules. Returns {} if not saved yet."""
    path = get_rules_path(company_name, fy)
    if path.exists():
        try:
            with open(path) as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_rules(company_name: str, fy: str, rules: dict):
    paths.atomic_write_json(get_rules_path(company_name, fy), rules)


def reset_rules(company_name: str, fy: str):
    """Delete saved rules — revert to auto-map."""
    path = get_rules_path(company_name, fy)
    if path.exists():
        path.unlink()


def rules_exist(company_name: str, fy: str) -> bool:
    return get_rules_path(company_name, fy).exists()


# ── Auto-map Logic ────────────────────────────────────────────────────────────
def auto_map_ledger(ledger_name: str) -> dict:
    from difflib import SequenceMatcher
    name_lower = ledger_name.lower()

    def fuzzy_match(word, text, threshold=0.82):
        # Check exact substring first
        if word in text:
            return True
        # Check each word in text for similarity
        for token in text.split():
            ratio = SequenceMatcher(None, word, token).ratio()
            if ratio >= threshold:
                return True
        return False

    for keywords, section, rate, typ in get_word_rules():
        for kw in keywords:
            if fuzzy_match(kw, name_lower):
                return {
                    "section": section,
                    "rate"   : rate,
                    "type"   : typ
                }
    return None


def auto_map_all(expense_ledgers: list) -> dict:
    """
    Auto-map all expense ledgers.
    Returns rules dict.
    """
    rules = {}
    for ledger in expense_ledgers:
        match = auto_map_ledger(ledger)
        if match:
            rules[ledger] = match
        else:
            rules[ledger] = {
                "section": None,
                "rate"   : None,
                "type"   : "Unmapped"
            }
    return rules


def get_effective_rules(company_name: str, fy: str,
                        expense_ledgers: list) -> dict:
    """
    Returns effective rules for company:
    - If saved rules exist → use them
    - New ledgers not in saved rules → mark Unmapped
    - If no saved rules → auto-map all
    """
    if rules_exist(company_name, fy):
        saved = load_rules(company_name, fy)
        # Check for new ledgers not in saved rules
        for ledger in expense_ledgers:
            if ledger not in saved:
                saved[ledger] = {
                    "section": None,
                    "rate"   : None,
                    "type"   : "Unmapped"
                }
        return saved
    else:
        return auto_map_all(expense_ledgers)


# ── Apply Rules to DataFrame ──────────────────────────────────────────────────
def apply_rules_to_df(df, rules: dict):
    """
    Adds Expected_Section, Expected_Rate, Expected_TDS,
    TDS_Variance, Variance_Flag columns to Final Merged Report df.
    194C rate determined by PAN 4th character.
    192 → slab based → blank TDS.
    """
    import pandas as pd

    def get_rate(ledger, pan):
        rule = rules.get(ledger)
        if not rule:
            return None, None, 'Unmapped'

        section = rule.get('section')
        rate    = rule.get('rate')
        typ     = rule.get('type', 'TDS')

        if typ == 'NON-TDS':
            return section, 0.0, 'NON-TDS'

        if section is None:
            return None, None, 'Unmapped'

        # 194C — rate by PAN
        if section == '194C':
            pan_str = str(pan).strip().upper()
            if len(pan_str) >= 4 and pan_str[3] == 'P':
                rate = 0.01  # Individual
            else:
                rate = 0.02  # Company/HUF

        # 192 — slab based
        if section == '192':
            return section, None, 'Slab Based'
            
        # 194Q — TDS only on amount exceeding 50L
        if section == '194Q':
            return section, rate, '194Q_EXCESS'

        return section, rate, typ

    sections, rates, exp_tds, variances, flags = [], [], [], [], []

    for _, row in df.iterrows():
        ledger = row.get('$Particulars', '')
        pan    = row.get('$Led_PAN', '')
        exp_amt = abs(float(row.get('ExpenseAmount', 0) or 0))
        tds_amt = float(row.get('TDSAmount', 0) or 0)

        section, rate, flag = get_rate(ledger, pan)

        if flag == '194Q_EXCESS':
            excess = max(exp_amt - 5000000, 0)
            expected = round(excess * rate, 2) if rate else 0.0
            exp_tds.append(expected)
            variances.append(round(tds_amt - expected, 2))
            flags.append('OK' if expected == tds_amt else ('Short' if tds_amt < expected else 'Excess'))
            sections.append(section)
            rates.append(f"{rate*100:.2f}%" if rate else '')
            continue

        if flag == 'Unmapped':
            sections.append('Unmapped')
            rates.append(None)
            exp_tds.append(None)
            variances.append(None)
            flags.append('Unmapped')

        elif flag == 'NON-TDS':
            sections.append(section)
            rates.append(0.0)
            exp_tds.append(0.0)
            variances.append(tds_amt - 0.0)
            flags.append('NON-TDS')

        elif flag == 'Slab Based':
            sections.append(section)
            rates.append(None)
            exp_tds.append(None)
            variances.append(None)
            flags.append('Slab Based')

        else:
            expected = round(exp_amt * rate, 2) if rate else 0.0
            variance = round(tds_amt - expected, 2)
            vflag = 'OK' if variance == 0 else ('Short' if variance < 0 else 'Excess')
            sections.append(section)
            rates.append(f"{rate*100:.1f}%" if rate else '')
            exp_tds.append(expected)
            variances.append(variance)
            flags.append(vflag)

    df['Expected_Section'] = sections
    df['Expected_Rate']    = rates
    df['Expected_TDS']     = exp_tds
    df['TDS_Variance']     = variances
    df['Variance_Flag']    = flags

    return df


# ── Threshold Rules ───────────────────────────────────────────────────────────
THRESHOLDS = {
    '194J' : {'type': 'annual',      'limit': 50000},
    '194I' : {'type': 'annual',      'limit': 600000},
    '194C' : {'type': 'transaction', 'annual': 100000, 'txn': 30000},
    '194A' : {'type': 'annual',      'limit': 40000},
    '194H' : {'type': 'annual',      'limit': 15000},
    '194Q' : {'type': 'excess',      'limit': 5000000},
    '192'  : {'type': 'slab'},
    'NON-TDS': {'type': 'skip'},
}


def build_advanced_tds_report(merged_df, rules: dict):
    """
    Build Advanced_TDS_Report from Final Merged Report.
    Group by Party + Section.
    Apply threshold logic.
    Returns DataFrame.
    """
    import pandas as pd

    # Skip if no section columns yet
    if 'Expected_Section' not in merged_df.columns:
        return pd.DataFrame()

    # Filter out unmapped and non-tds for grouping
    df = merged_df.copy()
    df = df[~df['Expected_Section'].isin(['Unmapped', None, ''])]

    if df.empty:
        return pd.DataFrame()

    # Ensure numeric
    for col in ['ExpenseAmount', 'TDSAmount', 'TDS_Deposited']:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)

    # Group by Party + PAN + Section
    grp = df.groupby(
        ['$Party_LedName', '$Led_PAN', 'Expected_Section'],
        as_index=False
    ).agg(
        Expense_Heads  = ('$Particulars',
                          lambda x: ' | '.join(sorted(set(x.dropna())))),
        Total_Expense  = ('ExpenseAmount', 'sum'),
        Max_Txn        = ('ExpenseAmount', 'max'),
        TDS_Books      = ('TDSAmount', 'sum'),
        TDS_Winman     = ('TDS_Deposited', 'sum') 
                         if 'TDS_Deposited' in df.columns 
                         else ('TDSAmount', 'sum'),
        Expected_Rate  = ('Expected_Rate', 'first'),
    )

    # Apply threshold and calculate Expected TDS
    exp_tds_list, var_books_list, var_winman_list, flag_list = [], [], [], []

    for _, row in grp.iterrows():
        section     = row['Expected_Section']
        total_exp   = abs(float(row['Total_Expense']))
        max_txn     = abs(float(row['Max_Txn']))
        tds_books   = float(row['TDS_Books'])
        tds_winman  = float(row['TDS_Winman'])
        pan         = str(row['$Led_PAN']).strip().upper()

        # Get rate
        rate_str = str(row.get('Expected_Rate', '') or '')
        try:
            rate = float(rate_str.replace('%', '')) / 100
        except Exception:
            rate = None

        # 194C rate by PAN
        if section == '194C':
            rate = 0.01 if (len(pan) >= 4 and pan[3] == 'P') else 0.02

        thresh = THRESHOLDS.get(section, {'type': 'none'})
        typ    = thresh.get('type', 'none')

        if typ == 'skip' or typ == 'slab':
            exp_tds_list.append(None)
            var_books_list.append(None)
            var_winman_list.append(None)
            flag_list.append('Slab Based' if typ == 'slab' else 'NON-TDS')

        elif typ == 'annual':
            limit = thresh.get('limit', 0)
            if total_exp <= limit:
                exp_tds_list.append(0.0)
                var_books_list.append(round(tds_books - 0.0, 2))
                var_winman_list.append(round(tds_winman - 0.0, 2))
                flag_list.append('Below Threshold')
            else:
                expected = round(total_exp * rate, 2) if rate else 0.0
                vb = round(tds_books - expected, 2)
                vw = round(tds_winman - expected, 2)
                exp_tds_list.append(expected)
                var_books_list.append(vb)
                var_winman_list.append(vw)
                flag_list.append(
                    'OK' if vb == 0 else ('Short' if vb < 0 else 'Excess'))

        elif typ == 'transaction':
            annual_limit = thresh.get('annual', 100000)
            txn_limit    = thresh.get('txn', 30000)
            if max_txn >= txn_limit or total_exp >= annual_limit:
                expected = round(total_exp * rate, 2) if rate else 0.0
                vb = round(tds_books - expected, 2)
                vw = round(tds_winman - expected, 2)
                exp_tds_list.append(expected)
                var_books_list.append(vb)
                var_winman_list.append(vw)
                flag_list.append(
                    'OK' if vb == 0 else ('Short' if vb < 0 else 'Excess'))
            else:
                exp_tds_list.append(0.0)
                var_books_list.append(round(tds_books, 2))
                var_winman_list.append(round(tds_winman, 2))
                flag_list.append('Below Threshold')

        elif typ == 'excess':
            limit = thresh.get('limit', 5000000)
            if total_exp > limit:
                taxable  = total_exp - limit
                expected = round(taxable * rate, 2) if rate else 0.0
                vb = round(tds_books - expected, 2)
                vw = round(tds_winman - expected, 2)
                exp_tds_list.append(expected)
                var_books_list.append(vb)
                var_winman_list.append(vw)
                flag_list.append(
                    'OK' if vb == 0 else ('Short' if vb < 0 else 'Excess'))
            else:
                exp_tds_list.append(0.0)
                var_books_list.append(0.0)
                var_winman_list.append(0.0)
                flag_list.append('Below Threshold')

        else:
            # No threshold — always applicable
            expected = round(total_exp * rate, 2) if rate else 0.0
            vb = round(tds_books - expected, 2)
            vw = round(tds_winman - expected, 2)
            exp_tds_list.append(expected)
            var_books_list.append(vb)
            var_winman_list.append(vw)
            flag_list.append(
                'OK' if vb == 0 else ('Short' if vb < 0 else 'Excess'))

    grp['Expected_TDS']     = exp_tds_list
    grp['Variance_Books']   = var_books_list
    grp['Variance_Winman']  = var_winman_list
    grp['Flag']             = flag_list

    # Final column order
    final_cols = [
        '$Party_LedName', '$Led_PAN', 'Expected_Section',
        'Expected_Rate', 'Expense_Heads', 'Total_Expense',
        'Expected_TDS', 'TDS_Books', 'TDS_Winman',
        'Variance_Books', 'Variance_Winman', 'Flag'
    ]
    grp = grp[[c for c in final_cols if c in grp.columns]]
    grp = grp.rename(columns={
        '$Party_LedName'  : 'Party',
        '$Led_PAN'        : 'PAN',
        'Expected_Section': 'Section',
        'Expected_Rate'   : 'Rate',
    })

    return grp.sort_values('Flag').reset_index(drop=True)
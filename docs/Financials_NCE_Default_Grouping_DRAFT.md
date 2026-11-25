# NCE Financial Statements — Default Grouping Rules (DRAFT for CA review)

Maps each **Tally primary group** (from our extraction) → **ICAI NCE Face Grouping** → **default Note**.
These are the *predefined rules*; the CA can override any ledger in the grouping editor, and
overrides are saved per company and carried forward year-on-year.

Sign convention from TB: **Debit = +, Credit = −**.

---

## A. BALANCE SHEET — Owners' Fund & Liabilities

| Tally Primary Group | Keyword refinement | Face Grouping | Default Note |
|---|---|---|---|
| Capital Account | (default) | Owners' Fund → Capital Account* | **Partners' Current Account** (partnership) / Owner's Capital (proprietor) — user can change |
| Reserves & Surplus | — | Reserves and Surplus | Surplus (P&L balance) / General Reserve |
| Secured Loans | — | Long-term Borrowings | Term loans from banks (secured) |
| Unsecured Loans | — | Long-term Borrowings | Unsecured loans — **user to confirm long-term vs short-term** |
| Loans (Liability) | — | Long-term Borrowings | Borrowings |
| Bank OD A/c | — | Short-term Borrowings | Working-capital loans from banks (secured) |
| Sundry Creditors | — | Trade Payables | Due to Others (MSME / Others split) |
| Duties & Taxes | — | Other Current Liabilities | Statutory dues payable |
| Provisions | name has "tax" | Short-term Provisions | Provision for tax |
| Provisions | (default) | Short-term Provisions | Other provisions |
| Current Liabilities | — | Other Current Liabilities | Other payables |

\* Face name depends on entity type: **Partnership → "Partners' Capital Account"**, **Proprietor → "Owner's Capital Account"**.

## B. BALANCE SHEET — Assets

| Tally Primary Group | Keyword refinement | Face Grouping | Default Note |
|---|---|---|---|
| Fixed Assets | — | Property, Plant and Equipment | Captured from FAR (IT depreciation) |
| Investments | (default) | Non-current Investments | Long-term investments |
| Investments | name has "short"/"mutual fund (liquid)" | Current Investments | Current investments |
| Stock-in-Hand | — | Inventories | As valued & certified by management |
| Sundry Debtors | — | Trade Receivables | Unsecured, considered good |
| Cash-in-Hand | — | Cash and Bank Balances | Cash on hand |
| Bank Accounts | — | Cash and Bank Balances | Balances with banks — current accounts |
| Bank Accounts | name has "deposit"/"FD" | Cash and Bank Balances | Bank deposits |
| Loans & Advances (Asset) | (default) | Short-term Loans and Advances | Advances recoverable in cash/kind |
| Loans & Advances (Asset) | name has "deposit" | Long-term Loans and Advances | Security deposits |
| Deposits (Asset) | — | Long-term Loans and Advances | Security deposits |
| Misc. Expenses (Asset) | — | Other Non-current Assets | Misc. expenditure not written off |
| Current Assets | — | Other Current Assets | Other current assets |

## C. STATEMENT OF P&L — Income

| Tally Primary Group | Keyword refinement | Face Grouping | Default Note |
|---|---|---|---|
| Sales Accounts | — | Revenue from Operations | Sale of products / services |
| Direct Income | — | Revenue from Operations | Other operating revenue |
| Indirect Income | name has "interest" | Other Income | Interest income |
| Indirect Income | (default) | Other Income | Miscellaneous income |

## D. STATEMENT OF P&L — Expenses

| Tally Primary Group | Keyword refinement | Face Grouping | Default Note |
|---|---|---|---|
| Purchase Accounts | — | Purchases of Stock-in-Trade | Purchases (Mfg: Cost of materials consumed) |
| Direct Expenses | — | Direct / Manufacturing Expenses | Power & fuel, wages, etc. |
| Indirect Expenses | salary/wages/bonus/staff/pf/esi/gratuity/welfare | Employee Benefit Expenses | Salaries, wages & bonus / Staff welfare |
| Indirect Expenses | interest/bank charge/finance/processing fee | Finance Costs | Interest expense / Bank charges |
| Indirect Expenses | depreciation/amortization | Depreciation and Amortization | (from FAR) |
| Indirect Expenses | (default) | Other Expenses | (by ledger name) |

## E. Special / computed (not direct ledger maps)
- **Changes in Inventories** (Opening − Closing stock) — computed for trading/manufacturing P&L.
- **Depreciation** — comes from the IT-depreciation FAR module, not from a TB ledger.
- **Profit/Loss for the year** — flows to Reserves & Surplus / Partners' Capital.

---

### Decisions (confirmed by CA)
1. **Direct Expenses** — keep as a separate **Direct/Manufacturing Expenses** head; user can change.
2. **Partner accounts** — default Note = **Partners' Current Account**; user can change to Capital.
3. **Unsecured Loans** — do not auto long/short; **user selects** (default long-term, flagged for review).
4. No house-style name changes for now.

### Confirmed MVP scope
The MVP is the **TB grouping/mapping editor only**: load the TB, let the user review each ledger,
and select **Face + Note + Sub-Note together in one go** (so the notes are also ready) — with the
predefined defaults applied first. Mapping is saved and carried forward (not redone yearly).
BS / P&L / Notes generation, the Financials viewer, and PDF export come *after* mapping is solid.

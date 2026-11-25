# Tally TDL files

| File | Purpose | Status |
|---|---|---|
| `DB_Mini_with_LiteV4.tdl` | Provides `DB_Mini` and `DB_Lite` | Earlier version |
| `DB_Mini_with_LiteV4_1.tdl` | Same, plus the supplier's invoice number (`Supplier_VchNo`) | Newer version, to be confirmed by testing |
| `LSToolContext.tdl` | Shows the active company to the tool | Under test |

**Load only one `DB_Mini` file at a time.** Both define the same collections.

Optional and cancelled vouchers are both excluded (rule corrected November 2026; test in Tally before release).

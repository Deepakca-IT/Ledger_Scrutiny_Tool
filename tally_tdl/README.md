# Tally TDL files

| File | Purpose | Status |
|---|---|---|
| `DB_Mini_with_LiteV4_1.tdl` | Provides `DB_Mini` and `DB_Lite`, including the supplier's invoice number | **Required** |
| `LSToolContext.tdl` | Shows the active company to the tool | Optional, under test |

Load only this version of `DB_Mini` and remove any older copy from Tally, because they define the same collections.

Optional and cancelled vouchers are excluded.

"""Prefilled NCE disclosures — Entity Information (Note 1) and Significant
Accounting Policies (Note 2). Each policy head has a default Disclose flag and
standard ICAI-style text the user can edit. Only disclosed heads that have text
(or a table) are rendered, lettered a, b, c… in order.

`fs_engine.load_policies/save_policies` resolve these defaults against the
company's saved overrides; `fs_reports` renders Notes 1–2; the Disclosures tab
edits them.
"""

# Note 1 — Entity Information (editable single block).
DEFAULT_ENTITY_INFO = (
    "The firm was commenced on __/__/____ to carry on the business of ____."
)

# Note 2 — Significant Accounting Policies.
# (key, head, default_disclose, default_text). Order = presentation order.
DEFAULT_POLICIES = [
    ("basis_of_preparation", "Basis of Preparation", True,
     "The firm follows mercantile system of accounting and recognizes significant "
     "items of income and expenses on accrual basis."),
    ("use_of_estimates", "Use of Estimates", False,
     "The preparation of financial statements in conformity with generally accepted "
     "accounting principles requires the management to make estimates and assumptions "
     "that affect the reported amounts of assets and liabilities and disclosure of "
     "contingent liabilities as at the date of the financial statements, and the "
     "reported amounts of income and expenses during the reporting period. Actual "
     "results could differ from those estimates; any revision to such estimates is "
     "recognised in the period in which the same is determined."),
    ("ppe", "Property, Plant and Equipment", True,
     "Fixed Assets are stated at cost less depreciation."),
    ("intangibles", "Intangible assets", False,
     "Intangible assets are stated at cost of acquisition less accumulated "
     "amortisation. They are amortised over their estimated useful lives on a "
     "straight-line basis."),
    ("depreciation", "Depreciation and amortization", True,
     "Depreciation has been provided on the Fixed Asset as per the rate specified in "
     "the Income Tax Act, 1961."),
    ("impairment", "Impairment of assets", False,
     "At each balance sheet date, the management reviews the carrying amounts of its "
     "assets included in each cash generating unit to determine whether there is any "
     "indication that those assets were impaired. If any such indication exists, the "
     "recoverable amount of the asset is estimated in order to determine the extent of "
     "impairment. Recoverable amount is the higher of an asset's net selling price and "
     "value in use. In assessing value in use, the estimated future cash flows expected "
     "from the continuing use of the asset and from its disposal are discounted to their "
     "present value using a pre-tax discount rate that reflects the current market "
     "assessments of time value of money and the risks specific to the asset. Reversal "
     "of impairment loss is recognised as income in the statement of profit and loss."),
    ("leases", "Leases", False,
     "Assets taken on lease by the entity in its capacity as lessee, where the entity "
     "has substantially all the risks and rewards of ownership are classified as finance "
     "lease. Such a lease is capitalised at the inception of the lease at lower of the "
     "fair value or the present value of the minimum lease payments and a liability is "
     "recognised for an equivalent amount. Each lease rental paid is allocated between "
     "the liability and the interest cost so as to obtain a constant periodic rate of "
     "interest on the outstanding liability for each year.\n"
     "Lease arrangements where the risks and rewards incidental to ownership of an asset "
     "substantially vest with the lessor, are recognised as operating leases. Lease "
     "rentals under operating leases are recognised in the statement of profit and loss "
     "on a straight-line basis."),
    ("investment", "Investment", True,
     "The firm does not hold any investment as on the date of balance sheet."),
    ("inventories", "Inventories", True,
     "The valuation for inventories is as follows;"),
    ("cash", "Cash and cash equivalents", False,
     "The entity considers all highly liquid financial instruments, which are readily "
     "convertible into known amount of cash that are subject to an insignificant risk of "
     "change in value and having original maturities of three months or less from the "
     "date of purchase, to be cash equivalents."),
    ("revenue", "Revenue recognition", True,
     "Sales are accounted on accrual basis when the sales of goods are completed or on "
     "raising of invoices whichever is earlier. Sales exclude GST and other taxes."),
    ("employee_benefits", "Employee Benefits", False,
     "Contributions to defined contribution retirement benefit schemes are recognised as "
     "expense when employees have rendered services entitling them to such benefits. The "
     "undiscounted amount of short-term employee benefits expected to be paid in exchange "
     "for the services rendered by employees is recognised during the period when the "
     "employee renders the service."),
    ("borrowing_cost", "Borrowing Cost", False,
     "Borrowing costs that are directly attributable to the acquisition, construction or "
     "production of a qualifying asset are capitalised as part of the cost of that asset. "
     "Other borrowing costs are recognised as an expense in the period in which they are "
     "incurred."),
    ("rnd", "Research and Development Expenses", False, ""),
    ("forex", "Foreign currency transactions", True,
     "There was no foreign currency transaction during the year under review."),
    ("current_tax", "Current Tax", True,
     "Income tax payable in India is determined in accordance with the provisions of the "
     "Income Tax Act, 1961 but not charged to the Profit and Loss Account."),
    ("deferred_tax", "Deferred Tax", True,
     "Provision of deferred tax is not considered in books of account."),
    ("segment", "Segment accounting", True, ""),
    ("government_grants", "Government Grants", False, ""),
    ("provisions", "Provisions, Contingent liabilities and Contingent assets", True,
     "Provisions involving substantial degree of estimation in measurement are "
     "recognized. Contingent Assets or Liabilities are neither recognized or disclosed "
     "in the financial statements."),
]

# Policies that carry a structured sub-table, and the table's default rows.
# (Only Inventories for now — valuation policy by classification.)
DEFAULT_TABLES = {
    "inventories": {
        "columns": ["classification", "policy"],
        "headers": ["Classification", "Valuation Policy"],
        "rows": [{"classification": "Finished Goods",
                  "policy": "At lower of cost or net realizable value."}],
    },
}

POLICY_HEADS = [p[1] for p in DEFAULT_POLICIES]

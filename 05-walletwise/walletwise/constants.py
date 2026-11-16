"""Fixed lists WalletWise uses everywhere: transaction types, categories, accounts."""

APP_NAME = "WalletWise"
CURRENCY = "PKR"

# Transaction types
INCOME = "Income"
EXPENSE = "Expense"
TRANSFER_IN = "Transfer In"
TRANSFER_OUT = "Transfer Out"
TYPES = [INCOME, EXPENSE, TRANSFER_IN, TRANSFER_OUT]

# Money coming in (+) or going out (-) of an account
SIGN = {INCOME: 1, TRANSFER_IN: 1, EXPENSE: -1, TRANSFER_OUT: -1}

INCOME_CATEGORIES = ["Salary", "Freelance", "Side Income", "Pocket Money", "Gift Received"]
EXPENSE_CATEGORIES = [
    "Food & Snacks",
    "Mobile & Internet",
    "University & Books",
    "Transport",
    "Personal Care",
    "Family & Gifts",
    "Fun & Outings",
    "Learning & Tools",
    "Health & Medicine",
    "Other",
]
TRANSFER_CATEGORIES = ["Transfer", "Investment"]
CATEGORIES = INCOME_CATEGORIES + EXPENSE_CATEGORIES + TRANSFER_CATEGORIES

# Money you earned yourself (not pocket money or gifts)
EARNED_CATEGORIES = ["Salary", "Freelance", "Side Income"]

NEED = "Need"
WANT = "Want"
NEED_WANT = [NEED, WANT]

ACCOUNT_KINDS = ["Cash", "Bank", "Wallet", "Investment", "Other"]

# Coaching rules (student version)
MONTHLY_WANTS_CAP = 1000        # keep wants around this while there is no job
EMERGENCY_FUND_MONTHS = 3       # emergency fund = 3x average monthly spending

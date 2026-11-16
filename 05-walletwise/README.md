# 💼 WalletWise

A personal money manager that knows your whole money story, from the first rupee to today, and gives you suggestions based on it.

Pure Python 3 standard library (`sqlite3`, `csv`, `argparse`). Nothing to install.

## ✨ What it does

| Feature | Command |
|---|---|
| Add income / expenses (asks you questions step by step) | `python main.py add` |
| Move money between your own accounts (e.g. cash → bank, bank → investment) | `python main.py transfer "Cash" "Bank" 2000` |
| See balances and net worth | `python main.py balance` |
| Monthly summary with budgets | `python main.py summary --all` |
| Your money story: milestones + a chapter for every month | `python main.py story` |
| Personal suggestions from your data | `python main.py suggest` |
| Monthly budgets | `python main.py budget set "Food & Snacks" 1500` |
| Savings goals linked to an account | `python main.py goal add "Emergency Fund" 30000 --account "Bank"` |
| Import / export CSV | `python main.py import file.csv` · `python main.py export backup.csv` |

Run `python main.py` with no command for a simple menu.

## 🚀 Quick start

```bash
cd 05-walletwise

# 1. Add your accounts with the balance they had on the day you start tracking
python main.py account add "Physical Cash" --kind Cash --opening 500 --date 2026-11-14
python main.py account add "Bank" --kind Bank --opening 10000 --date 2026-11-14

# 2. Bring in your history (or try the sample data)
python main.py import sample_data/sample_transactions.csv

# 3. Explore
python main.py story
python main.py suggest
```

### Importing from a Google Sheet / Claude Sheet

Download the **Transactions** tab as CSV and run `python main.py import Transactions.csv`.
Columns: `Date, Type, Category, Amount (PKR), Account, Note, Need / Want`.
Amounts like `PKR 12,000` and dates like `11/14/2026` both work, and importing the same file again skips rows that are already saved.

## 🧠 How suggestions work

`walletwise/advisor.py` has a list of small **rules**. Each rule looks at your transactions and returns suggestions, for example:

- 🔴 / 🟡 a category over or close to its budget
- ⚠️ a month where you spent more than you got
- 📝 starting budgets worked out from your real spending (wants trimmed by 20%)
- 🎯 your biggest spending category and 🔁 your most repeated spend (e.g. rides)
- 📈 a category that jumped compared with the month before
- 🛡️ emergency-fund progress against 3× your average monthly spending
- 💡 how much of your income you earned yourself
- 📅 your most expensive weekday, 🏦 bank fees, 🌱 no-spend days

To add your own idea, write a function `def my_rule(ctx) -> list[Suggestion]` and add it to `RULES`.

## 🔒 Privacy

Your data is stored in `data/walletwise.db`. The `data/` folder is in `.gitignore`, so **your real money data never gets pushed to GitHub**. Only the fake `sample_data/` is in the repo.
Use `--db path/to/file.db` (or the `WALLETWISE_DB` environment variable) to keep the database somewhere else.

## 🧪 Tests

```bash
cd 05-walletwise
python -m unittest discover -s tests -v
```

## 📁 Structure

```
05-walletwise/
├── main.py               # entry point
├── walletwise/
│   ├── constants.py      # types, categories, coaching rules
│   ├── db.py             # SQLite storage + data classes
│   ├── reports.py        # totals, months, balances
│   ├── advisor.py        # suggestion rules
│   ├── story.py          # your money story
│   ├── csv_io.py         # import / export
│   └── cli.py            # commands and menu
├── sample_data/          # fake example data
└── tests/
```

## 🗺️ Roadmap

- [x] **Step 1:** CLI + SQLite, budgets, goals, story, rule-based suggestions
- [ ] **Step 2:** charts with `matplotlib`
- [ ] **Step 3:** web app (Streamlit/Flask) to use from the phone
- [ ] **Step 4:** AI-powered suggestions

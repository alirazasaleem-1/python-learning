# 💼 WalletWise

A personal money manager that knows your whole money story, from the first rupee to today, and gives you suggestions based on it.

It has two sides:
- **💬 WalletWise AI**: a chat assistant powered by Claude. Talk to it in English, Urdu or Roman Urdu: it logs your spending, answers questions about your money and gives advice based on your real history.
- **🧮 Classic commands**: a fast command-line tracker with reports, a money story and rule-based suggestions. Pure Python standard library, works offline.

## 💬 WalletWise AI

```bash
pip install -r requirements.txt          # installs the anthropic SDK
setx ANTHROPIC_API_KEY "sk-ant-..."      # Windows (open a new terminal after)
python main.py chat
```

```
🧑 You: aaj 250 ka lunch cash se kiya aur 120 ka rickshaw
   ❓ Save this? 16 Nov 2026 · Expense · PKR 250 · Food & Snacks · Physical Cash · Need · Lunch (y/n): y
   ❓ Save this? 16 Nov 2026 · Expense · PKR 120 · Transport · Physical Cash · Need · Rickshaw (y/n): y
💼 Dono save ho gaye ✅ Cash ab PKR 60 bacha hai...

🧑 You: can I afford a 5000 PKR course next month?
🧑 You: why did I overspend in October?
🧑 You: I got an internship, 15000 a month from December
   📝 Remembered: Starts an internship in December paying PKR 15,000/month
```

**How it works** (`walletwise/assistant.py`, `walletwise/tools.py`)
- At the start of every chat Claude gets your **whole money story**: every transaction, balances, budgets, goals, month-by-month totals, the rule-based insights, and its **long-term memory** of you.
- It has **tools** to search transactions, build spending reports, log income/expenses, move money between accounts, set budgets and goals, and remember or forget facts about you.
- **Nothing is saved without your OK.** Every change asks `(y/n)` first.
- Memories live in your local database (`/memory` shows them, `/forget <id>` deletes one).
- Chat commands: `/memory`, `/forget <id>`, `/new`, `/help`, `/exit`.

**Cost:** each message costs a little API credit (with prompt caching, usually around 1-3 US cents on the default model).
Settings via environment variables: `WALLETWISE_MODEL` (default `claude-opus-5-5`) and `WALLETWISE_EFFORT` (`low`/`medium`/`high`, default `medium`).

## 🧮 Classic commands

Pure Python 3 standard library (`sqlite3`, `csv`, `argparse`). Nothing to install.

## ✨ What it does

| Feature | Command |
|---|---|
| 💬 Chat with the AI | `python main.py chat` |
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

Your data (transactions, AI memories) is stored in `data/walletwise.db`. The `data/` folder is in `.gitignore`, so **your real money data never gets pushed to GitHub**. Only the fake `sample_data/` is in the repo. When you use the AI chat, your money data is sent to the Anthropic API to answer you.
Use `--db path/to/file.db` (or the `WALLETWISE_DB` environment variable) to keep the database somewhere else.

## 🧪 Tests

```bash
cd 05-walletwise
python -m unittest discover -s tests -v     # no API key needed: the AI tests use a fake client
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
│   ├── tools.py          # what the AI can look up and change
│   ├── assistant.py      # the Claude chat loop + money snapshot
│   └── cli.py            # commands and menu
├── sample_data/          # fake example data
└── tests/
```

## 🗺️ Roadmap

- [x] **Step 1:** CLI + SQLite, budgets, goals, story, rule-based suggestions
- [x] **Step 2:** WalletWise AI chat with tools and long-term memory
- [ ] **Step 3:** charts with `matplotlib`
- [ ] **Step 4:** web app (Streamlit/Flask) to chat from the phone

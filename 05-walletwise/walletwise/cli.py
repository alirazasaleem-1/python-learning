"""Command-line interface for WalletWise.

Run `python main.py` for the menu, or `python main.py <command> --help` for one command.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from typing import List, Optional, Sequence

from . import advisor, csv_io, reports, story
from .constants import (
    ACCOUNT_KINDS, APP_NAME, CATEGORIES, EXPENSE, EXPENSE_CATEGORIES, INCOME,
    INCOME_CATEGORIES, NEED_WANT, TRANSFER_CATEGORIES, TRANSFER_IN, TRANSFER_OUT, TYPES,
)
from .db import Account, Database, Goal, Transaction
from .reports import month_name, pkr


# ---------------------------------------------------------------- helpers

def table(headers: Sequence[str], rows: List[Sequence[object]]) -> str:
    cells = [[str(c) for c in headers]] + [[str(c) for c in r] for r in rows]
    widths = [max(len(r[i]) for r in cells) for i in range(len(headers))]
    lines = ["  ".join(c.ljust(w) for c, w in zip(row, widths)) for row in cells]
    lines.insert(1, "  ".join("-" * w for w in widths))
    return "\n".join(lines)


def choose(prompt: str, options: List[str], allow_blank: bool = False) -> str:
    for i, opt in enumerate(options, 1):
        print(f"  {i:>2}. {opt}")
    while True:
        answer = input(f"{prompt}{' (Enter to skip)' if allow_blank else ''}: ").strip()
        if not answer and allow_blank:
            return ""
        if answer.isdigit() and 1 <= int(answer) <= len(options):
            return options[int(answer) - 1]
        matches = [o for o in options if o.lower() == answer.lower()]
        if matches:
            return matches[0]
        print("  Please type a number from the list.")


def ask(prompt: str, default: str = "") -> str:
    answer = input(f"{prompt}{f' [{default}]' if default else ''}: ").strip()
    return answer or default


def ask_amount(prompt: str) -> float:
    while True:
        try:
            return csv_io.parse_amount(ask(prompt))
        except ValueError:
            print("  Please type a number, e.g. 250")


def categories_for(txn_type: str) -> List[str]:
    if txn_type == INCOME:
        return INCOME_CATEGORIES
    if txn_type == EXPENSE:
        return EXPENSE_CATEGORIES
    return TRANSFER_CATEGORIES


def account_names(db: Database) -> List[str]:
    return [a.name for a in db.accounts()]


def check(value: str, allowed: List[str], what: str) -> str:
    for a in allowed:
        if a.lower() == value.lower():
            return a
    raise SystemExit(f"❌ Unknown {what} '{value}'. Choose one of: {', '.join(allowed)}")


def balance_line(db: Database, name: str) -> str:
    acc = next((a for a in db.accounts() if a.name == name), None)
    if not acc:
        return ""
    return f"   {name} balance: {pkr(reports.account_balance(acc, db.transactions()))}"


# ---------------------------------------------------------------- commands

def cmd_add(db: Database, args) -> None:
    interactive = args.amount is None
    txn_type = args.type and check(args.type, TYPES, "type")
    if not txn_type:
        txn_type = choose("Type", [INCOME, EXPENSE])
    category = args.category and check(args.category, CATEGORIES, "category")
    if not category:
        category = choose("Category", categories_for(txn_type))
    amount = args.amount if args.amount is not None else ask_amount("Amount (PKR)")
    accounts = account_names(db)
    account = args.account or ""
    if accounts and account:
        account = check(account, accounts, "account")
    elif accounts and interactive:
        account = choose("Account", accounts, allow_blank=True)
    note = args.note if args.note is not None else (ask("Note") if interactive else "")
    need_want = args.need or ""
    if need_want:
        need_want = check(need_want, NEED_WANT, "need/want")
    elif txn_type == EXPENSE and interactive:
        need_want = choose("Need or Want", NEED_WANT)
    day = csv_io.parse_date(args.date) if args.date else date.today()

    t = Transaction(day, txn_type, category, amount, account, note, need_want)
    txn_id = db.add_transaction(t)
    print(f"✅ Saved #{txn_id}: {day:%d %b} {txn_type} {pkr(amount)} · {category}"
          f"{' · ' + account if account else ''}{' · ' + need_want if need_want else ''}")
    if account:
        print(balance_line(db, account))
    budget = next((b for b in db.budgets() if b.category == category), None)
    if budget and txn_type == EXPENSE:
        spent = reports.spending_by_category(
            reports.in_month(db.transactions(), reports.month_key(date.today()))).get(category, 0)
        print(f"   {category} budget: {pkr(spent)} of {pkr(budget.monthly_limit)} used")


def cmd_transfer(db: Database, args) -> None:
    accounts = account_names(db)
    source = check(args.source, accounts, "account")
    target = check(args.target, accounts, "account")
    category = check(args.category, TRANSFER_CATEGORIES, "category")
    day = csv_io.parse_date(args.date) if args.date else date.today()
    note = args.note or f"{source} → {target}"
    db.add_transaction(Transaction(day, TRANSFER_OUT, category, args.amount, source, note))
    db.add_transaction(Transaction(day, TRANSFER_IN, category, args.amount, target, note))
    print(f"✅ Moved {pkr(args.amount)} from {source} to {target}")
    print(balance_line(db, source))
    print(balance_line(db, target))


def cmd_list(db: Database, args) -> None:
    txns = db.transactions()
    if args.month:
        txns = reports.in_month(txns, args.month)
    txns = txns[-args.last:] if args.last else txns
    if not txns:
        print("No transactions yet.")
        return
    rows = [(t.id, f"{t.date:%d %b %Y}", t.type, t.category, pkr(t.amount), t.account or "-",
             t.need_want or "-", t.note[:40]) for t in txns]
    print(table(["#", "Date", "Type", "Category", "Amount", "Account", "N/W", "Note"], rows))


def cmd_delete(db: Database, args) -> None:
    sure = args.yes or ask(f"Delete transaction #{args.id}? (y/n)", "n").lower() == "y"
    if not sure:
        print("Cancelled.")
    elif db.delete_transaction(args.id):
        print(f"🗑️ Deleted #{args.id}")
    else:
        print(f"No transaction #{args.id}")


def cmd_balance(db: Database, args) -> None:
    accounts = db.accounts()
    if not accounts:
        print('No accounts yet. Add one: python main.py account add "Physical Cash" --kind Cash --opening 500')
        return
    bal = reports.balances(accounts, db.transactions())
    net = sum(bal.values())
    rows = [(a.name, a.kind, pkr(bal[a.name]), f"{bal[a.name] / net:.0%}" if net else "-", a.note)
            for a in accounts]
    print(table(["Account", "Kind", "Balance", "Share", "Note"], rows))
    print(f"\n💰 Net worth: {pkr(net)}")


def cmd_summary(db: Database, args) -> None:
    txns = db.transactions()
    key = args.month or reports.month_key(date.today())
    month = reports.in_month(txns, key)
    t = reports.totals(month)
    print(f"📊 {month_name(key)}")
    print(f"   Income  {pkr(t.income):>12}   (earned yourself: {pkr(t.earned)})")
    print(f"   Spent   {pkr(t.spent):>12}   (needs {pkr(t.needs)} · wants {pkr(t.wants)})")
    rate = f"  ({t.savings_rate:.0%} savings rate)" if t.savings_rate is not None else ""
    print(f"   Saved   {pkr(t.saved):>12}{rate}")
    cats = reports.spending_by_category(month)
    budgets = {b.category: b.monthly_limit for b in db.budgets()}
    if cats or budgets:
        print()
        rows = []
        for cat in list(cats) + [c for c in budgets if c not in cats]:
            spent = cats.get(cat, 0)
            limit = budgets.get(cat)
            status = "-" if limit is None else ("🔴 Over" if spent > limit else
                                                "🟡 Close" if spent >= 0.8 * limit else "🟢 OK")
            rows.append((cat, pkr(spent), pkr(limit) if limit is not None else "-", status))
        print(table(["Category", "Spent", "Limit", "Status"], rows))
    if args.all:
        print("\n📅 Month by month")
        rows = [(month_name(m), pkr(v.income), pkr(v.spent), pkr(v.saved))
                for m, v in reports.monthly_totals(txns).items()]
        print(table(["Month", "Income", "Spent", "Net"], rows))


def cmd_story(db: Database, args) -> None:
    print(story.tell(db.transactions(), db.accounts()))


def cmd_suggest(db: Database, args) -> None:
    tips = advisor.suggest(db.transactions(), db.accounts(), db.budgets(), db.goals())
    if not tips:
        print("Add a few transactions first, then I can give you suggestions.")
        return
    print(f"🧠 {APP_NAME} suggestions\n")
    for s in tips[: args.top] if args.top else tips:
        print(f"{s.icon} {s.title}")
        for line in s.detail.splitlines():
            print(f"   {line}")
        print()
    print("Not financial advice: these are patterns from your own data.")


def cmd_budget(db: Database, args) -> None:
    if args.action == "set":
        category = check(args.category, EXPENSE_CATEGORIES, "category")
        db.set_budget(category, args.limit)
        print(f"✅ {category} limit set to {pkr(args.limit)} a month")
    args.month, args.all = None, False
    cmd_summary(db, args)


def cmd_goal(db: Database, args) -> None:
    if args.action == "add":
        account = check(args.account, account_names(db), "account") if args.account else ""
        db.save_goal(Goal(args.name, args.target, account, args.by or "", args.note or ""))
        print(f"✅ Goal saved: {args.name} ({pkr(args.target)})")
    goals = db.goals()
    if not goals:
        print('No goals yet. Example: python main.py goal add "Emergency Fund" 30000 --account "Bank"')
        return
    bal = reports.balances(db.accounts(), db.transactions())
    rows = []
    for g in goals:
        saved = bal.get(g.account, 0)
        pct = min(saved / g.target, 1) if g.target else 0
        bar = "█" * int(pct * 10) + "░" * (10 - int(pct * 10))
        rows.append((g.name, pkr(g.target), pkr(saved), f"{bar} {pct:.0%}", g.target_date or "-", g.account or "-"))
    print(table(["Goal", "Target", "Saved", "Progress", "By", "Account"], rows))


def cmd_account(db: Database, args) -> None:
    if args.action == "add":
        kind = check(args.kind, ACCOUNT_KINDS, "kind")
        opened = csv_io.parse_date(args.date) if args.date else date.today()
        db.save_account(Account(args.name, kind, args.opening, opened, args.note or ""))
        print(f"✅ Account saved: {args.name} (opening {pkr(args.opening)} on {opened:%d %b %Y})")
    cmd_balance(db, args)


def cmd_import(db: Database, args) -> None:
    added, skipped, errors = csv_io.import_csv(db, args.file)
    print(f"✅ Imported {added} transaction(s), skipped {skipped} already saved.")
    for e in errors:
        print(f"   ⚠️ {e}")


def cmd_export(db: Database, args) -> None:
    n = csv_io.export_csv(db, args.file)
    print(f"✅ Exported {n} transaction(s) to {args.file}")


# ---------------------------------------------------------------- menu

MENU = [
    ("Add income / expense", "add"),
    ("Move money between accounts", "transfer"),
    ("Recent transactions", "list"),
    ("Balances", "balance"),
    ("This month's summary", "summary"),
    ("My money story", "story"),
    ("Suggestions", "suggest"),
    ("Goals", "goal"),
]


def menu(db: Database, parser: argparse.ArgumentParser) -> None:
    while True:
        print(f"\n===== 💼 {APP_NAME} =====")
        for i, (label, _) in enumerate(MENU, 1):
            print(f"  {i}. {label}")
        print("  0. Exit")
        choice = input("Choose: ").strip()
        if choice == "0" or choice.lower() in ("q", "exit"):
            print("Khuda Hafiz! 👋")
            return
        if not choice.isdigit() or not 1 <= int(choice) <= len(MENU):
            print("Please choose a number from the menu.")
            continue
        command = MENU[int(choice) - 1][1]
        argv = [command]
        if command == "transfer":
            names = account_names(db)
            if len(names) < 2:
                print("Add at least two accounts first (python main.py account add ...).")
                continue
            source = choose("From", names)
            target = choose("To", [n for n in names if n != source])
            argv += [source, target, str(ask_amount("Amount (PKR)"))]
        elif command == "list":
            argv += ["--last", "15"]
        print()
        try:
            run(db, parser.parse_args(argv))
        except SystemExit as e:
            if e.code not in (0, None):
                print(e)


# ---------------------------------------------------------------- parser

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="walletwise", description=f"💼 {APP_NAME}: your personal money manager")
    p.add_argument("--db", help="path to the database file (default: data/walletwise.db)")
    sub = p.add_subparsers(dest="command")

    a = sub.add_parser("add", help="add income or an expense (asks questions if you leave things out)")
    a.add_argument("--type", help="Income or Expense")
    a.add_argument("--category")
    a.add_argument("--amount", type=csv_io.parse_amount)
    a.add_argument("--account")
    a.add_argument("--note")
    a.add_argument("--need", help="Need or Want (expenses)")
    a.add_argument("--date", help="YYYY-MM-DD (default: today)")

    t = sub.add_parser("transfer", help="move money between two of your accounts")
    t.add_argument("source")
    t.add_argument("target")
    t.add_argument("amount", type=csv_io.parse_amount)
    t.add_argument("--category", default="Transfer", help="Transfer or Investment")
    t.add_argument("--note")
    t.add_argument("--date")

    ls = sub.add_parser("list", help="show transactions")
    ls.add_argument("--month", help="YYYY-MM")
    ls.add_argument("--last", type=int, default=20, help="only the last N (0 = all)")

    d = sub.add_parser("delete", help="delete a transaction by its #")
    d.add_argument("id", type=int)
    d.add_argument("-y", "--yes", action="store_true")

    sub.add_parser("balance", help="account balances and net worth")

    s = sub.add_parser("summary", help="income, spending and budgets for a month")
    s.add_argument("--month", help="YYYY-MM (default: this month)")
    s.add_argument("--all", action="store_true", help="also show every month")

    sub.add_parser("story", help="your money story from start to today")

    sg = sub.add_parser("suggest", help="personal suggestions from your data")
    sg.add_argument("--top", type=int, default=0, help="show only the top N")

    b = sub.add_parser("budget", help="show or set monthly budgets")
    bsub = b.add_subparsers(dest="action")
    bs = bsub.add_parser("set")
    bs.add_argument("category")
    bs.add_argument("limit", type=csv_io.parse_amount)

    g = sub.add_parser("goal", help="show or add savings goals")
    gsub = g.add_subparsers(dest="action")
    ga = gsub.add_parser("add")
    ga.add_argument("name")
    ga.add_argument("target", type=csv_io.parse_amount)
    ga.add_argument("--account", help="the account that holds this goal's money")
    ga.add_argument("--by", help="target date YYYY-MM-DD")
    ga.add_argument("--note")

    ac = sub.add_parser("account", help="show or add accounts")
    asub = ac.add_subparsers(dest="action")
    aa = asub.add_parser("add")
    aa.add_argument("name")
    aa.add_argument("--kind", default="Cash", help=", ".join(ACCOUNT_KINDS))
    aa.add_argument("--opening", type=csv_io.parse_amount, default=0.0, help="balance on the opening date")
    aa.add_argument("--date", help="opening date YYYY-MM-DD (default: today)")
    aa.add_argument("--note")

    im = sub.add_parser("import", help="import transactions from a CSV (e.g. the Sheet's Transactions tab)")
    im.add_argument("file")
    ex = sub.add_parser("export", help="export all transactions to CSV")
    ex.add_argument("file")
    return p


COMMANDS = {
    "add": cmd_add, "transfer": cmd_transfer, "list": cmd_list, "delete": cmd_delete,
    "balance": cmd_balance, "summary": cmd_summary, "story": cmd_story, "suggest": cmd_suggest,
    "budget": cmd_budget, "goal": cmd_goal, "account": cmd_account,
    "import": cmd_import, "export": cmd_export,
}


def run(db: Database, args) -> None:
    COMMANDS[args.command](db, args)


def main(argv: Optional[Sequence[str]] = None) -> None:
    # Make emoji print correctly in the Windows terminal
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except (ValueError, OSError):
            pass
    parser = build_parser()
    args = parser.parse_args(argv)
    db = Database(args.db)
    try:
        if args.command is None:
            menu(db, parser)
        else:
            run(db, args)
    except (KeyboardInterrupt, EOFError):
        print("\nKhuda Hafiz! 👋")
    finally:
        db.close()

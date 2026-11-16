"""Your money story, from the first entry to today, told month by month."""

from __future__ import annotations

from typing import List

from . import reports
from .constants import EARNED_CATEGORIES, EXPENSE, INCOME, TRANSFER_IN
from .db import Account, Transaction
from .reports import month_name, pkr


def _first(txns, test):
    return next((t for t in txns if test(t)), None)


def milestones(txns: List[Transaction]) -> List[str]:
    found = []  # (label, transaction)
    found.append(("📖 Story begins", txns[0]))
    found.append(("📥 First money in", _first(txns, lambda t: t.type == INCOME)))
    found.append(("🎉 First salary", _first(txns, lambda t: t.type == INCOME and t.category == "Salary")))
    found.append(("🛠️ First money from your own work",
                  _first(txns, lambda t: t.type == INCOME and t.category in ("Freelance", "Side Income"))))
    found.append(("📈 First investment",
                  _first(txns, lambda t: t.type == TRANSFER_IN and t.category == "Investment")))
    incomes = [t for t in txns if t.type == INCOME]
    if incomes:
        found.append(("💰 Biggest money in", max(incomes, key=lambda t: t.amount)))
    expenses = [t for t in txns if t.type == EXPENSE]
    if expenses:
        found.append(("💸 Biggest single spend", max(expenses, key=lambda t: t.amount)))

    # One line per transaction, even if it is several milestones at once
    merged = {}
    for label, t in found:
        if t is None:
            continue
        key = id(t)
        if key in merged:
            merged[key][0].append(label.split(" ", 1)[1].lower())
        else:
            merged[key] = ([label], t)
    lines = []
    for labels, t in sorted(merged.values(), key=lambda item: item[1].date):
        title = labels[0] + (f" (also {', '.join(labels[1:])})" if len(labels) > 1 else "")
        lines.append(f"{t.date:%d %b %Y}  {title}: {pkr(t.amount)} · {t.category} · {t.note}")
    return lines


def chapter(key: str, txns: List[Transaction]) -> List[str]:
    month = reports.in_month(txns, key)
    t = reports.totals(month)
    cats = reports.spending_by_category(month)
    lines = [f"── {month_name(key)} " + "─" * 40,
             f"   In {pkr(t.income):>12}   Out {pkr(t.spent):>12}   Net {pkr(t.saved):>12}   ({len(month)} entries)"]
    for inc in (x for x in month if x.type == INCOME):
        tag = "earned" if inc.category in EARNED_CATEGORIES else inc.category.lower()
        lines.append(f"   📥 {pkr(inc.amount)} {tag}: {inc.note}")
    if cats:
        top, amount = next(iter(cats.items()))
        lines.append(f"   🗂️ Most went to {top}: {pkr(amount)} ({amount / t.spent:.0%})")
    expenses = [x for x in month if x.type == EXPENSE]
    if expenses:
        big = max(expenses, key=lambda x: x.amount)
        lines.append(f"   💸 Biggest spend: {pkr(big.amount)}, {big.note}")
    if t.spent:
        lines.append(f"   ⚖️ Needs {t.needs / t.spent:.0%} · Wants {t.wants / t.spent:.0%}")
    return lines


def tell(txns: List[Transaction], accounts: List[Account]) -> str:
    if not txns:
        return "Your story hasn't started yet. Add your first transaction with: python main.py add"
    lines = ["📖 YOUR MONEY STORY", "", "⭐ Milestones"]
    lines += ["   " + m for m in milestones(txns)]
    lines.append("")
    for key in reports.months(txns):
        lines += chapter(key, txns)
        lines.append("")
    overall = reports.totals(txns)
    lines.append("── So far " + "─" * 40)
    lines.append(f"   Total in {pkr(overall.income)} · out {pkr(overall.spent)} · "
                 f"you earned {pkr(overall.earned)} yourself")
    if accounts:
        net = sum(reports.balances(accounts, txns).values())
        lines.append(f"   🏛️ Net worth today: {pkr(net)}")
    return "\n".join(lines)

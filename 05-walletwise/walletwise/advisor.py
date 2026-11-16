"""The 'wise' part of WalletWise: reads your whole history and gives suggestions.

Every rule is a small function that looks at your data and returns zero or more
Suggestion objects. To add a new idea, write a new rule and add it to RULES.
"""

from __future__ import annotations

import re
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Callable, Dict, List

from . import reports
from .constants import (
    EMERGENCY_FUND_MONTHS, EXPENSE, INCOME, MONTHLY_WANTS_CAP, WANT,
)
from .db import Account, Budget, Goal, Transaction
from .reports import month_key, month_name, pkr

HIGH, MEDIUM, LOW = 1, 2, 3


@dataclass
class Suggestion:
    priority: int
    icon: str
    title: str
    detail: str


@dataclass
class Context:
    """Everything a rule might need, gathered once."""
    txns: List[Transaction]
    accounts: List[Account]
    budgets: List[Budget]
    goals: List[Goal]
    today: date

    @property
    def this_month(self) -> str:
        return month_key(self.today)

    @property
    def last_month(self) -> str:
        first = self.today.replace(day=1)
        return month_key(first - timedelta(days=1))

    def expenses(self) -> List[Transaction]:
        return [t for t in self.txns if t.type == EXPENSE and t.amount > 0]

    def full_months(self) -> List[str]:
        """Months before the current one that have any data."""
        return [m for m in reports.months(self.txns) if m < self.this_month]

    def avg_monthly_spending(self, last_n: int = 3) -> float:
        monthly = reports.monthly_totals(self.txns)
        spent = [monthly[m].spent for m in self.full_months()[-last_n:] if monthly[m].spent > 0]
        return sum(spent) / len(spent) if spent else 0.0


Rule = Callable[[Context], List[Suggestion]]


# ---------------------------------------------------------------- rules

def budget_alerts(ctx: Context) -> List[Suggestion]:
    spent = reports.spending_by_category(reports.in_month(ctx.txns, ctx.this_month))
    out = []
    for b in ctx.budgets:
        used = spent.get(b.category, 0)
        if b.monthly_limit <= 0:
            continue
        if used > b.monthly_limit:
            out.append(Suggestion(HIGH, "🔴", f"{b.category} is over budget",
                                  f"Spent {pkr(used)} of {pkr(b.monthly_limit)} this month "
                                  f"({pkr(used - b.monthly_limit)} over). Pause this category until next month."))
        elif used >= 0.8 * b.monthly_limit:
            out.append(Suggestion(HIGH, "🟡", f"{b.category} is close to its limit",
                                  f"{pkr(b.monthly_limit - used)} left of {pkr(b.monthly_limit)}."))
    return out


def propose_budgets(ctx: Context) -> List[Suggestion]:
    if ctx.budgets or not ctx.full_months():
        return []
    recent = ctx.full_months()[-3:]
    per_cat: Dict[str, float] = defaultdict(float)
    is_want: Dict[str, int] = Counter()
    for t in ctx.expenses():
        if month_key(t.date) in recent:
            per_cat[t.category] += t.amount
            if t.need_want == WANT:
                is_want[t.category] += 1
    if not per_cat:
        return []
    lines = []
    for cat, total in sorted(per_cat.items(), key=lambda kv: kv[1], reverse=True):
        avg = total / len(recent)
        limit = avg * (0.8 if is_want[cat] else 1.0)      # trim wants by 20%
        limit = max(50, round(limit / 50) * 50)            # round to nearest 50
        lines.append(f'    python main.py budget set "{cat}" {limit:.0f}')
    return [Suggestion(MEDIUM, "📝", "You have no budgets yet. Here is a starting point",
                       f"Based on your average spending over the last {len(recent)} month(s), "
                       "with wants trimmed by 20%:\n" + "\n".join(lines))]


def top_category(ctx: Context) -> List[Suggestion]:
    cats = reports.spending_by_category(ctx.txns)
    total = sum(cats.values())
    if not cats or total == 0:
        return []
    cat, amount = next(iter(cats.items()))
    share = amount / total
    if share < 0.3:
        return []
    return [Suggestion(MEDIUM, "🎯", f"{cat} is your biggest money leak ({share:.0%} of all spending)",
                       f"{pkr(amount)} of {pkr(total)} in total. Making this category even 20% cheaper "
                       f"saves more than cutting all of your small categories put together.")]


def _note_key(note: str) -> str:
    words = re.findall(r"[A-Za-z]+", note)
    return words[0].lower() if words else ""


def recurring_spend(ctx: Context) -> List[Suggestion]:
    groups: Dict[str, List[Transaction]] = defaultdict(list)
    for t in ctx.expenses():
        key = _note_key(t.note)
        if key:
            groups[key].append(t)
    if not groups:
        return []
    key, items = max(groups.items(), key=lambda kv: sum(t.amount for t in kv[1]))
    if len(items) < 5:
        return []
    total = sum(t.amount for t in items)
    avg = total / len(items)
    first_word = re.findall(r"[A-Za-z]+", items[0].note)[0]
    per_week = len(items) / max(1, ((items[-1].date - items[0].date).days + 1) / 7)
    weekly_save = avg  # skip one per week
    return [Suggestion(MEDIUM, "🔁", f"'{first_word}' is your most repeated spend",
                       f"{len(items)} times, {pkr(total)} in total, about {pkr(avg)} each "
                       f"(~{per_week:.1f} times a week). Skipping just one a week (shared ride, walking, "
                       f"a cheaper pickup point) saves about {pkr(weekly_save * 4.3)} a month.")]


def wants_check(ctx: Context) -> List[Suggestion]:
    month = reports.totals(reports.in_month(ctx.txns, ctx.this_month))
    out = []
    if month.wants > MONTHLY_WANTS_CAP:
        out.append(Suggestion(HIGH, "🍕", "Wants are above your monthly cap",
                              f"{pkr(month.wants)} on wants this month, cap is {pkr(MONTHLY_WANTS_CAP)}."))
    elif month.spent > 0:
        out.append(Suggestion(LOW, "🍕", "Wants are under control this month",
                              f"{pkr(month.wants)} of your {pkr(MONTHLY_WANTS_CAP)} wants cap used."))
    overall = reports.totals(ctx.txns)
    if overall.spent and overall.wants / overall.spent > 0.3:
        out.append(Suggestion(MEDIUM, "⚖️", f"{overall.wants / overall.spent:.0%} of your spending is wants",
                              "Try to keep wants under 30% of spending while you have no fixed income."))
    return out


def month_over_month(ctx: Context) -> List[Suggestion]:
    full = ctx.full_months()
    if len(full) < 2:
        return []
    prev, last = full[-2], full[-1]
    a = reports.spending_by_category(reports.in_month(ctx.txns, prev))
    b = reports.spending_by_category(reports.in_month(ctx.txns, last))
    jumps = [(cat, b[cat] - a.get(cat, 0)) for cat in b if b[cat] - a.get(cat, 0) >= 300]
    if not jumps:
        return []
    cat, diff = max(jumps, key=lambda j: j[1])
    return [Suggestion(MEDIUM, "📈", f"{cat} went up in {month_name(last)}",
                       f"{pkr(b[cat])} vs {pkr(a.get(cat, 0))} in {month_name(prev)} (+{pkr(diff)}). "
                       "Was it a one-time thing or a new habit?")]


def savings_rate(ctx: Context) -> List[Suggestion]:
    out = []
    for key in (ctx.last_month, ctx.this_month):
        t = reports.totals(reports.in_month(ctx.txns, key))
        if t.income == 0 and t.spent == 0:
            continue
        label = "this month" if key == ctx.this_month else month_name(key)
        if t.saved < 0:
            out.append(Suggestion(HIGH, "⚠️", f"You spent more than you got in {label}",
                                  f"Income {pkr(t.income)}, spent {pkr(t.spent)}: {pkr(-t.saved)} came from savings."))
        elif t.savings_rate is not None and t.savings_rate >= 0.2:
            out.append(Suggestion(LOW, "🐷", f"Great saving in {label}: {t.savings_rate:.0%}",
                                  f"Saved {pkr(t.saved)} of {pkr(t.income)}. Move it to savings before it gets spent."))
    return out


def goal_progress(ctx: Context) -> List[Suggestion]:
    balances = reports.balances(ctx.accounts, ctx.txns)
    out = []
    avg = ctx.avg_monthly_spending()
    for g in ctx.goals:
        saved = balances.get(g.account, 0)
        progress = saved / g.target if g.target else 0
        detail = f"{pkr(saved)} of {pkr(g.target)} ({min(progress, 1):.0%})."
        if progress >= 1:
            out.append(Suggestion(LOW, "🏆", f"Goal reached: {g.name}", detail))
            continue
        if g.target_date:
            try:
                deadline = date.fromisoformat(g.target_date)
                months_left = max(1, (deadline.year - ctx.today.year) * 12 + deadline.month - ctx.today.month)
                detail += f" Save {pkr((g.target - saved) / months_left)} a month to hit it by {deadline:%d %b %Y}."
            except ValueError:
                pass
        if "emergency" in g.name.lower() and avg:
            ideal = avg * EMERGENCY_FUND_MONTHS
            detail += (f" Your average monthly spending is {pkr(avg)}, so {EMERGENCY_FUND_MONTHS} months "
                       f"of safety is about {pkr(ideal)}.")
        out.append(Suggestion(MEDIUM, "🎯", f"Goal: {g.name}", detail))
    return out


def grow_income(ctx: Context) -> List[Suggestion]:
    overall = reports.totals(ctx.txns)
    month = reports.totals(reports.in_month(ctx.txns, ctx.this_month))
    if overall.income == 0:
        return []
    share = overall.earned / overall.income
    if month.earned == 0 or share < 0.5:
        return [Suggestion(MEDIUM, "💡", "Growing income is your biggest lever",
                           f"You earned {share:.0%} of all your income yourself ({pkr(overall.earned)}), "
                           f"and {pkr(month.earned)} so far this month. One small freelance gig or selling a "
                           "digital product beats months of cutting chai.")]
    return []


def big_expenses(ctx: Context) -> List[Suggestion]:
    exp = ctx.expenses()
    if len(exp) < 5:
        return []
    median = statistics.median(t.amount for t in exp)
    since = ctx.today - timedelta(days=30)
    big = [t for t in exp if t.date >= since and t.amount >= max(1000, 3 * median)]
    if not big:
        return []
    lines = "\n".join(f"    {t.date:%d %b}  {pkr(t.amount):>11}  {t.category}: {t.note[:50]}" for t in big)
    return [Suggestion(LOW, "🧾", "Big spends in the last 30 days",
                       f"Your usual expense is about {pkr(median)}. These were much bigger:\n{lines}")]


def busiest_day(ctx: Context) -> List[Suggestion]:
    by_day: Dict[str, float] = defaultdict(float)
    for t in ctx.expenses():
        by_day[t.date.strftime("%A")] += t.amount
    total = sum(by_day.values())
    if not total or len(by_day) < 3:
        return []
    day, amount = max(by_day.items(), key=lambda kv: kv[1])
    if amount / total < 0.25:
        return []
    return [Suggestion(LOW, "📅", f"{day} is your most expensive day",
                       f"{amount / total:.0%} of all spending ({pkr(amount)}) happened on a {day}.")]


def fees(ctx: Context) -> List[Suggestion]:
    hits = [t for t in ctx.expenses() if re.search(r"\bfee\b", t.note, re.I) and "transfer" in t.note.lower()]
    if not hits:
        return []
    total = sum(t.amount for t in hits)
    return [Suggestion(LOW, "🏦", f"Bank/transfer fees cost you {pkr(total)}",
                       "Check if your bank app offers free transfers (Raast is free) before moving money.")]


def untracked_accounts(ctx: Context) -> List[Suggestion]:
    if not ctx.accounts:
        return [Suggestion(MEDIUM, "🏛️", "Add your accounts to see real balances",
                           'Example: python main.py account add "Physical Cash" --kind Cash --opening 500')]
    start = min(a.opening_date for a in ctx.accounts)
    missing = [t for t in ctx.txns if not t.account and t.date >= start]
    if not missing:
        return []
    return [Suggestion(HIGH, "❓", f"{len(missing)} recent entries have no account",
                       "Balances can't include them. Always say where the money came from or went.")]


def no_spend_days(ctx: Context) -> List[Suggestion]:
    first = ctx.today.replace(day=1)
    days = (ctx.today - first).days + 1
    spend_days = {t.date for t in ctx.expenses() if first <= t.date <= ctx.today}
    free = days - len(spend_days)
    if days >= 7 and free >= days * 0.5:
        return [Suggestion(LOW, "🌱", f"{free} no-spend days this month",
                           f"Out of {days} days so far. Keep the streak going!")]
    return []


RULES: List[Rule] = [
    budget_alerts, untracked_accounts, savings_rate, wants_check, propose_budgets,
    top_category, recurring_spend, month_over_month, goal_progress, grow_income,
    big_expenses, busiest_day, fees, no_spend_days,
]


def suggest(txns, accounts, budgets, goals, today: date = None) -> List[Suggestion]:
    ctx = Context(txns, accounts, budgets, goals, today or date.today())
    out: List[Suggestion] = []
    for rule in RULES:
        out.extend(rule(ctx))
    return sorted(out, key=lambda s: s.priority)

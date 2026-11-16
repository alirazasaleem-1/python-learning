"""Number crunching: totals, categories, months and account balances."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from typing import Dict, Iterable, List, Optional

from .constants import EXPENSE, INCOME, NEED, SIGN, WANT, EARNED_CATEGORIES
from .db import Account, Transaction


def pkr(amount: float) -> str:
    """Format a number as money: 12000 -> 'PKR 12,000'."""
    sign = "-" if amount < 0 else ""
    return f"{sign}PKR {abs(amount):,.0f}"


def month_key(d: date) -> str:
    return d.strftime("%Y-%m")


def month_name(key: str) -> str:
    year, month = key.split("-")
    return date(int(year), int(month), 1).strftime("%b %Y")


def in_month(txns: Iterable[Transaction], key: Optional[str]) -> List[Transaction]:
    if key is None:
        return list(txns)
    return [t for t in txns if month_key(t.date) == key]


@dataclass
class Totals:
    income: float = 0
    earned: float = 0
    spent: float = 0
    needs: float = 0
    wants: float = 0

    @property
    def saved(self) -> float:
        return self.income - self.spent

    @property
    def savings_rate(self) -> Optional[float]:
        return self.saved / self.income if self.income else None


def totals(txns: Iterable[Transaction]) -> Totals:
    result = Totals()
    for t in txns:
        if t.type == INCOME:
            result.income += t.amount
            if t.category in EARNED_CATEGORIES:
                result.earned += t.amount
        elif t.type == EXPENSE:
            result.spent += t.amount
            if t.need_want == NEED:
                result.needs += t.amount
            elif t.need_want == WANT:
                result.wants += t.amount
    return result


def spending_by_category(txns: Iterable[Transaction]) -> Dict[str, float]:
    result: Dict[str, float] = defaultdict(float)
    for t in txns:
        if t.type == EXPENSE:
            result[t.category] += t.amount
    return dict(sorted(result.items(), key=lambda kv: kv[1], reverse=True))


def months(txns: Iterable[Transaction]) -> List[str]:
    return sorted({month_key(t.date) for t in txns})


def monthly_totals(txns: List[Transaction]) -> Dict[str, Totals]:
    return {m: totals(in_month(txns, m)) for m in months(txns)}


def account_balance(account: Account, txns: Iterable[Transaction]) -> float:
    """Opening balance + every transaction on this account from the opening date on."""
    balance = account.opening_balance
    for t in txns:
        if t.account == account.name and t.date >= account.opening_date:
            balance += SIGN[t.type] * t.amount
    return balance


def balances(accounts: List[Account], txns: List[Transaction]) -> Dict[str, float]:
    return {a.name: account_balance(a, txns) for a in accounts}

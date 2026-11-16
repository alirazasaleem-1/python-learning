"""Tools the AI assistant can use on your WalletWise data.

Each tool has:
  * a JSON schema, so Claude knows what the tool does and which inputs it takes
  * a Python method that actually runs it against the database

Tools that change data (add, transfer, budget, goal, delete) ask YOU first.
If you say no, nothing is saved and Claude is told you declined.
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import date
from typing import Any, Callable, Dict, List, Optional

from . import advisor, reports
from .constants import (
    CATEGORIES, EXPENSE, EXPENSE_CATEGORIES, NEED_WANT, TRANSFER_CATEGORIES, TRANSFER_IN,
    TRANSFER_OUT, TYPES,
)
from .csv_io import parse_date
from .db import Database, Goal, Transaction
from .reports import month_key, pkr

Confirm = Callable[[str], bool]


def _txn_dict(t: Transaction) -> Dict[str, Any]:
    return {"id": t.id, "date": t.date.isoformat(), "type": t.type, "category": t.category,
            "amount": t.amount, "account": t.account, "note": t.note, "need_want": t.need_want}


class MoneyTools:
    def __init__(self, db: Database, confirm: Confirm, today: Optional[date] = None):
        self.db = db
        self.confirm = confirm
        self.today = today or date.today()

    # ------------------------------------------------------------ schemas

    def schemas(self) -> List[Dict[str, Any]]:
        accounts = [a.name for a in self.db.accounts()]
        account = {"type": "string", "description": "Account name"}
        if accounts:
            account["enum"] = accounts
        date_prop = {"type": "string", "description": "Date as YYYY-MM-DD"}
        month_prop = {"type": "string", "description": "Month as YYYY-MM"}

        def tool(name, description, properties, required=()):
            return {
                "name": name,
                "description": description,
                "strict": True,
                "input_schema": {"type": "object", "properties": properties,
                                 "required": list(required), "additionalProperties": False},
            }

        return [
            tool("get_overview",
                 "Current balances of every account, net worth, this month's income/spending/savings, "
                 "budget status and goal progress. Use it for fresh numbers after any change.", {}),
            tool("find_transactions",
                 "Search transactions. All filters are optional and combine with AND. Returns newest first.",
                 {"month": month_prop, "date_from": date_prop, "date_to": date_prop,
                  "type": {"type": "string", "enum": TYPES},
                  "category": {"type": "string", "enum": CATEGORIES},
                  "account": account,
                  "search": {"type": "string", "description": "Text to find in the note (case-insensitive)"},
                  "limit": {"type": "integer", "description": "Max rows to return (default 50)"}}),
            tool("spending_report",
                 "Totals grouped one way: by category, month, weekday, need_want or account. "
                 "Optionally limited to a date range. Use it for 'how much did I spend on X' questions.",
                 {"group_by": {"type": "string", "enum": ["category", "month", "weekday", "need_want", "account"]},
                  "type": {"type": "string", "enum": TYPES, "description": "Default: Expense"},
                  "date_from": date_prop, "date_to": date_prop},
                 required=["group_by"]),
            tool("get_rule_insights",
                 "WalletWise's built-in rule-based checks (budget alerts, overspending months, repeated "
                 "spends, goal progress...). A good starting point for advice.", {}),
            tool("add_transaction",
                 "Save one income or expense. The user is asked to confirm before it is saved. "
                 "For money moving between the user's own accounts use transfer_money instead.",
                 {"date": date_prop,
                  "type": {"type": "string", "enum": ["Income", "Expense"]},
                  "category": {"type": "string", "enum": CATEGORIES},
                  "amount": {"type": "number", "description": "Positive amount in PKR"},
                  "account": account,
                  "note": {"type": "string", "description": "Short note in the user's own words"},
                  "need_want": {"type": "string", "enum": NEED_WANT, "description": "Only for expenses"}},
                 required=["date", "type", "category", "amount", "account", "note"]),
            tool("transfer_money",
                 "Move money between two of the user's own accounts (e.g. cash to bank, bank to an "
                 "investment). Saves a Transfer Out and a Transfer In row. The user is asked to confirm.",
                 {"source": account, "target": account,
                  "amount": {"type": "number"},
                  "category": {"type": "string", "enum": TRANSFER_CATEGORIES,
                               "description": "Investment when buying shares/funds, otherwise Transfer"},
                  "date": date_prop, "note": {"type": "string"}},
                 required=["source", "target", "amount", "category", "date", "note"]),
            tool("delete_transaction",
                 "Delete one transaction by id (find it with find_transactions first). The user is asked to confirm.",
                 {"id": {"type": "integer"}}, required=["id"]),
            tool("set_budget",
                 "Set the monthly spending limit of an expense category. The user is asked to confirm.",
                 {"category": {"type": "string", "enum": EXPENSE_CATEGORIES},
                  "monthly_limit": {"type": "number"}},
                 required=["category", "monthly_limit"]),
            tool("save_goal",
                 "Create or update a savings goal. Its progress is the balance of the linked account. "
                 "The user is asked to confirm.",
                 {"name": {"type": "string"}, "target": {"type": "number"}, "account": account,
                  "target_date": date_prop, "note": {"type": "string"}},
                 required=["name", "target"]),
            tool("remember",
                 "Save a lasting fact about the user's money life to long-term memory, so you know it in "
                 "future chats: income sources, family situation, plans, habits, preferences, goals. "
                 "One short fact per call. Don't save numbers that the transactions already show.",
                 {"fact": {"type": "string"}}, required=["fact"]),
            tool("forget",
                 "Delete a memory by its id, when it is wrong or out of date.",
                 {"id": {"type": "integer"}}, required=["id"]),
        ]

    # ------------------------------------------------------------ running

    def run(self, name: str, args: Dict[str, Any]) -> str:
        handler = getattr(self, f"tool_{name}", None)
        if handler is None:
            raise ValueError(f"Unknown tool {name}")
        result = handler(**args)
        return json.dumps(result, ensure_ascii=False, default=str)

    def _check_account(self, name: str) -> str:
        names = [a.name for a in self.db.accounts()]
        if names and name not in names:
            raise ValueError(f"Unknown account '{name}'. Accounts: {names}")
        return name

    # ------------------------------------------------------------ read tools

    def tool_get_overview(self) -> Dict[str, Any]:
        txns = self.db.transactions()
        accounts = self.db.accounts()
        bal = reports.balances(accounts, txns)
        month = reports.totals(reports.in_month(txns, month_key(self.today)))
        spent = reports.spending_by_category(reports.in_month(txns, month_key(self.today)))
        return {
            "today": self.today.isoformat(),
            "accounts": [{"name": a.name, "kind": a.kind, "balance": round(bal[a.name], 2), "note": a.note}
                         for a in accounts],
            "net_worth": round(sum(bal.values()), 2),
            "this_month": {"income": month.income, "earned_by_user": month.earned, "spent": month.spent,
                           "needs": month.needs, "wants": month.wants, "saved": month.saved},
            "budgets": [{"category": b.category, "limit": b.monthly_limit,
                         "spent_this_month": spent.get(b.category, 0)} for b in self.db.budgets()],
            "goals": [{"name": g.name, "target": g.target, "account": g.account,
                       "saved": round(bal.get(g.account, 0), 2), "target_date": g.target_date}
                      for g in self.db.goals()],
        }

    def tool_find_transactions(self, month=None, date_from=None, date_to=None, type=None, category=None,
                               account=None, search=None, limit=50) -> Dict[str, Any]:
        rows = self.db.transactions()
        if month:
            rows = [t for t in rows if month_key(t.date) == month]
        if date_from:
            rows = [t for t in rows if t.date >= parse_date(date_from)]
        if date_to:
            rows = [t for t in rows if t.date <= parse_date(date_to)]
        if type:
            rows = [t for t in rows if t.type == type]
        if category:
            rows = [t for t in rows if t.category == category]
        if account:
            rows = [t for t in rows if t.account == account]
        if search:
            rows = [t for t in rows if search.lower() in t.note.lower()]
        total = sum(t.amount for t in rows)
        rows = list(reversed(rows))[: max(1, min(int(limit or 50), 500))]
        return {"matches": len(rows), "total_amount_of_matches": total,
                "transactions": [_txn_dict(t) for t in rows]}

    def tool_spending_report(self, group_by, type=EXPENSE, date_from=None, date_to=None) -> Dict[str, Any]:
        rows = [t for t in self.db.transactions() if t.type == type]
        if date_from:
            rows = [t for t in rows if t.date >= parse_date(date_from)]
        if date_to:
            rows = [t for t in rows if t.date <= parse_date(date_to)]
        key = {
            "category": lambda t: t.category,
            "month": lambda t: month_key(t.date),
            "weekday": lambda t: t.date.strftime("%A"),
            "need_want": lambda t: t.need_want or "(not set)",
            "account": lambda t: t.account or "(no account)",
        }[group_by]
        groups: Dict[str, List[float]] = defaultdict(list)
        for t in rows:
            groups[key(t)].append(t.amount)
        total = sum(sum(v) for v in groups.values())
        order = sorted(groups) if group_by == "month" else sorted(groups, key=lambda k: -sum(groups[k]))
        return {"type": type, "total": total, "groups": [
            {group_by: k, "total": sum(groups[k]), "count": len(groups[k]),
             "share": round(sum(groups[k]) / total, 3) if total else 0} for k in order]}

    def tool_get_rule_insights(self) -> List[Dict[str, str]]:
        tips = advisor.suggest(self.db.transactions(), self.db.accounts(), self.db.budgets(),
                               self.db.goals(), today=self.today)
        return [{"title": s.title, "detail": s.detail} for s in tips]

    # ------------------------------------------------------------ write tools

    def tool_add_transaction(self, date, type, category, amount, account, note, need_want="") -> Dict[str, Any]:
        t = Transaction(parse_date(date), type, category, abs(float(amount)),
                        self._check_account(account), note, need_want if type == EXPENSE else "")
        summary = (f"{t.date:%d %b %Y} · {t.type} · {pkr(t.amount)} · {t.category} · {t.account}"
                   f"{' · ' + t.need_want if t.need_want else ''} · {t.note}")
        if not self.confirm(f"Save this? {summary}"):
            return {"saved": False, "reason": "The user declined. Ask what to change."}
        t.id = self.db.add_transaction(t)
        return {"saved": True, "transaction": _txn_dict(t), "new_balance": self._balance(t.account)}

    def tool_transfer_money(self, source, target, amount, category, date, note) -> Dict[str, Any]:
        source, target = self._check_account(source), self._check_account(target)
        if source == target:
            raise ValueError("source and target must be different accounts")
        day, amount = parse_date(date), abs(float(amount))
        if not self.confirm(f"Move {pkr(amount)} from {source} to {target} on {day:%d %b %Y} ({category})?"):
            return {"saved": False, "reason": "The user declined."}
        self.db.add_transaction(Transaction(day, TRANSFER_OUT, category, amount, source, note))
        self.db.add_transaction(Transaction(day, TRANSFER_IN, category, amount, target, note))
        return {"saved": True, "balances": {source: self._balance(source), target: self._balance(target)}}

    def tool_delete_transaction(self, id) -> Dict[str, Any]:
        t = next((x for x in self.db.transactions() if x.id == id), None)
        if t is None:
            return {"deleted": False, "reason": f"No transaction #{id}"}
        if not self.confirm(f"Delete #{id}: {t.date:%d %b %Y} {t.type} {pkr(t.amount)} {t.category} ({t.note})?"):
            return {"deleted": False, "reason": "The user declined."}
        self.db.delete_transaction(id)
        return {"deleted": True, "transaction": _txn_dict(t)}

    def tool_set_budget(self, category, monthly_limit) -> Dict[str, Any]:
        if not self.confirm(f"Set the {category} budget to {pkr(monthly_limit)} a month?"):
            return {"saved": False, "reason": "The user declined."}
        self.db.set_budget(category, abs(float(monthly_limit)))
        return {"saved": True}

    def tool_save_goal(self, name, target, account="", target_date="", note="") -> Dict[str, Any]:
        if account:
            self._check_account(account)
        if target_date:
            target_date = parse_date(target_date).isoformat()
        if not self.confirm(f"Save goal '{name}': {pkr(target)}"
                            f"{' in ' + account if account else ''}{' by ' + target_date if target_date else ''}?"):
            return {"saved": False, "reason": "The user declined."}
        self.db.save_goal(Goal(name, abs(float(target)), account, target_date, note))
        return {"saved": True}

    def tool_remember(self, fact) -> Dict[str, Any]:
        return {"saved": True, "id": self.db.add_memory(fact)}

    def tool_forget(self, id) -> Dict[str, Any]:
        return {"deleted": self.db.delete_memory(id)}

    def _balance(self, account_name: str) -> Optional[float]:
        acc = next((a for a in self.db.accounts() if a.name == account_name), None)
        return round(reports.account_balance(acc, self.db.transactions()), 2) if acc else None


def ledger_csv(db: Database, max_rows: int = 600) -> str:
    """All transactions as compact CSV for the assistant's context (newest kept if there are too many)."""
    txns = db.transactions()
    dropped = max(0, len(txns) - max_rows)
    lines = ["id,date,type,category,amount,account,need_want,note"]
    for t in txns[dropped:]:
        note = t.note.replace('"', "'")
        lines.append(f'{t.id},{t.date.isoformat()},{t.type},{t.category},{t.amount:g},'
                     f'{t.account},{t.need_want},"{note}"')
    if dropped:
        lines.insert(1, f"# {dropped} older rows not shown; use find_transactions for them")
    return "\n".join(lines)

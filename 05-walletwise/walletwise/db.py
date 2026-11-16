"""SQLite storage for WalletWise.

All data lives in one file (default: 05-walletwise/data/walletwise.db).
That folder is git-ignored, so your real money data never goes to GitHub.
"""

from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import List, Optional

PROJECT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DB = PROJECT_DIR / "data" / "walletwise.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (
    name            TEXT PRIMARY KEY,
    kind            TEXT NOT NULL,
    opening_balance REAL NOT NULL DEFAULT 0,
    opening_date    TEXT NOT NULL,
    note            TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS transactions (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    date      TEXT NOT NULL,
    type      TEXT NOT NULL,
    category  TEXT NOT NULL,
    amount    REAL NOT NULL CHECK (amount >= 0),
    account   TEXT NOT NULL DEFAULT '',
    note      TEXT NOT NULL DEFAULT '',
    need_want TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS budgets (
    category      TEXT PRIMARY KEY,
    monthly_limit REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS goals (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL UNIQUE,
    target      REAL NOT NULL,
    account     TEXT NOT NULL DEFAULT '',
    target_date TEXT NOT NULL DEFAULT '',
    note        TEXT NOT NULL DEFAULT ''
);
"""


@dataclass
class Transaction:
    date: date
    type: str
    category: str
    amount: float
    account: str = ""
    note: str = ""
    need_want: str = ""
    id: Optional[int] = None


@dataclass
class Account:
    name: str
    kind: str
    opening_balance: float
    opening_date: date
    note: str = ""


@dataclass
class Budget:
    category: str
    monthly_limit: float


@dataclass
class Goal:
    name: str
    target: float
    account: str = ""
    target_date: str = ""
    note: str = ""
    id: Optional[int] = None


class Database:
    def __init__(self, path: Optional[str] = None):
        path = path or os.environ.get("WALLETWISE_DB") or str(DEFAULT_DB)
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)

    def close(self) -> None:
        self.conn.close()

    # ---------- transactions ----------
    def add_transaction(self, t: Transaction) -> int:
        cur = self.conn.execute(
            "INSERT INTO transactions (date, type, category, amount, account, note, need_want)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (t.date.isoformat(), t.type, t.category, t.amount, t.account, t.note, t.need_want),
        )
        self.conn.commit()
        return cur.lastrowid

    def transaction_exists(self, t: Transaction) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM transactions WHERE date=? AND type=? AND category=? AND amount=?"
            " AND account=? AND note=? LIMIT 1",
            (t.date.isoformat(), t.type, t.category, t.amount, t.account, t.note),
        ).fetchone()
        return row is not None

    def delete_transaction(self, txn_id: int) -> bool:
        cur = self.conn.execute("DELETE FROM transactions WHERE id=?", (txn_id,))
        self.conn.commit()
        return cur.rowcount > 0

    def transactions(self) -> List[Transaction]:
        rows = self.conn.execute("SELECT * FROM transactions ORDER BY date, id").fetchall()
        return [
            Transaction(
                id=r["id"],
                date=date.fromisoformat(r["date"]),
                type=r["type"],
                category=r["category"],
                amount=r["amount"],
                account=r["account"],
                note=r["note"],
                need_want=r["need_want"],
            )
            for r in rows
        ]

    # ---------- accounts ----------
    def save_account(self, a: Account) -> None:
        self.conn.execute(
            "INSERT INTO accounts (name, kind, opening_balance, opening_date, note)"
            " VALUES (?, ?, ?, ?, ?)"
            " ON CONFLICT(name) DO UPDATE SET kind=excluded.kind,"
            " opening_balance=excluded.opening_balance, opening_date=excluded.opening_date,"
            " note=excluded.note",
            (a.name, a.kind, a.opening_balance, a.opening_date.isoformat(), a.note),
        )
        self.conn.commit()

    def accounts(self) -> List[Account]:
        rows = self.conn.execute("SELECT * FROM accounts ORDER BY rowid").fetchall()
        return [
            Account(r["name"], r["kind"], r["opening_balance"],
                    date.fromisoformat(r["opening_date"]), r["note"])
            for r in rows
        ]

    # ---------- budgets ----------
    def set_budget(self, category: str, limit: float) -> None:
        self.conn.execute(
            "INSERT INTO budgets (category, monthly_limit) VALUES (?, ?)"
            " ON CONFLICT(category) DO UPDATE SET monthly_limit=excluded.monthly_limit",
            (category, limit),
        )
        self.conn.commit()

    def budgets(self) -> List[Budget]:
        rows = self.conn.execute("SELECT * FROM budgets ORDER BY category").fetchall()
        return [Budget(r["category"], r["monthly_limit"]) for r in rows]

    # ---------- goals ----------
    def save_goal(self, g: Goal) -> None:
        self.conn.execute(
            "INSERT INTO goals (name, target, account, target_date, note) VALUES (?, ?, ?, ?, ?)"
            " ON CONFLICT(name) DO UPDATE SET target=excluded.target, account=excluded.account,"
            " target_date=excluded.target_date, note=excluded.note",
            (g.name, g.target, g.account, g.target_date, g.note),
        )
        self.conn.commit()

    def goals(self) -> List[Goal]:
        rows = self.conn.execute("SELECT * FROM goals ORDER BY id").fetchall()
        return [
            Goal(id=r["id"], name=r["name"], target=r["target"], account=r["account"],
                 target_date=r["target_date"], note=r["note"])
            for r in rows
        ]

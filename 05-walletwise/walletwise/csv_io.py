"""Import and export transactions as CSV.

The CSV columns match the Transactions tab of the money tracker Sheet:
Date, Type, Category, Amount (PKR), Account, Note, Need / Want
so you can download that tab as CSV and import it straight in.
"""

from __future__ import annotations

import csv
from datetime import date, datetime
from typing import Dict, List, Tuple

from .constants import TYPES
from .db import Database, Transaction

HEADERS = ["Date", "Type", "Category", "Amount (PKR)", "Account", "Note", "Need / Want"]
DATE_FORMATS = ["%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y", "%b %d, %Y", "%d %b %Y", "%d-%m-%Y"]


def parse_date(text: str) -> date:
    text = text.strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"Can't understand the date '{text}'. Use YYYY-MM-DD.")


def parse_amount(text: str) -> float:
    cleaned = text.upper().replace("PKR", "").replace("RS.", "").replace("RS", "").replace(",", "").strip()
    if not cleaned:
        raise ValueError("Amount is empty")
    return abs(float(cleaned))


def _column_map(fieldnames: List[str]) -> Dict[str, str]:
    """Match CSV headers loosely, e.g. 'amount' finds 'Amount (PKR)'."""
    result = {}
    for wanted in HEADERS:
        key = wanted.split(" ")[0].lower()        # date, type, category, amount, account, note, need
        for name in fieldnames:
            if name and name.strip().lower().startswith(key):
                result[wanted] = name
                break
    missing = [h for h in ("Date", "Type", "Category", "Amount (PKR)") if h not in result]
    if missing:
        raise ValueError(f"CSV is missing column(s): {', '.join(missing)}")
    return result


def import_csv(db: Database, path: str) -> Tuple[int, int, List[str]]:
    """Returns (added, skipped_duplicates, errors). Re-importing the same file is safe."""
    added = skipped = 0
    errors: List[str] = []
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        cols = _column_map(reader.fieldnames or [])
        for line_no, row in enumerate(reader, start=2):
            get = lambda h: (row.get(cols.get(h, ""), "") or "").strip()
            if not get("Date") and not get("Amount (PKR)"):
                continue                                  # blank line
            try:
                t = Transaction(
                    date=parse_date(get("Date")),
                    type=get("Type"),
                    category=get("Category"),
                    amount=parse_amount(get("Amount (PKR)")),
                    account=get("Account"),
                    note=get("Note"),
                    need_want=get("Need / Want"),
                )
                if t.type not in TYPES:
                    raise ValueError(f"Unknown type '{t.type}'")
            except ValueError as e:
                errors.append(f"line {line_no}: {e}")
                continue
            if db.transaction_exists(t):
                skipped += 1
            else:
                db.add_transaction(t)
                added += 1
    return added, skipped, errors


def export_csv(db: Database, path: str) -> int:
    txns = db.transactions()
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(HEADERS)
        for t in txns:
            writer.writerow([t.date.isoformat(), t.type, t.category, f"{t.amount:g}",
                             t.account, t.note, t.need_want])
    return len(txns)

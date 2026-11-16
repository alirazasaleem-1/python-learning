import os
import tempfile
import unittest
from datetime import date
from pathlib import Path

from walletwise import advisor, csv_io, reports, story
from walletwise.db import Account, Database, Goal, Transaction

SAMPLE = Path(__file__).resolve().parent.parent / "sample_data" / "sample_transactions.csv"


class WalletWiseTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(os.path.join(self.tmp.name, "test.db"))
        self.db.save_account(Account("Cash", "Cash", 1000, date(2026, 9, 1)))
        self.db.save_account(Account("Bank", "Bank", 0, date(2026, 9, 1)))

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def test_import_is_safe_to_repeat(self):
        added, skipped, errors = csv_io.import_csv(self.db, SAMPLE)
        self.assertEqual((skipped, errors), (0, []))
        self.assertEqual(added, len(self.db.transactions()))
        added_again, skipped_again, _ = csv_io.import_csv(self.db, SAMPLE)
        self.assertEqual((added_again, skipped_again), (0, added))

    def test_parse_sheet_style_values(self):
        self.assertEqual(csv_io.parse_amount("PKR 12,000"), 12000)
        self.assertEqual(csv_io.parse_date("11/14/2026"), date(2026, 11, 14))
        self.assertEqual(csv_io.parse_date("2026-11-14"), date(2026, 11, 14))

    def test_balances_and_transfers(self):
        self.db.add_transaction(Transaction(date(2026, 9, 2), "Expense", "Transport", 200, "Cash"))
        self.db.add_transaction(Transaction(date(2026, 9, 3), "Transfer Out", "Transfer", 500, "Cash"))
        self.db.add_transaction(Transaction(date(2026, 9, 3), "Transfer In", "Transfer", 500, "Bank"))
        # before the opening date: must not change the balance
        self.db.add_transaction(Transaction(date(2026, 8, 1), "Expense", "Transport", 999, "Cash"))
        bal = reports.balances(self.db.accounts(), self.db.transactions())
        self.assertEqual(bal, {"Cash": 300, "Bank": 500})

    def test_totals(self):
        csv_io.import_csv(self.db, SAMPLE)
        oct_ = reports.totals(reports.in_month(self.db.transactions(), "2026-10"))
        self.assertEqual(oct_.income, 5000)
        self.assertEqual(oct_.spent, 5400)
        self.assertEqual(oct_.wants, 3600)
        self.assertLess(oct_.saved, 0)

    def test_suggestions(self):
        csv_io.import_csv(self.db, SAMPLE)
        self.db.save_goal(Goal("Emergency Fund", 10000, "Bank"))
        tips = advisor.suggest(self.db.transactions(), self.db.accounts(), [], self.db.goals(),
                               today=date(2026, 11, 16))
        titles = " | ".join(t.title for t in tips)
        self.assertIn("spent more than you got in Oct 2026", titles)
        self.assertIn("no budgets yet", titles)
        self.assertIn("Emergency Fund", titles)
        self.assertEqual(sorted(t.priority for t in tips), [t.priority for t in tips])

    def test_budget_alert(self):
        csv_io.import_csv(self.db, SAMPLE)
        self.db.set_budget("Food & Snacks", 800)
        tips = advisor.suggest(self.db.transactions(), self.db.accounts(), self.db.budgets(), [],
                               today=date(2026, 11, 16))
        self.assertTrue(any("Food & Snacks is over budget" in t.title for t in tips))

    def test_story(self):
        csv_io.import_csv(self.db, SAMPLE)
        text = story.tell(self.db.transactions(), self.db.accounts())
        self.assertIn("Story begins", text)
        self.assertIn("Oct 2026", text)
        self.assertIn("First money from your own work", text)


if __name__ == "__main__":
    unittest.main()

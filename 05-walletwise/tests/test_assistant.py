"""Tests for the AI chat, using a fake Claude client (no internet, no API key)."""

import os
import tempfile
import unittest
from datetime import date
from types import SimpleNamespace as NS

from walletwise.assistant import MoneyChat
from walletwise.db import Account, Database


def text(t):
    return NS(type="text", text=t)


def tool_use(id_, name, inp):
    return NS(type="tool_use", id=id_, name=name, input=inp)


class FakeResponse:
    def __init__(self, stop_reason, content):
        self.stop_reason, self.content = stop_reason, content

    def to_param(self):
        return {"role": "assistant", "content": [vars(b) for b in self.content]}


class FakeClient:
    """Replays scripted responses and records every request."""

    def __init__(self, responses):
        self.responses, self.requests = list(responses), []
        self.beta = NS(messages=NS(create=self.create))

    def create(self, **kwargs):
        self.requests.append({**kwargs, "messages": list(kwargs["messages"])})
        return self.responses.pop(0)


class AssistantTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(os.path.join(self.tmp.name, "t.db"))
        self.db.save_account(Account("Cash", "Cash", 1000, date(2026, 11, 1)))
        self.today = date(2026, 11, 16)

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def chat(self, responses, answer=True):
        self.asked = []
        client = FakeClient(responses)
        chat = MoneyChat(self.db, client=client, today=self.today, show=lambda t: None,
                         confirm=lambda q: self.asked.append(q) or answer)
        return chat, client

    def test_logs_expense_after_confirmation(self):
        chat, client = self.chat([
            FakeResponse("tool_use", [tool_use("t1", "add_transaction", {
                "date": "2026-11-16", "type": "Expense", "category": "Food & Snacks", "amount": 250,
                "account": "Cash", "note": "Lunch", "need_want": "Need"})]),
            FakeResponse("end_turn", [text("Saved! Cash is now PKR 750.")]),
        ])
        reply = chat.send("aaj 250 ka lunch cash se")
        self.assertEqual(reply, "Saved! Cash is now PKR 750.")
        self.assertEqual(len(self.asked), 1)
        self.assertEqual(self.db.transactions()[-1].amount, 250)
        result = client.requests[1]["messages"][-1]["content"][0]
        self.assertEqual(result["tool_use_id"], "t1")
        self.assertIn('"new_balance": 750.0', result["content"])

    def test_declined_save_writes_nothing(self):
        chat, _ = self.chat([
            FakeResponse("tool_use", [tool_use("t1", "add_transaction", {
                "date": "2026-11-16", "type": "Income", "category": "Pocket Money", "amount": 500,
                "account": "Cash", "note": "Ammi"})]),
            FakeResponse("end_turn", [text("Okay, not saved.")]),
        ], answer=False)
        chat.send("Ammi ne 500 diye")
        self.assertEqual(self.db.transactions(), [])

    def test_tool_errors_go_back_to_claude(self):
        chat, client = self.chat([
            FakeResponse("tool_use", [tool_use("t1", "add_transaction", {
                "date": "2026-11-16", "type": "Expense", "category": "Transport", "amount": 100,
                "account": "Wallet That Does Not Exist", "note": "Rickshaw"})]),
            FakeResponse("end_turn", [text("Which account?")]),
        ])
        chat.send("100 rickshaw")
        result = client.requests[1]["messages"][-1]["content"][0]
        self.assertTrue(result["is_error"])
        self.assertIn("Unknown account", result["content"])

    def test_memory_and_snapshot(self):
        chat, _ = self.chat([
            FakeResponse("tool_use", [tool_use("t1", "remember", {"fact": "Saving for a laptop SSD"})]),
            FakeResponse("end_turn", [text("Noted!")]),
        ])
        chat.send("I'm saving for an SSD")
        self.assertEqual([m["fact"] for m in self.db.memories()], ["Saving for a laptop SSD"])
        fresh, _ = self.chat([])
        self.assertIn("Saving for a laptop SSD", fresh.system[1]["text"])
        self.assertIn("Cash (Cash): PKR 1,000", fresh.system[1]["text"])

    def test_history_is_kept_and_failed_turn_rolled_back(self):
        chat, client = self.chat([FakeResponse("end_turn", [text("Hi!")])])
        chat.send("salam")
        self.assertEqual([m["role"] for m in chat.messages], ["user", "assistant"])
        client.responses = []  # next request raises IndexError, like a network error
        with self.assertRaises(IndexError):
            chat.send("are you there?")
        self.assertEqual(len(chat.messages), 2)

    def test_request_settings(self):
        chat, client = self.chat([FakeResponse("end_turn", [text("ok")])])
        chat.send("hi")
        req = client.requests[0]
        self.assertEqual(req["model"], "claude-opus-5-5")
        self.assertEqual(req["fallbacks"], "default")
        names = {t["name"] for t in req["tools"]}
        self.assertTrue({"add_transaction", "transfer_money", "remember", "find_transactions"} <= names)
        for t in req["tools"]:
            self.assertFalse(t["input_schema"]["additionalProperties"])


if __name__ == "__main__":
    unittest.main()

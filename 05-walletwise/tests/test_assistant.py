"""Tests for WalletWise AI with fake brains: no internet, no Ollama, no API key needed."""

import os
import tempfile
import unittest
from datetime import date
from types import SimpleNamespace as NS

from walletwise.assistant import INSTRUCTIONS, MoneyChat, snapshot
from walletwise.brains import ClaudeBrain, OllamaBrain
from walletwise.db import Account, Database, Transaction
from walletwise.tools import MoneyTools

TODAY = date(2026, 11, 16)


# ---------------------------------------------------------------- fake Ollama server

class FakeOllama:
    """Plays the part of Ollama's /api/chat endpoint with scripted replies."""

    def __init__(self, replies):
        self.replies, self.requests = list(replies), []

    def __call__(self, path, body):
        assert path == "/api/chat"
        self.requests.append({**body, "messages": [dict(m) for m in body["messages"]]})
        return {"message": self.replies.pop(0), "done": True, "done_reason": "stop"}


def ollama_call(name, **args):
    return {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": name, "arguments": args}}]}


def ollama_text(text):
    return {"role": "assistant", "content": text}


# ---------------------------------------------------------------- fake Claude client

class FakeResponse:
    def __init__(self, stop_reason, content):
        self.stop_reason, self.content = stop_reason, content

    def to_param(self):
        return {"role": "assistant", "content": [vars(b) for b in self.content]}


class FakeClaude:
    def __init__(self, responses):
        self.responses, self.requests = list(responses), []
        self.beta = NS(messages=NS(create=self.create))

    def create(self, **kwargs):
        self.requests.append({**kwargs, "messages": list(kwargs["messages"])})
        return self.responses.pop(0)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(os.path.join(self.tmp.name, "t.db"))
        self.db.save_account(Account("Physical Cash", "Cash", 1000, date(2026, 11, 1)))
        self.asked = []

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def confirm(self, answer=True):
        return lambda q: self.asked.append(q) or answer

    def ollama_chat(self, replies, answer=True):
        server = FakeOllama(replies)
        tools = MoneyTools(self.db, self.confirm(answer), TODAY)
        brain = OllamaBrain("system", tools.schemas(), model="qwen2.5:3b", post=server)
        return MoneyChat(self.db, brain=brain, confirm=self.confirm(answer), today=TODAY,
                         show=lambda t: None), server


class OllamaTest(Base):
    def test_logs_expense_free_and_locally(self):
        chat, server = self.ollama_chat([
            ollama_call("add_transaction", date="2026-11-16", type="expense", category="food & snacks",
                        amount="250", account="physical cash", note="Lunch", need_want="need", extra="ignored"),
            ollama_text("Lunch save ho gaya ✅"),
        ])
        self.assertEqual(chat.send("aaj 250 ka lunch cash se"), "Lunch save ho gaya ✅")
        t = self.db.transactions()[-1]
        self.assertEqual((t.type, t.category, t.amount, t.account, t.need_want),
                         ("Expense", "Food & Snacks", 250, "Physical Cash", "Need"))
        tool_msg = server.requests[1]["messages"][-1]
        self.assertEqual((tool_msg["role"], tool_msg["tool_name"]), ("tool", "add_transaction"))
        self.assertIn('"new_balance": 750.0', tool_msg["content"])
        req = server.requests[0]
        self.assertFalse(req["stream"])
        self.assertEqual(req["tools"][0]["type"], "function")
        self.assertIn("parameters", req["tools"][0]["function"])

    def test_bad_input_is_sent_back_as_error(self):
        chat, server = self.ollama_chat([
            ollama_call("add_transaction", date="2026-11-16", type="Expense", category="Snacks",
                        amount=100, account="Physical Cash", note="Samosa"),
            ollama_text("Which category?"),
        ])
        chat.send("100 ka samosa")
        self.assertIn("not a valid category", server.requests[1]["messages"][-1]["content"])
        self.assertEqual(self.db.transactions(), [])

    def test_string_arguments_and_think_tags(self):
        reply = {"role": "assistant", "content": "<think>hmm</think>",
                 "tool_calls": [{"function": {"name": "get_overview", "arguments": "{}"}}]}
        chat, _ = self.ollama_chat([reply, ollama_text("<think>ok</think>Net worth PKR 1,000")])
        self.assertEqual(chat.send("kitne paise hain?"), "Net worth PKR 1,000")

    def test_declined_and_history(self):
        chat, server = self.ollama_chat([
            ollama_call("add_transaction", date="2026-11-16", type="Income", category="Pocket Money",
                        amount=500, account="Physical Cash", note="Ammi"),
            ollama_text("Theek hai, save nahi kiya."),
            ollama_text("Salam!"),
        ], answer=False)
        chat.send("Ammi ne 500 diye")
        chat.send("salam")
        self.assertEqual(self.db.transactions(), [])
        roles = [m["role"] for m in server.requests[-1]["messages"]]
        self.assertEqual(roles, ["system", "user", "assistant", "tool", "assistant", "user"])

    def test_failed_turn_is_rolled_back(self):
        chat, server = self.ollama_chat([ollama_text("hi")])
        chat.send("salam")
        with self.assertRaises(IndexError):        # no scripted reply left = like a crash
            chat.send("hello?")
        self.assertEqual(len(chat.brain.messages), 3)


class ClaudeTest(Base):
    def test_claude_brain_still_works(self):
        client = FakeClaude([
            FakeResponse("tool_use", [NS(type="tool_use", id="t1", name="remember",
                                         input={"fact": "Saving for an SSD"})]),
            FakeResponse("end_turn", [NS(type="text", text="Noted!")]),
        ])
        tools = MoneyTools(self.db, self.confirm(), TODAY)
        brain = ClaudeBrain([INSTRUCTIONS, "snapshot"], tools.schemas(), client=client)
        chat = MoneyChat(self.db, brain=brain, today=TODAY, show=lambda t: None)
        self.assertEqual(chat.send("saving for an SSD"), "Noted!")
        self.assertEqual([m["fact"] for m in self.db.memories()], ["Saving for an SSD"])
        result = client.requests[1]["messages"][-1]["content"][0]
        self.assertEqual(result["tool_use_id"], "t1")
        self.assertEqual(client.requests[0]["fallbacks"], "default")


class SnapshotTest(Base):
    def test_local_snapshot_is_compact(self):
        for i in range(40):
            self.db.add_transaction(Transaction(date(2026, 11, 2), "Expense", "Transport", 100 + i,
                                                "Physical Cash", f"ride {i}", "Need"))
        self.db.add_memory("Walks to university")
        full, compact = snapshot(self.db, TODAY), snapshot(self.db, TODAY, full_ledger=False)
        self.assertIn('"ride 0"', full)
        self.assertNotIn('"ride 0"', compact)
        self.assertIn("ride 39", compact)
        self.assertIn("Walks to university", compact)
        self.assertLess(len(compact), len(full))


if __name__ == "__main__":
    unittest.main()

"""The 'brains' WalletWise AI can talk to.

* OllamaBrain (default, FREE): runs an open AI model on your own computer with Ollama.
  No account, no API key, no internet needed after the download, and your data never leaves your laptop.
* ClaudeBrain (optional, paid): Anthropic's Claude API. Smarter and faster, but costs a little per message.

Both have the same small interface, so the chat code (assistant.py) doesn't care which one it uses:
    add_user(text)       -> add your message
    step()               -> ask the model, get back its text and the tools it wants to call
    add_results(results) -> give the tool results back to the model
    mark() / rollback()  -> undo a half-finished turn after an error
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

DEFAULT_OLLAMA_MODEL = "qwen2.5:3b"
DEFAULT_CLAUDE_MODEL = "claude-opus-5-5"


class BrainError(Exception):
    """A problem with a friendly message we can show to the user as-is."""


@dataclass
class ToolCall:
    id: str
    name: str
    args: Dict[str, Any]


@dataclass
class Step:
    texts: List[str] = field(default_factory=list)
    calls: List[ToolCall] = field(default_factory=list)
    stopped: str = ""          # "" = normal, "max_tokens" = cut off, "refusal" = model declined


# (tool call, result text, is_error)
ToolResult = Tuple[ToolCall, str, bool]

THINK_TAGS = re.compile(r"<think>.*?</think>", re.S)


# ====================================================================== Ollama (free, local)

class OllamaBrain:
    name = "Ollama (free, on your computer)"

    def __init__(self, system: str, tools: Sequence[Dict[str, Any]], model: Optional[str] = None,
                 host: Optional[str] = None, post: Optional[Callable[[str, dict], dict]] = None):
        self.model = model or os.environ.get("WALLETWISE_MODEL") or DEFAULT_OLLAMA_MODEL
        host = host or os.environ.get("OLLAMA_HOST") or "http://localhost:11434"
        self.host = (host if host.startswith("http") else f"http://{host}").rstrip("/")
        self.num_ctx = int(os.environ.get("WALLETWISE_CTX", "8192"))
        self.messages: List[Dict[str, Any]] = [{"role": "system", "content": system}]
        self.tools = [{"type": "function",
                       "function": {"name": t["name"], "description": t["description"],
                                    "parameters": t["input_schema"]}} for t in tools]
        self._post = post or self._http_post

    # -- interface
    def mark(self) -> int:
        return len(self.messages)

    def rollback(self, mark: int) -> None:
        del self.messages[mark:]

    def add_user(self, text: str) -> None:
        self.messages.append({"role": "user", "content": text})

    def step(self) -> Step:
        data = self._post("/api/chat", {
            "model": self.model,
            "messages": self.messages,
            "tools": self.tools,
            "stream": False,
            "keep_alive": "30m",                       # keep the model loaded while you chat
            "options": {"num_ctx": self.num_ctx, "temperature": 0.3},
        })
        msg = data.get("message") or {}
        raw_calls = msg.get("tool_calls") or []
        saved = {"role": "assistant", "content": msg.get("content", "")}
        if raw_calls:
            saved["tool_calls"] = raw_calls
        self.messages.append(saved)

        calls = []
        for i, tc in enumerate(raw_calls):
            fn = tc.get("function") or {}
            args = fn.get("arguments") or {}
            if isinstance(args, str):                  # some models send the arguments as a JSON string
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    args = {}
            calls.append(ToolCall(id=tc.get("id") or f"call_{i}", name=fn.get("name", ""),
                                  args=args if isinstance(args, dict) else {}))
        text = THINK_TAGS.sub("", msg.get("content") or "").strip()
        return Step(texts=[text] if text else [], calls=calls,
                    stopped="max_tokens" if data.get("done_reason") == "length" else "")

    def add_results(self, results: List[ToolResult]) -> None:
        for call, content, _ in results:
            self.messages.append({"role": "tool", "content": content, "tool_name": call.name})

    # -- setup check
    def check(self) -> None:
        """Make sure Ollama is running and the model is downloaded, with clear help if not."""
        try:
            with urllib.request.urlopen(f"{self.host}/api/tags", timeout=5) as r:
                models = [m.get("name", "") for m in json.load(r).get("models", [])]
        except (urllib.error.URLError, OSError):
            raise BrainError(
                f"Ollama is not running at {self.host}.\n"
                "   1. Install it (free) from https://ollama.com/download\n"
                "   2. Open the Ollama app (it runs in the background)\n"
                f"   3. Download the model once:  ollama pull {self.model}")
        wanted = self.model if ":" in self.model else f"{self.model}:latest"
        if wanted not in models:
            have = ", ".join(models) or "none yet"
            raise BrainError(f"The model '{self.model}' isn't downloaded (you have: {have}).\n"
                             f"   Run once:  ollama pull {self.model}")

    def _http_post(self, path: str, body: dict) -> dict:
        req = urllib.request.Request(f"{self.host}{path}", data=json.dumps(body).encode("utf-8"),
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=900) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            try:
                detail = json.load(e).get("error", "")
            except (ValueError, OSError):
                detail = ""
            if "not found" in detail:
                raise BrainError(f"Model '{self.model}' not found. Run:  ollama pull {self.model}")
            if "does not support tools" in detail:
                raise BrainError(f"'{self.model}' can't use tools. Try:  set WALLETWISE_MODEL={DEFAULT_OLLAMA_MODEL}")
            raise BrainError(f"Ollama error ({e.code}): {detail or e.reason}")
        except (urllib.error.URLError, OSError) as e:
            raise BrainError(f"Can't reach Ollama at {self.host} ({e}). Is the Ollama app running?")


# ====================================================================== Claude (optional, paid)

class ClaudeBrain:
    name = "Claude API (paid)"
    FALLBACK_BETA = "server-side-fallback-2026-07-01"

    def __init__(self, system_parts: Sequence[str], tools: Sequence[Dict[str, Any]],
                 model: Optional[str] = None, client: Any = None):
        if client is None:
            try:
                import anthropic
            except ImportError:
                raise BrainError("The Claude brain needs the Anthropic SDK:  pip install anthropic")
            client = anthropic.Anthropic()
        self.client = client
        self.model = model or os.environ.get("WALLETWISE_MODEL") or DEFAULT_CLAUDE_MODEL
        self.effort = os.environ.get("WALLETWISE_EFFORT", "medium")
        self.system = [{"type": "text", "text": part} for part in system_parts]
        self.tools = list(tools)
        self.messages: List[Dict[str, Any]] = []

    def mark(self) -> int:
        return len(self.messages)

    def rollback(self, mark: int) -> None:
        del self.messages[mark:]

    def add_user(self, text: str) -> None:
        self.messages.append({"role": "user", "content": text})

    def step(self) -> Step:
        response = self.client.beta.messages.create(
            model=self.model,
            max_tokens=16000,
            system=self.system,
            messages=self.messages,
            tools=self.tools,
            output_config={"effort": self.effort},
            cache_control={"type": "ephemeral"},   # cache the long money story between messages
            betas=[self.FALLBACK_BETA],
            fallbacks="default",                   # if a request is declined, retry on a fallback model
        )
        if response.stop_reason == "refusal":
            return Step(stopped="refusal")
        self.messages.append(response.to_param())
        texts = [b.text for b in response.content if b.type == "text" and b.text.strip()]
        calls = [ToolCall(b.id, b.name, dict(b.input)) for b in response.content if b.type == "tool_use"]
        return Step(texts, calls, "max_tokens" if response.stop_reason == "max_tokens" else "")

    def add_results(self, results: List[ToolResult]) -> None:
        self.messages.append({"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": call.id, "content": content, "is_error": is_error}
            for call, content, is_error in results]})

    def check(self) -> None:
        pass

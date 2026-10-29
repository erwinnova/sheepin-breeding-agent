"""
Sheepin Breeding Agent: tool-calling loop over an OpenAI-compatible chat API.
"""

import json
import os
import sys
from datetime import datetime

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # run from any directory

from openai import OpenAI

from backend_stub import Backend

HERE = os.path.dirname(os.path.abspath(__file__))
MAX_ROUNDS = 8

PROVIDERS = {
    "baseten": {"base_url": "https://inference.baseten.co/v1", "key_env": "BASETEN_API_KEY",
                "model": "meta-models/muse-spark-open-1026"},
    "meta": {"base_url": os.environ.get("META_BASE_URL", ""), "key_env": "META_API_KEY",
             "model": os.environ.get("META_MODEL", "")},
}


def load_tools():
    with open(os.path.join(HERE, "tools.json"), encoding="utf-8") as f:
        return json.load(f)


def load_prompt(now, tz, farm="Sheepin model farm"):
    with open(os.path.join(HERE, "system_prompt.txt"), encoding="utf-8") as f:
        p = f.read()
    return (p.replace("{NOW_ISO}", now.strftime("%Y-%m-%dT%H:%M:%S"))
             .replace("{NOW_HUMAN}", now.strftime("%A %d %B %Y, %H:%M"))
             .replace("{TZ}", tz).replace("{FARM_NAME}", farm))


class Agent:
    def __init__(self, provider=None, backend=None, now=None, tz=None, verbose=False):
        provider = provider or os.environ.get("PROVIDER", "baseten")
        cfg = PROVIDERS[provider]
        if not cfg["base_url"] or not cfg["model"]:
            raise SystemExit(f"provider {provider}: base_url/model not configured (see env in agent.py)")
        self.client = OpenAI(base_url=cfg["base_url"], api_key=os.environ[cfg["key_env"]])
        self.model = cfg["model"]
        self.provider = provider
        self.now = now or (datetime.fromisoformat(os.environ["AGENT_NOW"]) if os.environ.get("AGENT_NOW") else datetime.now())
        self.tz = tz or os.environ.get("AGENT_TZ", "Asia/Jakarta")
        self.backend = backend or Backend(now=self.now)
        self.tools = load_tools()
        self.messages = [{"role": "system", "content": load_prompt(self.now, self.tz)}]
        self.calls = []          # every tool call made, for tests and the comparison page
        self.verbose = verbose
        self.usage = {"prompt": 0, "completion": 0, "reasoning": 0}

    def _assistant_message(self, msg):
        """Strip reasoning fields before echoing the assistant turn back to the API."""
        out = {"role": "assistant", "content": msg.content or ""}
        if msg.tool_calls:
            out["tool_calls"] = [{"id": c.id, "type": "function",
                                  "function": {"name": c.function.name, "arguments": c.function.arguments}}
                                 for c in msg.tool_calls]
        return out

    def send(self, text):
        """One user turn. Returns the agent's final text; tool calls are logged in self.calls."""
        self.messages.append({"role": "user", "content": text})
        for _ in range(MAX_ROUNDS):
            r = self.client.chat.completions.create(
                model=self.model, messages=self.messages, tools=self.tools, tool_choice="auto", temperature=0.1)
            u = r.usage
            if u:
                self.usage["prompt"] += u.prompt_tokens or 0
                self.usage["completion"] += u.completion_tokens or 0
                det = getattr(u, "completion_tokens_details", None)
                self.usage["reasoning"] += getattr(det, "reasoning_tokens", 0) or 0
            msg = r.choices[0].message
            self.messages.append(self._assistant_message(msg))
            if not msg.tool_calls:
                return msg.content or ""
            for c in msg.tool_calls:
                try:
                    args = json.loads(c.function.arguments or "{}")
                except json.JSONDecodeError:
                    args = {"_raw": c.function.arguments}
                result = self.backend.dispatch(c.function.name, args) if "_raw" not in args \
                    else {"ok": False, "error": "argumen bukan JSON yang valid"}
                self.calls.append({"name": c.function.name, "args": args, "result": result})
                if self.verbose:
                    print(f"  -> {c.function.name}({json.dumps(args, ensure_ascii=False)})")
                    print(f"  <- {json.dumps(result, ensure_ascii=False)[:300]}")
                self.messages.append({"role": "tool", "tool_call_id": c.id,
                                      "content": json.dumps(result, ensure_ascii=False)})
        return "(berhenti: terlalu banyak putaran tool call)"


def main():
    agent = Agent(verbose=True)
    print(f"provider={agent.provider} model={agent.model} now={agent.now:%Y-%m-%d %H:%M}")
    if len(sys.argv) > 1:
        print(agent.send(" ".join(sys.argv[1:])))
        return
    print("Ketik catatan peternak (kosong untuk keluar).")
    while True:
        try:
            text = input("> ").strip()
        except EOFError:
            break
        if not text:
            break
        print(agent.send(text))
    print("tokens:", agent.usage)


if __name__ == "__main__":
    main()
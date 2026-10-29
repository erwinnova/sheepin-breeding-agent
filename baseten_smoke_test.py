"""
Smoke test for Muse Spark Open on Baseten (Meta hackathon).
"""

import json
import os

from openai import OpenAI

MODEL = "meta-models/muse-spark-open-1026"
client = OpenAI(base_url="https://inference.baseten.co/v1",
                api_key=os.environ["BASETEN_API_KEY"])

NOTE = ("0266 dikawinkan dengan pejantan 0931 tadi pagi jam 7, "
        "0744 beranak dua, satu mati.")

TOOLS = [
    {"type": "function", "function": {
        "name": "catat_kawin",
        "description": "Record a mating event for a ewe.",
        "parameters": {"type": "object", "properties": {
            "ear_tag": {"type": "string"},
            "pejantan": {"type": "string"},
            "waktu": {"type": "string", "description": "ISO time, or as stated"}},
            "required": ["ear_tag", "pejantan"]}}},
    {"type": "function", "function": {
        "name": "catat_beranak",
        "description": "Record a lambing event.",
        "parameters": {"type": "object", "properties": {
            "ear_tag": {"type": "string"},
            "lahir": {"type": "integer"},
            "mati": {"type": "integer"},
            "waktu": {"type": "string"}},
            "required": ["ear_tag", "lahir"]}}},
]


def show_reasoning(msg):
    for field in ("reasoning_content", "reasoning"):
        value = getattr(msg, field, None) or (msg.model_extra or {}).get(field)
        if value:
            print(f"  reasoning field '{field}': {str(value)[:120]}...")
            return
    print("  no separate reasoning field (check if it is inside content)")


def test_basic():
    print("\n[1] basic call")
    r = client.chat.completions.create(
        model=MODEL, messages=[{"role": "user", "content": "Reply with one word: ok"}])
    m = r.choices[0].message
    print("  content:", repr(m.content)[:200])
    show_reasoning(m)
    print("  usage:", r.usage)


def test_tools():
    print("\n[2] tool calling")
    r = client.chat.completions.create(
        model=MODEL, tools=TOOLS, tool_choice="auto",
        messages=[
            {"role": "system", "content": "Turn the farmer's note into tool calls. "
             "Call one tool per event. Do not invent values that are not in the note."},
            {"role": "user", "content": NOTE}])
    m = r.choices[0].message
    calls = m.tool_calls or []
    print(f"  tool calls returned: {len(calls)} (expected 2)")
    for c in calls:
        print("   ", c.function.name, c.function.arguments)
    if not calls:
        print("  content instead:", repr(m.content)[:300])


def test_json():
    print("\n[3] JSON-only output")
    r = client.chat.completions.create(
        model=MODEL, response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": "Return ONLY JSON: {\"events\": [{\"type\": "
             "\"kawin\"|\"beranak\", \"ear_tag\": str, \"pejantan\": str|null, "
             "\"lahir\": int|null, \"mati\": int|null, \"waktu\": str|null}]}"},
            {"role": "user", "content": NOTE}])
    text = r.choices[0].message.content
    try:
        print("  parsed:", json.dumps(json.loads(text), ensure_ascii=False))
    except Exception as e:
        print("  NOT valid JSON:", e, repr(text)[:300])


for test in (test_basic, test_tools, test_json):
    try:
        test()
    except Exception as e:
        print(f"  FAILED: {type(e).__name__}: {e}")
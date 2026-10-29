"""
Run test_cases.json against a provider and report pass/fail.
"""

import json
import os
import sys
import time
from datetime import datetime

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # run from any directory

from agent import Agent
from backend_stub import Backend

HERE = os.path.dirname(os.path.abspath(__file__))
RECORD = {"catat_birahi", "catat_kawin", "catat_cek_bunting", "catat_beranak",
          "catat_keguguran", "catat_sapih", "catat_bcs", "larang_kawin"}


def check(case, calls, reply):
    problems = []
    names = [c["name"] for c in calls]
    exp = case.get("expect_calls", [])
    exp_record = [e for e in exp if e["name"] in RECORD]
    got_record = [c for c in calls if c["name"] in RECORD]
    if any(e["name"] == "cari_ternak" for e in exp) and "cari_ternak" not in names:
        problems.append("tidak memanggil cari_ternak")
    if sorted(e["name"] for e in exp_record) != sorted(c["name"] for c in got_record):
        problems.append(f"record calls {sorted(c['name'] for c in got_record)} != expected {sorted(e['name'] for e in exp_record)}")
    for e in exp_record:
        match = [c for c in got_record if c["name"] == e["name"]]
        for k, v in e.get("args", {}).items():
            if not any(c["args"].get(k) == v for c in match):
                problems.append(f"{e['name']}.{k} != {v!r} (got {[c['args'].get(k) for c in match]})")
    for c in got_record:
        if not c["result"].get("ok", False):
            problems.append(f"{c['name']} ditolak backend: {c['result'].get('error')}")
    if case.get("expect_question"):
        if got_record:
            problems.append("harusnya bertanya, tetapi mencatat")
        if "?" not in reply:
            problems.append("harusnya bertanya, tidak ada tanda tanya")
    if not exp and not case.get("expect_question") and calls:
        problems.append("harusnya tidak memanggil fungsi apa pun")
    return problems


def main():
    out = None
    if "--out" in sys.argv:
        out = sys.argv[sys.argv.index("--out") + 1]
    now = datetime.fromisoformat(os.environ.get("AGENT_NOW", "2026-10-29T18:00:00"))
    with open(os.path.join(HERE, "test_cases.json"), encoding="utf-8") as f:
        cases = json.load(f)
    results, passed = [], 0
    for case in cases:
        agent = Agent(backend=Backend(now=now), now=now)
        t0 = time.time()
        try:
            reply = agent.send(case["input"])
            err = None
        except Exception as e:  # keep going so one failure does not hide the rest
            reply, err = "", f"{type(e).__name__}: {e}"
        dt = time.time() - t0
        problems = [err] if err else check(case, agent.calls, reply)
        ok = not problems
        passed += ok
        print(f"[{'PASS' if ok else 'FAIL'}] #{case['id']} ({dt:.1f}s) {case['input'][:60]}")
        for p in problems:
            print("       -", p)
        results.append({"id": case["id"], "input": case["input"], "pass": ok, "problems": problems,
                        "calls": agent.calls, "reply": reply, "seconds": round(dt, 1), "usage": agent.usage})
    print(f"\n{passed}/{len(cases)} passed  provider={os.environ.get('PROVIDER', 'baseten')}")
    if out:
        with open(out, "w", encoding="utf-8") as f:
            json.dump({"provider": os.environ.get("PROVIDER", "baseten"), "now": now.isoformat(),
                       "passed": passed, "total": len(cases), "results": results}, f, ensure_ascii=False, indent=2)
        print("saved", out)


if __name__ == "__main__":
    main()
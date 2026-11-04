"""
Sheepin Breeding Agent demo server.
"""

import base64
import os
import re
import sys
import threading
import time
from datetime import datetime, timedelta

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from agent import Agent                      # noqa: E402
from backend_stub import Backend, LAMA_BUNTING, CEK_ULANG, USG, SAPIH  # noqa: E402
from transcribe import transcribe            # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
app = FastAPI(title="Sheepin Breeding Agent")

SESSION_TTL_H = float(os.environ.get("SESSION_TTL_H", "6"))
MAX_SESSIONS = int(os.environ.get("MAX_SESSIONS", "200"))
_SID_OK = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_LOCK = threading.Lock()
SESSIONS = {}   # sid -> {"backend": Backend, "agent": Agent | None, "seen": epoch seconds}


def _session(sid: str) -> dict:
    sid = sid if sid and _SID_OK.match(sid) else "public"
    now = time.time()
    with _LOCK:
        for k in [k for k, v in SESSIONS.items() if now - v["seen"] > SESSION_TTL_H * 3600]:
            del SESSIONS[k]
        if sid not in SESSIONS:
            if len(SESSIONS) >= MAX_SESSIONS:                      # drop the least recently used
                del SESSIONS[min(SESSIONS, key=lambda k: SESSIONS[k]["seen"])]
            SESSIONS[sid] = {"backend": Backend(), "agent": None, "seen": now}
        s = SESSIONS[sid]
        s["seen"] = now
        return s


def _backend(sid: str) -> Backend:
    return _session(sid)["backend"]


def _agent(sid: str) -> Agent:
    s = _session(sid)
    if s["agent"] is None:
        s["agent"] = Agent(backend=s["backend"])
    return s["agent"]


class ChatIn(BaseModel):
    session_id: str
    text: str


class AudioIn(BaseModel):
    audio_b64: str
    mime: str = "audio/wav"


@app.get("/")
def index():
    path = os.path.join(HERE, "static", "index.html")
    if not os.path.exists(path):
        raise HTTPException(500, f"static/index.html tidak ditemukan; letakkan di {path}")
    return FileResponse(path)


@app.post("/api/chat")
def chat(body: ChatIn, x_session_id: str = Header(default="")):
    ag = _agent(body.session_id or x_session_id)
    n0 = len(ag.calls)
    reply = ag.send(body.text)
    return {"reply": reply, "calls": ag.calls[n0:], "usage": ag.usage, "provider": ag.provider, "model": ag.model}


@app.post("/api/transcribe")
def transcribe_audio(body: AudioIn):
    try:
        audio = base64.b64decode(body.audio_b64)
    except Exception:
        raise HTTPException(400, "audio_b64 tidak valid")
    if len(audio) > 25 * 1024 * 1024:
        raise HTTPException(413, "rekaman lebih dari 25 MB")
    return transcribe(audio, body.mime)


def _calendar(b: Backend, tag: str):
    """Derived status and upcoming dates. Windows that have already passed are dropped;
    a mating whose re-check window passed with no estrus recorded becomes 'indikasi_bunting'."""
    a = b.animals[tag]
    today = b.now.date()
    evs = [e for e in b.events if e["ear_tag"] == tag]
    status = a.get("status")
    last_kawin = next((e for e in reversed(evs) if e["jenis"] == "kawin"), None) or \
        ({"waktu": a["kawin_terakhir"]["waktu"]} if a.get("kawin_terakhir") else None)
    last_beranak = next((e for e in reversed(evs) if e["jenis"] == "beranak"), None)
    nxt = []
    if status in ("dikawinkan", "indikasi_bunting", "bunting") and last_kawin:
        k = datetime.fromisoformat(last_kawin["waktu"])
        w0, w1 = (k + timedelta(days=CEK_ULANG[0])).date(), (k + timedelta(days=CEK_ULANG[1])).date()
        if status == "dikawinkan" and today > w1:
            status = "indikasi_bunting"            # non-return to estrus
        if status == "dikawinkan":
            nxt.append({"apa": "cek birahi ulang", "mulai": w0.isoformat(), "sampai": w1.isoformat()})
        if status in ("dikawinkan", "indikasi_bunting"):
            nxt.append({"apa": "USG kebuntingan", "mulai": (k + timedelta(days=USG)).date().isoformat()})
        nxt.append({"apa": "perkiraan beranak", "mulai": (k + timedelta(days=LAMA_BUNTING)).date().isoformat()})
    if status == "menyusui" and last_beranak:
        d = datetime.fromisoformat(last_beranak["waktu"])
        nxt.append({"apa": "sapih", "mulai": (d + timedelta(days=SAPIH[0])).date().isoformat(),
                    "sampai": (d + timedelta(days=SAPIH[1])).date().isoformat()})
    nxt = [n for n in nxt if datetime.fromisoformat(n.get("sampai") or n["mulai"]).date() >= today]
    return {"status": status, "larangan_kawin": a.get("larangan_kawin"), "berikutnya": nxt}


@app.get("/api/herd")
def herd(x_session_id: str = Header(default="")):
    b = _backend(x_session_id)
    rows = []
    for tag, a in b.animals.items():
        row = {k: a.get(k) for k in ("ear_tag", "jenis_kelamin", "ras", "umur_bulan", "status", "dam", "sire", "tanggal_lahir")}
        row["kalender"] = _calendar(b, tag) if a.get("jenis_kelamin") == "betina" else None
        if row["kalender"]:
            row["status"] = row["kalender"]["status"]   # derived status (e.g. indikasi_bunting)
        rows.append(row)
    return {"ternak": rows, "jumlah_kejadian": len(b.events)}


@app.get("/api/events")
def events(x_session_id: str = Header(default="")):
    return {"kejadian": list(reversed(_backend(x_session_id).events))}


@app.get("/api/silsilah/{tag}")
def silsilah(tag: str, x_session_id: str = Header(default="")):
    t = _backend(x_session_id).silsilah(tag)
    if not t:
        raise HTTPException(404, "ear tag tidak ada")
    return t


@app.get("/api/hari_ini")
def hari_ini(hari_ke_depan: int = 7, x_session_id: str = Header(default="")):
    return _backend(x_session_id).ringkasan_hari_ini(hari_ke_depan)


@app.get("/api/prediksi/{tag}")
def prediksi(tag: str, x_session_id: str = Header(default="")):
    r = _backend(x_session_id).prediksi_induk(tag)
    if not r.get("ok"):
        raise HTTPException(404, r.get("error"))
    return r


@app.post("/api/reset")
def reset(x_session_id: str = Header(default="")):
    s = _session(x_session_id)
    with _LOCK:
        s["backend"], s["agent"] = Backend(), None
    return {"ok": True}


@app.get("/api/health")   # not /healthz: Cloud Run reserves paths ending in "z"
def health():
    return {"ok": True, "sessions": len(SESSIONS)}

# ---------- test results page ----------
RESULT_FILES = [("results_baseten.json", "Muse Spark Open (Baseten, open weights)"),
                ("results_meta.json", "Muse Spark (Meta Model API)")]


@app.get("/compare")
def compare_page():
    path = os.path.join(HERE, "static", "compare.html")
    if not os.path.exists(path):
        raise HTTPException(500, f"static/compare.html tidak ditemukan; letakkan di {path}")
    return FileResponse(path)


@app.get("/api/results")
def results():
    import json
    with open(os.path.join(HERE, "test_cases.json"), encoding="utf-8") as f:
        cases = json.load(f)
    runs = []
    for fn, label in RESULT_FILES:
        p = os.path.join(HERE, fn)
        if os.path.exists(p):
            with open(p, encoding="utf-8") as f:
                r = json.load(f)
            runs.append({"label": label, "provider": r.get("provider"), "model": r.get("model") or _model_of(r),
                         "now": r.get("now"), "passed": r.get("passed"), "total": r.get("total"), "results": r.get("results", [])})
    return {"cases": cases, "runs": runs}


def _model_of(r):
    from agent import PROVIDERS
    return PROVIDERS.get(r.get("provider", ""), {}).get("model", "")
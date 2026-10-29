"""
Sheepin Breeding Agent demo server.
"""

import base64
import os
import sys
from datetime import datetime, timedelta

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from agent import Agent                      # noqa: E402
from backend_stub import Backend, LAMA_BUNTING, CEK_ULANG, USG, SAPIH  # noqa: E402
from transcribe import transcribe            # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
app = FastAPI(title="Sheepin Breeding Agent")

STATE = {"backend": Backend(), "agents": {}}


def _agent(session_id: str) -> Agent:
    if session_id not in STATE["agents"]:
        STATE["agents"][session_id] = Agent(backend=STATE["backend"])
    return STATE["agents"][session_id]


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
def chat(body: ChatIn):
    ag = _agent(body.session_id)
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
def herd():
    b = STATE["backend"]
    rows = []
    for tag, a in b.animals.items():
        row = {k: a.get(k) for k in ("ear_tag", "jenis_kelamin", "ras", "umur_bulan", "status", "dam", "sire", "tanggal_lahir")}
        row["kalender"] = _calendar(b, tag) if a.get("jenis_kelamin") == "betina" else None
        if row["kalender"]:
            row["status"] = row["kalender"]["status"]   # derived status (e.g. indikasi_bunting)
        rows.append(row)
    return {"ternak": rows, "jumlah_kejadian": len(b.events)}


@app.get("/api/events")
def events():
    return {"kejadian": list(reversed(STATE["backend"].events))}


@app.get("/api/silsilah/{tag}")
def silsilah(tag: str):
    t = STATE["backend"].silsilah(tag)
    if not t:
        raise HTTPException(404, "ear tag tidak ada")
    return t


@app.post("/api/reset")
def reset():
    STATE["backend"] = Backend()
    STATE["agents"] = {}
    return {"ok": True}
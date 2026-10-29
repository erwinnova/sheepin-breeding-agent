"""
In-memory backend for the Sheepin Breeding Agent.
"""

import json
import os
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))

# Reproductive constants (sheep, agreed with the partner vet)
SIKLUS_BIRAHI = 17          # days
CEK_ULANG = (17, 21)        # days after mating
USG = 60                    # days after mating
LAMA_BUNTING = 147          # days
SAPIH = (60, 90)            # days after lambing


def _iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S")


def _parse(s):
    return datetime.fromisoformat(s)


class Backend:
    def __init__(self, herd_path=None, now=None):
        path = herd_path or os.path.join(HERE, "herd_fixture.json")
        with open(path, encoding="utf-8") as f:
            herd = json.load(f)
        self.animals = {a["ear_tag"]: dict(a, larangan_kawin=None) for a in herd}
        self.events = []
        self.now = now or datetime.now()
        self._next_tag = 9001

    # ---------- helpers ----------
    def _log(self, kind, ear_tag, waktu, **data):
        ev = {"id": len(self.events) + 1, "jenis": kind, "ear_tag": ear_tag,
              "waktu": waktu, "dicatat": _iso(self.now), **data}
        self.events.append(ev)
        return ev

    def _check_time(self, waktu):
        try:
            dt = _parse(waktu)
        except Exception:
            return None, f"waktu '{waktu}' bukan format ISO 8601 (contoh 2026-10-29T07:00:00)"
        if dt > self.now + timedelta(minutes=5):
            return None, f"waktu {waktu} berada di masa depan (sekarang {_iso(self.now)})"
        return dt, None

    def _female(self, tag):
        a = self.animals.get(tag)
        if not a:
            return None, f"ear tag {tag} tidak ada di kawanan"
        if a["jenis_kelamin"] != "betina":
            return None, f"{tag} adalah {a['jenis_kelamin']}, bukan betina"
        return a, None

    def _last(self, tag, kind):
        evs = [e for e in self.events if e["ear_tag"] == tag and e["jenis"] == kind]
        if evs:
            return evs[-1]
        a = self.animals.get(tag, {})
        if kind == "kawin" and a.get("kawin_terakhir"):
            k = a["kawin_terakhir"]
            return {"jenis": "kawin", "ear_tag": tag, "waktu": k["waktu"], "pejantan": k["pejantan"]}
        return None

    # ---------- tools ----------
    def cari_ternak(self, ear_tag):
        q = str(ear_tag).strip().upper()
        hits = [a for t, a in self.animals.items() if t.upper() == q]
        if not hits:
            hits = [a for t, a in self.animals.items() if t.upper().endswith(q) or q in t.upper()]
        out = []
        for a in hits[:5]:
            out.append({k: a.get(k) for k in ("ear_tag", "jenis_kelamin", "ras", "umur_bulan", "status", "larangan_kawin")})
        return {"ditemukan": len(out), "ternak": out}

    def catat_birahi(self, ear_tag, waktu, waktu_perkiraan=False, tanda=None, ada_pejantan=None, catatan=""):
        a, err = self._female(ear_tag)
        if err:
            return {"ok": False, "error": err}
        dt, err = self._check_time(waktu)
        if err:
            return {"ok": False, "error": err}
        warnings = []
        if a["status"] == "bunting":
            warnings.append("status tercatat bunting; birahi pada induk bunting tidak lazim, periksa kembali")
        if a["status"] in ("dikawinkan", "indikasi_bunting"):
            warnings.append("kembali birahi setelah kawin: kawin sebelumnya dianggap gagal, status menjadi kosong")
            a["status"] = "kosong"
        ev = self._log("birahi", ear_tag, _iso(dt), waktu_perkiraan=bool(waktu_perkiraan),
                       tanda=tanda or [], ada_pejantan=ada_pejantan, catatan=catatan)
        return {"ok": True, "event": ev, "status": a["status"], "peringatan": warnings,
                "kalender": {"perkiraan_birahi_berikutnya": _iso(dt + timedelta(days=SIKLUS_BIRAHI))}}

    def catat_kawin(self, ear_tag, pejantan, waktu, metode="alam", waktu_perkiraan=False, cara_diketahui=None, catatan=""):
        a, err = self._female(ear_tag)
        if err:
            return {"ok": False, "error": err}
        if metode == "alam":
            p = self.animals.get(pejantan)
            if not p:
                return {"ok": False, "error": f"pejantan {pejantan} tidak ada di kawanan"}
            if p["jenis_kelamin"] != "jantan":
                return {"ok": False, "error": f"{pejantan} adalah betina, bukan pejantan"}
        dt, err = self._check_time(waktu)
        if err:
            return {"ok": False, "error": err}
        if a.get("larangan_kawin"):
            return {"ok": False, "error": f"{ear_tag} sedang dilarang kawin: {a['larangan_kawin']}"}
        warnings = []
        if a["status"] == "bunting":
            warnings.append("status tercatat bunting; kawin pada induk bunting perlu dikonfirmasi")
        a["status"] = "dikawinkan"
        a["kawin_terakhir"] = {"pejantan": pejantan, "waktu": _iso(dt)}
        ev = self._log("kawin", ear_tag, _iso(dt), pejantan=pejantan, metode=metode,
                       waktu_perkiraan=bool(waktu_perkiraan), cara_diketahui=cara_diketahui, catatan=catatan)
        kal = {"cek_birahi_ulang": [_iso(dt + timedelta(days=CEK_ULANG[0])), _iso(dt + timedelta(days=CEK_ULANG[1]))],
               "usg": _iso(dt + timedelta(days=USG)),
               "perkiraan_beranak": _iso(dt + timedelta(days=LAMA_BUNTING))}
        return {"ok": True, "event": ev, "status": a["status"], "peringatan": warnings, "kalender": kal}

    def catat_cek_bunting(self, ear_tag, waktu, metode, hasil, jumlah_janin=None, pemeriksa=None, catatan=""):
        a, err = self._female(ear_tag)
        if err:
            return {"ok": False, "error": err}
        dt, err = self._check_time(waktu)
        if err:
            return {"ok": False, "error": err}
        warnings = []
        kal = {}
        last = self._last(ear_tag, "kawin")
        if hasil == "bunting":
            a["status"] = "bunting"
            if last:
                kal["perkiraan_beranak"] = _iso(_parse(last["waktu"]) + timedelta(days=LAMA_BUNTING))
            else:
                warnings.append("tidak ada kawin tercatat; tanggal beranak tidak bisa diperkirakan")
        elif hasil == "tidak_bunting":
            a["status"] = "kosong"
        ev = self._log("cek_bunting", ear_tag, _iso(dt), metode=metode, hasil=hasil,
                       jumlah_janin=jumlah_janin, pemeriksa=pemeriksa, catatan=catatan)
        return {"ok": True, "event": ev, "status": a["status"], "peringatan": warnings, "kalender": kal}

    def catat_beranak(self, ear_tag, waktu, jumlah_lahir, jumlah_mati=0, waktu_perkiraan=False, bantuan=None, anak=None, catatan=""):
        a, err = self._female(ear_tag)
        if err:
            return {"ok": False, "error": err}
        dt, err = self._check_time(waktu)
        if err:
            return {"ok": False, "error": err}
        if jumlah_mati > jumlah_lahir:
            return {"ok": False, "error": "jumlah mati melebihi jumlah lahir"}
        warnings = []
        last = self._last(ear_tag, "kawin")
        sire = last["pejantan"] if last else None
        if not last:
            warnings.append("tidak ada kawin tercatat; pejantan anak dicatat 'tidak diketahui'")
        prev = self._last(ear_tag, "beranak")
        hidup = jumlah_lahir - jumlah_mati
        anak = anak or []
        lambs = []
        for i in range(hidup):
            d = anak[i] if i < len(anak) else {}
            tag = d.get("ear_tag") or f"L{self._next_tag}"
            self._next_tag += 1
            lamb = {"ear_tag": tag, "jenis_kelamin": d.get("jenis_kelamin"), "ras": a.get("ras"),
                    "tanggal_lahir": _iso(dt), "dam": ear_tag, "sire": sire,
                    "bobot_lahir_kg": d.get("bobot_lahir_kg"), "status": "anak", "umur_bulan": 0,
                    "tipe_kelahiran": jumlah_lahir, "larangan_kawin": None}
            self.animals[tag] = lamb
            lambs.append(lamb)
        a["status"] = "menyusui"
        ev = self._log("beranak", ear_tag, _iso(dt), jumlah_lahir=jumlah_lahir, jumlah_mati=jumlah_mati,
                       waktu_perkiraan=bool(waktu_perkiraan), bantuan=bantuan,
                       anak=[l["ear_tag"] for l in lambs], catatan=catatan)
        kal = {"sapih": [_iso(dt + timedelta(days=SAPIH[0])), _iso(dt + timedelta(days=SAPIH[1]))]}
        if prev:
            kal["interval_beranak_hari"] = (dt - _parse(prev["waktu"])).days
        return {"ok": True, "event": ev, "status": a["status"], "anak_baru": lambs,
                "peringatan": warnings, "kalender": kal}

    def catat_keguguran(self, ear_tag, waktu, waktu_perkiraan=False, catatan=""):
        a, err = self._female(ear_tag)
        if err:
            return {"ok": False, "error": err}
        dt, err = self._check_time(waktu)
        if err:
            return {"ok": False, "error": err}
        a["status"] = "kosong"
        ev = self._log("keguguran", ear_tag, _iso(dt), waktu_perkiraan=bool(waktu_perkiraan), catatan=catatan)
        return {"ok": True, "event": ev, "status": a["status"],
                "peringatan": ["pertimbangkan larangan kawin sementara dan pemeriksaan dokter hewan"], "kalender": {}}

    def catat_sapih(self, ear_tag, waktu, bobot_sapih_kg=None, catatan=""):
        a = self.animals.get(ear_tag)
        if not a:
            return {"ok": False, "error": f"ear tag {ear_tag} tidak ada di kawanan"}
        dt, err = self._check_time(waktu)
        if err:
            return {"ok": False, "error": err}
        if a["jenis_kelamin"] == "betina" and a["status"] == "menyusui":
            a["status"] = "kosong"
        ev = self._log("sapih", ear_tag, _iso(dt), bobot_sapih_kg=bobot_sapih_kg, catatan=catatan)
        return {"ok": True, "event": ev, "status": a["status"], "peringatan": [], "kalender": {}}

    def catat_bcs(self, ear_tag, waktu, skor, penilai=None, catatan=""):
        a = self.animals.get(ear_tag)
        if not a:
            return {"ok": False, "error": f"ear tag {ear_tag} tidak ada di kawanan"}
        dt, err = self._check_time(waktu)
        if err:
            return {"ok": False, "error": err}
        if not 1 <= float(skor) <= 5:
            return {"ok": False, "error": "BCS harus antara 1 dan 5"}
        ev = self._log("bcs", ear_tag, _iso(dt), skor=float(skor), penilai=penilai, catatan=catatan)
        return {"ok": True, "event": ev, "status": a["status"], "peringatan": [], "kalender": {}}

    def larang_kawin(self, ear_tag, aksi, waktu, alasan=""):
        a = self.animals.get(ear_tag)
        if not a:
            return {"ok": False, "error": f"ear tag {ear_tag} tidak ada di kawanan"}
        dt, err = self._check_time(waktu)
        if err:
            return {"ok": False, "error": err}
        a["larangan_kawin"] = (alasan or "tanpa alasan") if aksi == "larang" else None
        ev = self._log("larangan_kawin", ear_tag, _iso(dt), aksi=aksi, alasan=alasan)
        return {"ok": True, "event": ev, "status": a["status"], "larangan_kawin": a["larangan_kawin"],
                "peringatan": [], "kalender": {}}

    # ---------- dispatch ----------
    TOOLS = ("cari_ternak", "catat_birahi", "catat_kawin", "catat_cek_bunting", "catat_beranak",
             "catat_keguguran", "catat_sapih", "catat_bcs", "larang_kawin")

    def dispatch(self, name, args):
        if name not in self.TOOLS:
            return {"ok": False, "error": f"fungsi {name} tidak dikenal"}
        try:
            return getattr(self, name)(**args)
        except TypeError as e:
            return {"ok": False, "error": f"argumen tidak sesuai: {e}"}

    # ---------- read model ----------
    def silsilah(self, ear_tag, depth=3):
        if not ear_tag or depth == 0:
            return None
        a = self.animals.get(ear_tag)
        if not a:  # known id, but no record in the herd (bought-in parent, old data)
            return {"ear_tag": ear_tag, "jenis_kelamin": None, "dam": None, "sire": None, "anak": [],
                    "tidak_ada_di_kawanan": True}
        return {"ear_tag": ear_tag, "jenis_kelamin": a.get("jenis_kelamin"),
                "dam": self.silsilah(a.get("dam"), depth - 1) if a.get("dam") else None,
                "sire": self.silsilah(a.get("sire"), depth - 1) if a.get("sire") else None,
                "anak": [t for t, x in self.animals.items() if x.get("dam") == ear_tag or x.get("sire") == ear_tag]}


if __name__ == "__main__":
    # Offline self-test of the calendar and validation logic.
    b = Backend(now=datetime(2026, 10, 29, 10, 0, 0))
    r = b.dispatch("catat_kawin", {"ear_tag": "0266", "pejantan": "0931", "waktu": "2026-10-29T07:00:00"})
    assert r["ok"] and r["kalender"]["usg"] == "2026-12-28T07:00:00" and r["kalender"]["perkiraan_beranak"].startswith("2027-03-25"), r
    r = b.dispatch("catat_kawin", {"ear_tag": "0931", "pejantan": "0266", "waktu": "2026-10-29T07:00:00"})
    assert not r["ok"], r
    r = b.dispatch("catat_beranak", {"ear_tag": "0744", "waktu": "2026-10-28T21:00:00", "jumlah_lahir": 2, "jumlah_mati": 1, "waktu_perkiraan": True})
    assert r["ok"] and len(r["anak_baru"]) == 1 and r["anak_baru"][0]["sire"] == "0931", r
    r = b.dispatch("catat_birahi", {"ear_tag": "0417", "waktu": "2026-10-29T07:00:00"})
    assert r["ok"] and r["status"] == "kosong" and r["peringatan"], r
    r = b.dispatch("catat_kawin", {"ear_tag": "0266", "pejantan": "0931", "waktu": "2026-11-05T07:00:00"})
    assert not r["ok"] and "masa depan" in r["error"], r
    print("backend self-test ok;", len(b.events), "events;", "silsilah:", json.dumps(b.silsilah(r.get("event", {}).get("anak", ["L9001"])[0] if r.get("ok") else "L9001"), ensure_ascii=False))
"""
In-memory backend for the Sheepin Breeding Agent.
"""

import json
import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

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
    def __init__(self, herd_path=None, now=None, tz=None):
        path = herd_path or os.path.join(HERE, "herd_fixture.json")
        with open(path, encoding="utf-8") as f:
            herd = json.load(f)
        self.animals = {a["ear_tag"]: dict(a, larangan_kawin=None) for a in herd}
        self.events = []
        for a in herd:                       # historical events shipped with the fixture
            for r in a.get("riwayat", []):
                self.events.append({"id": len(self.events) + 1, "ear_tag": a["ear_tag"], "dicatat": r["waktu"],
                                    "waktu_perkiraan": False, "catatan": "riwayat", **r})
        self.events.sort(key=lambda e: e["waktu"])
        self._fixed_now = now                      # fixed clock for tests; None = live local time
        self.tz = tz or os.environ.get("AGENT_TZ", "Asia/Jakarta")
        self._next_tag = 9001

    @property
    def now(self):
        """Naive local time in the farm's timezone (servers such as Cloud Run run in UTC)."""
        return self._fixed_now or datetime.now(ZoneInfo(self.tz)).replace(tzinfo=None, microsecond=0)

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

    def kerabat_dekat(self, betina, jantan):
        """Reason string if the pair is closely related (parent-offspring, grandparent,
        shared parent), else None. Uses dam/sire recorded on each animal."""
        def parents(tag):
            x = self.animals.get(tag) or {}
            return {p for p in (x.get("dam"), x.get("sire")) if p}
        pb, pj = parents(betina), parents(jantan)
        if jantan in pb:
            return f"{jantan} adalah ayah dari {betina}"
        if betina in pj:
            return f"{betina} adalah induk dari {jantan}"
        grandparents = set().union(*(parents(x) for x in pb)) if pb else set()
        if jantan in grandparents:
            return f"{jantan} adalah kakek dari {betina}"
        shared = pb & pj
        if shared:
            return f"{betina} dan {jantan} punya tetua yang sama ({', '.join(sorted(shared))})"
        return None

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
        if metode == "alam":
            reason = self.kerabat_dekat(ear_tag, pejantan)
            if reason:
                return {"ok": False, "error": f"kawin sedarah ditolak: {reason}. Pilih pejantan dari garis keturunan lain."}
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

    # ---------- predictions (deterministic + per-animal statistics) ----------
    BASE_CONCEPTION = 0.80     # typical conception rate per mating in healthy ewes (literature 80-90%)

    def _events(self, tag, kind=None):
        return [e for e in self.events if e["ear_tag"] == tag and (kind is None or e["jenis"] == kind)]

    def _cycle_stats(self, tag):
        """Per-animal estrus cycle length from recorded estrus/mating dates (days)."""
        dates = sorted({_parse(e["waktu"]).date() for e in self._events(tag) if e["jenis"] in ("birahi", "kawin")})
        gaps = []
        for a, c in zip(dates, dates[1:]):
            d = (c - a).days
            if 12 <= d <= 26:                 # one cycle; longer gaps are skipped cycles or pregnancy
                gaps.append(d)
            elif 28 <= d <= 50 and 12 <= d / 2 <= 26:
                gaps.append(d / 2)            # two cycles with one unobserved estrus
        if not gaps:
            return {"siklus_hari": SIKLUS_BIRAHI, "n": 0, "sd": None}
        m = sum(gaps) / len(gaps)
        sd = (sum((g - m) ** 2 for g in gaps) / len(gaps)) ** 0.5 if len(gaps) > 1 else None
        return {"siklus_hari": round(m, 1), "n": len(gaps), "sd": round(sd, 1) if sd is not None else None}

    def prediksi_induk(self, ear_tag):
        a, err = self._female(ear_tag)
        if err:
            return {"ok": False, "error": err}
        today = self.now.date()
        evs = self._events(ear_tag)
        last_kawin = self._last(ear_tag, "kawin")
        last_est = next((e for e in reversed(evs) if e["jenis"] in ("birahi", "kawin")), None)
        last_beranak = next((e for e in reversed(evs) if e["jenis"] == "beranak"), None)
        # an estrus/mating before the last lambing, or older than ~3 cycles, is no basis for projecting cycles
        if last_est and ((last_beranak and last_est["waktu"] < last_beranak["waktu"]) or
                         (today - _parse(last_est["waktu"]).date()).days > 3 * SIKLUS_BIRAHI + 5):
            last_est = None
        status = a["status"]
        out = {"ok": True, "ear_tag": ear_tag, "status": status, "larangan_kawin": a.get("larangan_kawin"),
               "hari_ini": today.isoformat()}

        # --- pregnancy likelihood ---
        preg = {"kemungkinan": 0.0, "dasar": "tidak ada kawin tercatat"}
        if status in ("dikawinkan", "indikasi_bunting", "bunting") and last_kawin:
            k = _parse(last_kawin["waktu"]).date()
            d = (today - k).days
            usg = next((e for e in reversed(evs) if e["jenis"] == "cek_bunting"), None)
            if status == "bunting" or (usg and usg["hasil"] == "bunting" and _parse(usg["waktu"]).date() >= k):
                preg = {"kemungkinan": 0.98, "dasar": "USG positif"}
            elif d < CEK_ULANG[0]:
                preg = {"kemungkinan": self.BASE_CONCEPTION, "dasar": f"hari ke-{d} setelah kawin; kembali birahi belum bisa dinilai"}
            elif d <= CEK_ULANG[1]:
                preg = {"kemungkinan": self.BASE_CONCEPTION, "dasar": f"hari ke-{d}: sedang dalam jendela cek birahi ulang"}
            else:
                p = min(0.92, self.BASE_CONCEPTION + 0.01 * min(d - CEK_ULANG[1], 12))
                preg = {"kemungkinan": round(p, 2), "dasar": f"tidak kembali birahi {d} hari setelah kawin; pastikan dengan USG"}
            out["perkiraan_beranak"] = (k + timedelta(days=LAMA_BUNTING)).isoformat()
            out["hari_bunting"] = d
            if status != "bunting":
                out["usg"] = (k + timedelta(days=USG)).isoformat()
        elif status == "menyusui":
            preg = {"kemungkinan": 0.0, "dasar": "sedang menyusui"}
        out["kebuntingan"] = preg

        # --- next estrus ---
        cyc = self._cycle_stats(ear_tag)
        out["siklus"] = cyc
        if status in ("kosong", "dikawinkan") and last_est:
            base = _parse(last_est["waktu"]).date()
            n = base
            while n <= today - timedelta(days=2):
                n = n + timedelta(days=round(cyc["siklus_hari"]))
            margin = 1 if (cyc["n"] >= 2 and (cyc["sd"] or 0) <= 1.5) else 2
            conf = "tinggi" if cyc["n"] >= 2 and (cyc["sd"] or 0) <= 1.5 else ("sedang" if cyc["n"] >= 1 else "rendah")
            if status == "dikawinkan":
                conf = "sedang" if conf == "tinggi" else conf
            out["birahi_berikutnya"] = {"mulai": (n - timedelta(days=margin)).isoformat(), "sampai": (n + timedelta(days=margin)).isoformat(),
                                        "keyakinan": conf, "dasar": f"{cyc['n']} siklus tercatat, rata-rata {cyc['siklus_hari']} hari" if cyc["n"] else "siklus standar 17 hari"}
            if status == "dikawinkan":
                out["birahi_berikutnya"]["catatan"] = "hanya terjadi bila kawin gagal; kalau muncul, catat sebagai birahi"
        elif status == "kosong" and not last_est:
            out["birahi_berikutnya"] = {"keyakinan": "rendah", "dasar": "belum ada birahi tercatat; amati dengan pejantan pengusik"}

        # --- lambing history ---
        lambings = sorted(_parse(e["waktu"]).date() for e in evs if e["jenis"] == "beranak")
        if lambings:
            ivals = [(c - a).days for a, c in zip(lambings, lambings[1:])]
            out["riwayat_beranak"] = {"jumlah": len(lambings), "terakhir": lambings[-1].isoformat(),
                                      "interval_hari": ivals[-1] if ivals else None}
        if last_beranak and status == "menyusui":
            d = _parse(last_beranak["waktu"]).date()
            out["sapih"] = [(d + timedelta(days=SAPIH[0])).isoformat(), (d + timedelta(days=SAPIH[1])).isoformat()]
        return out

    def ringkasan_hari_ini(self, hari_ke_depan=7):
        today = self.now.date()
        horizon = today + timedelta(days=int(hari_ke_depan or 7))
        items = []
        for tag, a in self.animals.items():
            if a.get("jenis_kelamin") != "betina" or a.get("status") == "anak":
                continue
            p = self.prediksi_induk(tag)
            if not p.get("ok"):
                continue
            if a.get("larangan_kawin"):
                items.append({"ear_tag": tag, "apa": "larangan kawin aktif", "kapan": today.isoformat(), "detail": a["larangan_kawin"]})
            if p["status"] == "dikawinkan" and p.get("hari_bunting") is not None:
                d = p["hari_bunting"]
                if CEK_ULANG[0] <= d <= CEK_ULANG[1]:
                    items.append({"ear_tag": tag, "apa": "cek birahi ulang", "kapan": today.isoformat(), "detail": f"hari ke-{d} setelah kawin"})
            if p.get("usg") and today <= _parse(p["usg"] + "T00:00:00").date() <= horizon:
                items.append({"ear_tag": tag, "apa": "jadwal USG", "kapan": p["usg"], "detail": p["kebuntingan"]["dasar"]})
            if p.get("perkiraan_beranak"):
                due = _parse(p["perkiraan_beranak"] + "T00:00:00").date()
                if due < today and p["status"] in ("bunting", "indikasi_bunting", "dikawinkan"):
                    items.append({"ear_tag": tag, "apa": "perkiraan beranak sudah lewat", "kapan": p["perkiraan_beranak"], "detail": f"{(today - due).days} hari lewat; periksa"})
                elif today <= due <= today + timedelta(days=14):
                    items.append({"ear_tag": tag, "apa": "mendekati beranak", "kapan": p["perkiraan_beranak"], "detail": f"{(due - today).days} hari lagi"})
            b = p.get("birahi_berikutnya")
            if b and b.get("mulai") and p["status"] == "kosong":
                s, e = _parse(b["mulai"] + "T00:00:00").date(), _parse(b["sampai"] + "T00:00:00").date()
                if s <= horizon and e >= today:
                    items.append({"ear_tag": tag, "apa": "perkiraan birahi", "kapan": f"{b['mulai']} - {b['sampai']}", "detail": f"keyakinan {b['keyakinan']}; siapkan pejantan"})
            if p.get("sapih") and today <= _parse(p["sapih"][1] + "T00:00:00").date() and _parse(p["sapih"][0] + "T00:00:00").date() <= horizon:
                items.append({"ear_tag": tag, "apa": "jendela sapih", "kapan": f"{p['sapih'][0]} - {p['sapih'][1]}", "detail": ""})
            if p["status"] == "kosong" and p.get("birahi_berikutnya", {}).get("keyakinan") == "rendah":
                items.append({"ear_tag": tag, "apa": "belum ada birahi tercatat", "kapan": today.isoformat(), "detail": "amati dengan pejantan pengusik"})
        order = {"perkiraan beranak sudah lewat": 0, "cek birahi ulang": 1, "mendekati beranak": 2, "perkiraan birahi": 3, "jadwal USG": 4, "jendela sapih": 5, "larangan kawin aktif": 6, "belum ada birahi tercatat": 7}
        items.sort(key=lambda i: (order.get(i["apa"], 9), i["kapan"]))
        counts = {}
        for i in items:
            counts[i["apa"]] = counts.get(i["apa"], 0) + 1
        return {"ok": True, "hari_ini": today.isoformat(), "sampai": horizon.isoformat(), "jumlah": len(items), "ringkasan": counts, "daftar": items}

    # ---------- dispatch ----------
    TOOLS = ("cari_ternak", "catat_birahi", "catat_kawin", "catat_cek_bunting", "catat_beranak",
             "catat_keguguran", "catat_sapih", "catat_bcs", "larang_kawin", "ringkasan_hari_ini", "prediksi_induk")

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
    b = Backend(now=datetime(2026, 10, 29, 18, 0, 0))   # fresh herd for prediction checks
    p = b.dispatch("prediksi_induk", {"ear_tag": "0417"})
    assert p["ok"] and p["kebuntingan"]["kemungkinan"] >= 0.8 and p["usg"] == "2026-11-19", p
    p2 = b.dispatch("prediksi_induk", {"ear_tag": "0582"})
    assert p2["ok"] and p2["siklus"]["n"] == 1 and p2["birahi_berikutnya"]["mulai"] == "2026-10-27", p2
    r = b.dispatch("ringkasan_hari_ini", {})
    assert r["ok"] and r["jumlah"] >= 2, r
    print("prediksi 0582:", p2["birahi_berikutnya"], "| ringkasan:", r["ringkasan"])
    print("backend self-test ok;", len(b.events), "events;", "silsilah:", json.dumps(b.silsilah(r.get("event", {}).get("anak", ["L9001"])[0] if r.get("ok") else "L9001"), ensure_ascii=False))

# Kalender reproduksi (dihitung backend, bukan LLM)

Semua tanggal dihitung dari kejadian yang tercatat. Konstanta (domba, sesuai praktik dokter hewan mitra):

| Konstanta | Nilai |
|---|---|
| Siklus birahi | 17 hari (rentang 14–20) |
| Jendela cek birahi ulang setelah kawin | hari 17–21 |
| USG kebuntingan | hari 60 setelah kawin |
| Lama bunting | 147 hari (rentang 144–151) |
| Sapih | 60–90 hari setelah beranak |

Status reproduksi per induk (dihitung dari kejadian terakhir):
kosong -> dikawinkan (ada kawin) -> indikasi_bunting (tidak ada birahi pada hari 17–21) -> bunting (USG positif) -> menyusui (beranak) -> kosong (sapih)
Birahi setelah kawin -> kembali ke kosong, dan kawin sebelumnya dianggap gagal.
USG negatif -> kosong. Keguguran -> kosong + saran larangan kawin sementara.

Respons backend untuk setiap catat_* mengembalikan kalender yang berubah, dan agen membacakannya ke peternak:
- catat_kawin -> cek_birahi_ulang: [tanggal+17, tanggal+21], usg: tanggal+60, perkiraan_beranak: tanggal+147
- catat_cek_bunting bunting -> perkiraan_beranak tetap; tidak_bunting -> status kosong
- catat_beranak -> anak baru dengan dam & sire; sapih: tanggal+60..90; interval beranak dihitung bila ada beranak sebelumnya

Validasi di backend (bukan di LLM):
- ear_tag harus ada; pejantan harus jantan; induk harus betina
- kawin saat status "larangan kawin" -> tolak dengan pesan, agen menyampaikan
- beranak tanpa kawin tercatat -> terima tetapi tandai "pejantan tidak diketahui"
- waktu tidak boleh di masa depan

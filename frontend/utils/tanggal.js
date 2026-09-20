/**
 * Satu-satunya tempat tanggal laporan diformat.
 *
 * Sebelum ini ada dua: `fmt()` di BaseTable (`toLocaleDateString("id-ID")` →
 * "20/9/2026") dan `tglServer()` di ReportPage (`month: "short"` →
 * "20 Sep 2026"). Dua kolom yang justru dipasang BERSEBELAHAN untuk
 * dibandingkan — `tanggal` yang bisa diubah operator di aplikasi POS lama, dan
 * `tanggal_server` yang tidak — tampil dengan dua bentuk berbeda, dan keduanya
 * membuang jam yang sebenarnya sudah dikirim server.
 *
 * ## Kenapa diurai regex, bukan `new Date(v)`
 *
 * Peramban memperlakukan keduanya dengan aturan BERBEDA:
 *
 *     new Date("2026-09-20")        -> tengah malam UTC
 *     new Date("2026-09-20 14:35")  -> waktu lokal
 *
 * Padahal server mengirim keduanya (`apps/core/reporting.py::_clean`: datetime
 * jadi "%Y-%m-%d %H:%M", date jadi "%Y-%m-%d"). Di zona waktu negatif, yang
 * pertama mundur sehari — tanpa galat, tanpa tanda. Dan nilai dari MS SQL
 * legacy adalah jam dinding apa adanya (lihat `_local` di
 * apps/monitoring/views.py), jadi ia memang tak boleh digeser sama sekali.
 *
 * Mengurai sendiri membuat keduanya tunduk pada satu aturan: tampilkan yang
 * tertulis.
 */
const POLA = /^(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2}))?/;

function bagian(v) {
  if (v === null || v === undefined || v === "") return null;
  const m = POLA.exec(String(v));
  return m ? { tgl: `${m[3]}/${m[2]}/${m[1]}`, jam: m[4] ? `${m[4]}.${m[5]}` : "" } : null;
}

/** "2026-09-20 14:35" -> "20/09/2026". Nilai tak dikenal dipulangkan apa adanya. */
export function tanggal(v) {
  const b = bagian(v);
  return b ? b.tgl : v;
}

/** "2026-09-20 14:35" -> "20/09/2026 14.35". Tanpa komponen jam, jadi tanggal saja. */
export function tanggalJam(v) {
  const b = bagian(v);
  if (!b) return v;
  return b.jam ? `${b.tgl} ${b.jam}` : b.tgl;
}

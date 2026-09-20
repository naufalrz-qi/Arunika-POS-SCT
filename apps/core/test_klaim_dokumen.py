"""Nama yang disebut CLAUDE.md harus benar-benar ada di kode.

## Kenapa ini ada

CLAUDE.md adalah berkas pertama yang dibaca setiap sesi baru, jadi kalimat basi di
sana tidak berhenti sebagai kerapian — ia mengarahkan pekerjaan ke tempat yang salah.
Dua kalimat terbukti melakukannya sekaligus, dan keduanya berbentuk "ini masih rusak"
padahal sudah lama diperbaiki:

- `_purchase_prices()` disebut masih membagi pembilang DAN penyebut dengan
  `bs.jumlah`, dan kolom `nominal` di Stok Akhir disebut "still unfixed". Rumusnya
  sudah dibetulkan, dan invariannya malah sudah dijaga `check_stock_agg`.
- Kas Harian dan FMI Stok disebut "not covered at all" untuk izin nilai uang, dengan
  rujukan ke konstanta `BELUM_TERTUTUP` yang sudah tidak ada. Keduanya tertutup lewat
  `_uang_bespoke()`, dan penjaganya `test_uang_e2e.UangBespoke`.

Yang kedua bisa ditangkap mesin tanpa memahami kalimatnya sama sekali: nama
konstantanya sudah tidak ada di kode mana pun. Itulah satu-satunya yang diperiksa di
sini. Test ini TIDAK bisa menangkap klaim pertama — kalimat yang setiap namanya masih
ada tapi isinya salah hanya bisa ditangkap manusia yang membaca kodenya. Jangan
menganggap hijaunya berarti CLAUDE.md benar.

Ambangnya sengaja rendah supaya tak berisik: hanya token dalam backtick yang
berbentuk konstanta (HURUF_BESAR dengan garis bawah). Pola itu tak cocok dengan kata
SQL (`LIKE`, `GROUP BY`), nama tabel legacy (huruf kecil), maupun nama collation
(`SQL_Latin1_General_CP1_CI_AS`, ada huruf kecilnya). Saat ditulis: 20 token
tertangkap, nol pengecualian dibutuhkan.

Hak Cipta (c) 2026 Naufal Rifqi Zuhrian. Lihat LICENSE.
"""
import pathlib
import re

from django.conf import settings
from django.test import SimpleTestCase

# Konstanta Python maupun JS: boleh berawalan garis bawah (`_FIELDS_BY_DATA_KEY`),
# wajib punya minimal satu garis bawah di tengah, dan tanpa huruf kecil sama sekali.
POLA_KONSTANTA = re.compile(r"`(_?[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+)`")

# Kode sumber yang dirujuk CLAUDE.md ada di dua tumpukan; memindai Python saja akan
# menuduh `SEARCH_DEBOUNCE_MS` (konstanta di useColumnarTable.js) sebagai nama basi.
SUFIKS = (".py", ".js", ".vue")
LEWATI = ("__pycache__", "node_modules", "frontend/dist", "frontend\\dist", "venv")


class NamaDiClaudeMdAda(SimpleTestCase):
    def _sumber(self) -> str:
        """Seluruh kode sumber sebagai satu string, KECUALI berkas ini sendiri.

        Pengecualian diri itu bukan kerapian: docstring di atas menyebut
        `BELUM_TERTUTUP` sebagai contoh, dan tanpa dikecualikan test ini akan
        menemukan namanya di dirinya sendiri lalu hijau selamanya.
        """
        sendiri = pathlib.Path(__file__).resolve()
        potong = []
        for p in pathlib.Path(settings.BASE_DIR).rglob("*"):
            if p.suffix not in SUFIKS or p.resolve() == sendiri:
                continue
            if any(l in str(p) for l in LEWATI):
                continue
            potong.append(p.read_text(encoding="utf-8", errors="replace"))
        return "\n".join(potong)

    def test_setiap_konstanta_yang_disebut_masih_ada(self):
        teks = (pathlib.Path(settings.BASE_DIR) / "CLAUDE.md").read_text(encoding="utf-8")
        token = sorted(set(POLA_KONSTANTA.findall(teks)))
        self.assertGreater(len(token), 10, "pemindainya nyaris tak menemukan apa pun")

        sumber = self._sumber()
        hilang = [t for t in token if t not in sumber]
        self.assertEqual(
            hilang, [],
            "CLAUDE.md menyebut nama yang tak ada di kode mana pun. Biasanya ini "
            "berarti kalimat di sekitarnya juga sudah basi -- periksa klaimnya, "
            "jangan cuma menghapus namanya")

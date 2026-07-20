"""Margin harus bisa mengembalikan harga bulat semula.

Aplikasi POS lama memakai margin sebagai acuan dan menurunkan harga darinya:
harga = modal * (1 + margin/100), lalu disimpan ke kolom `money` (4 desimal).
Kalau margin yang kita tulis dibulatkan, perhitungan itu meleset dan harga
tersimpan jadi berpecahan (9200 -> 9200,0019). Tes ini mengunci presisinya.

Angka modal/harga di bawah diambil dari baris nyata yang pernah rusak di
server RTL PUSAT.
"""
from decimal import Decimal, ROUND_HALF_UP

from django.test import SimpleTestCase

from apps.master_data.services import _margin


def _harga_dari_margin(modal: float, margin: float) -> Decimal:
    """Tiru aplikasi lama: hitung harga dari margin, simpan sebagai money(4)."""
    return Decimal(repr(modal * (1 + margin / 100))).quantize(
        Decimal("0.0001"), rounding=ROUND_HALF_UP
    )


class MarginRoundTripTest(SimpleTestCase):
    # (kd_barang, modal, harga bulat yang diinginkan)
    KASUS = [
        ("218A", 5752.0, 9200),
        ("ALATT06", 12750.0, 17213),
        ("ATKSET8016", 7250.0, 10513),
        ("BAK26", 41000.0, 49000),
        ("BAK36", 21500.0, 29000),
    ]

    def test_margin_mengembalikan_harga_bulat(self):
        for kode, modal, harga in self.KASUS:
            with self.subTest(kode=kode):
                hasil = _harga_dari_margin(modal, _margin(harga, modal))
                self.assertEqual(hasil, Decimal(harga), f"{kode}: {hasil} != {harga}")

    def test_margin_yang_dibulatkan_justru_merusak(self):
        # Membuktikan kenapa pembulatan dibuang — bukan sekadar preferensi.
        rusak = 0
        for _, modal, harga in self.KASUS:
            margin_bulat = round(_margin(harga, modal), 4)
            if _harga_dari_margin(modal, margin_bulat) != Decimal(harga):
                rusak += 1
        self.assertEqual(rusak, len(self.KASUS))

    def test_modal_tidak_valid_tetap_nol(self):
        self.assertEqual(_margin(12500, 0), 0.0)
        self.assertEqual(_margin(12500, None), 0.0)

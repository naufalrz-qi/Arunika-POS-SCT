"""Universe barang: satu key cache untuk semua divisi.

Dulu key-nya "universe:<kd_divisi>", jadi tiap divisi yang dibuka pengguna adalah
key dingin sendiri — di server WAN itu puluhan detik lagi per divisi baru. Sekarang
katalog penuh dicache sekali lalu disaring di Python. Tes ini menjaga klaim yang
membuat penyederhanaan itu sah: saring di Python == saring di SQL.
"""
import datetime as dt

from django.test import SimpleTestCase

from apps.inventory import services
from core import cache


class _Profile:
    pk = 4242
    name = "uji"


# (kd_divisi, kd_barang) seperti dikembalikan _barang_universe: sudah lewat _k()
# (strip+upper), dan '' untuk barang tanpa penugasan divisi.
FULL = [
    ("D01", "AAA"),
    ("D01", "BBB"),
    ("D02", "AAA"),
    ("", "CCC"),  # barang tanpa m_barang_divisi
]


def _sql_filter(kd_divisi):
    """Perilaku query berfilter: LEFT JOIN + WHERE bd.kd_divisi = ? efektif jadi
    INNER JOIN, jadi baris tanpa penugasan divisi ikut terbuang."""
    return [r for r in FULL if r[0] == services._k(kd_divisi)]


class UniverseFilterTest(SimpleTestCase):
    def setUp(self):
        cache._master_cache.clear()
        self.calls = []
        self._orig = services._barang_universe
        services._barang_universe = self._fake

    def tearDown(self):
        services._barang_universe = self._orig
        cache._master_cache.clear()

    def _fake(self, cur, kd_divisi=None):
        self.calls.append(kd_divisi)
        if kd_divisi:
            return _sql_filter(kd_divisi)
        return list(FULL)

    def test_saring_python_sama_dengan_saring_sql(self):
        for kd in ("D01", "D02", "d01"):  # collation CI: huruf kecil harus cocok
            with self.subTest(kd=kd):
                self.assertEqual(
                    services._universe_for(_Profile(), None, kd), _sql_filter(kd)
                )

    def test_divisi_kosong_memberi_katalog_penuh(self):
        self.assertEqual(services._universe_for(_Profile(), None, None), FULL)

    def test_satu_query_untuk_banyak_divisi(self):
        p = _Profile()
        for kd in (None, "D01", "D02", "D01"):
            services._universe_for(p, None, kd)
        # Empat pemanggilan, satu pembacaan katalog — itulah yang menghapus
        # ongkos cache dingin per divisi.
        self.assertEqual(self.calls, [None])


class WarmCacheTest(SimpleTestCase):
    """Pemanas harus MENGGANTI entri yang masih hidup (force), bukan melewatinya —
    kalau tidak isinya tak pernah diperbarui dan celah dingin tetap ada."""

    def setUp(self):
        cache._master_cache.clear()

    def tearDown(self):
        cache._master_cache.clear()

    def test_force_menimpa_entri_yang_masih_hidup(self):
        p = _Profile()
        self.assertEqual(cache._cached(p, "k", lambda: "lama"), "lama")
        self.assertEqual(cache._cached(p, "k", lambda: "baru"), "lama")  # cache hit
        cache._cached(p, "k", lambda: "baru", ttl=99, force=True)
        self.assertEqual(cache._cached(p, "k", lambda: "lain"), "baru")

    def test_invalidate_prefix_hanya_buang_yang_cocok(self):
        p = _Profile()
        cache._cached(p, "purchase_prices:2026-07-26", lambda: 1)
        cache._cached(p, "purchase_prices:2026-07-27", lambda: 2)
        cache._cached(p, "meta", lambda: 3)
        cache.invalidate_master_cache(p.pk, prefix=services.PURCHASE_PRICES_PREFIX)
        sisa = sorted(k[1] for k in cache._master_cache if k[0] == p.pk)
        self.assertEqual(sisa, ["meta"])

    def test_key_harga_beli_memuat_tanggal(self):
        # Lewat tengah malam key-nya berbeda, jadi TTL pemanas yang panjang tak
        # bisa menyajikan harga hari kemarin.
        a = services._purchase_prices_key(dt.datetime(2026, 7, 26, 23, 59, 59))
        b = services._purchase_prices_key(dt.datetime(2026, 7, 27, 0, 0, 1))
        self.assertNotEqual(a, b)
        self.assertTrue(a.startswith(services.PURCHASE_PRICES_PREFIX))

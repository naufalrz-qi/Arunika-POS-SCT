"""Nama & keterangan barang hanya boleh diubah dari server gudang.

Yang dijaga di sini PENJAGANYA, bukan SQL-nya: field yang di-disable di Vue tetap
bisa dikirim lewat permintaan buatan sendiri, jadi satu-satunya yang benar-benar
menahan penulisan adalah pemeriksaan di services. Kalau pemeriksaan itu hilang,
tak ada gejala apa pun di layar — sampai satu cabang menamai ulang barang dan
namanya menyebar ke semua cabang lewat Sinkronisasi Master Data.
"""
import os
from unittest import mock

from django.test import TestCase

from apps.connections.models import DbType, ServerProfile
from apps.master_data import services as master


def _profil(nama, tipe):
    return ServerProfile.objects.create(
        name=nama, db_type=tipe, host="localhost", port=1433,
        db_name="db", username="sa",
    )


class PenjagaTipeServer(TestCase):
    def test_non_gudang_ditolak_sebelum_menyentuh_db(self):
        # mssql.cursor di-patch supaya kalau penjaganya lolos, tes ini gagal
        # karena cursor terpanggil — bukan karena koneksi gagal (yang bisa
        # terlihat seperti lulus).
        for tipe in (DbType.RETAIL, DbType.GROSIR):
            with self.subTest(tipe=tipe):
                p = _profil(f"P-{tipe}", tipe)
                with mock.patch.object(master.mssql, "cursor") as m_cursor:
                    with self.assertRaises(master.BukanServerGudang):
                        master.update_nama_keterangan(p, "B1", "Nama Baru", "Ket")
                m_cursor.assert_not_called()

    def test_pesan_penolakan_menyebut_nama_dan_tipe_server(self):
        # Staf toko harus tahu server mana yang sedang aktif dan kenapa ditolak,
        # bukan cuma "tidak diizinkan".
        p = _profil("RTL PUSAT", DbType.RETAIL)
        with self.assertRaises(master.BukanServerGudang) as ctx:
            master.update_nama_keterangan(p, "B1", "X", "")
        pesan = str(ctx.exception)
        self.assertIn("RTL PUSAT", pesan)
        self.assertIn("retail", pesan)
        self.assertIn("gudang", pesan)


def _cursor_palsu(nama_lama, ket_lama, ada=True):
    """Cursor tiruan: satu SELECT lalu satu UPDATE. Merekam SQL yang dijalankan."""
    cur = mock.MagicMock()
    cur.fetchone.return_value = (nama_lama, ket_lama) if ada else None
    ctx = mock.MagicMock()
    ctx.__enter__.return_value = cur
    ctx.__exit__.return_value = False
    return ctx, cur


class TulisIdentitas(TestCase):
    def setUp(self):
        self.g = _profil("GUDANG", DbType.GUDANG)

    def _jalankan(self, nama_lama, ket_lama, nama, ket, ada=True):
        ctx, cur = _cursor_palsu(nama_lama, ket_lama, ada)
        with mock.patch.object(master.mssql, "cursor", return_value=ctx), \
             mock.patch.object(master, "_invalidate_inventory_cache") as m_inval:
            hasil = master.update_nama_keterangan(self.g, "B1", nama, ket)
        return hasil, cur, m_inval

    def test_hanya_yang_berubah_dilaporkan(self):
        hasil, _cur, _ = self._jalankan("Lama", "KetLama", "Baru", "KetLama")
        self.assertEqual(hasil, [{"field": "nama", "lama": "Lama", "baru": "Baru"}])

    def test_keduanya_berubah(self):
        hasil, _cur, _ = self._jalankan("Lama", "K1", "Baru", "K2")
        self.assertEqual([u["field"] for u in hasil], ["nama", "keterangan"])

    def test_tanpa_perubahan_tidak_menulis_dan_tidak_membuang_cache(self):
        # UPDATE yang tak mengubah apa pun tetap membuang cache master seluruh
        # profil — 55rb barang dibaca ulang untuk nol perubahan.
        hasil, cur, m_inval = self._jalankan("Sama", "Ket", "Sama", "Ket")
        self.assertEqual(hasil, [])
        m_inval.assert_not_called()
        self.assertFalse(any("UPDATE" in str(c) for c in cur.execute.call_args_list))

    def test_satu_update_untuk_dua_kolom(self):
        # Dua statement terpisah bisa menyimpan nama baru lalu gagal di
        # keterangan, meninggalkan barang setengah terubah.
        _hasil, cur, _ = self._jalankan("Lama", "K1", "Baru", "K2")
        updates = [c for c in cur.execute.call_args_list if "UPDATE" in str(c[0][0])]
        self.assertEqual(len(updates), 1)
        self.assertIn("nama = ?", updates[0][0][0])
        self.assertIn("keterangan = ?", updates[0][0][0])

    def test_cache_dibuang_setelah_perubahan_nyata(self):
        # Tanpa ini katalog yang dicache tetap memakai nama lama sampai TTL habis.
        _hasil, _cur, m_inval = self._jalankan("Lama", "K", "Baru", "K")
        m_inval.assert_called_once()

    def test_dipangkas_ke_panjang_kolom(self):
        # varchar(50) di m_barang. Dipangkas di sini supaya staf tak menerima galat
        # driver yang tak berarti apa pun bagi mereka.
        panjang = "A" * 80
        hasil, _cur, _ = self._jalankan("Lama", "", panjang, panjang)
        for u in hasil:
            self.assertEqual(len(u["baru"]), master.MAX_NAMA)

    def test_spasi_di_ujung_dipangkas_bukan_dianggap_perubahan(self):
        hasil, _cur, _ = self._jalankan("Nama", "Ket", "  Nama  ", "  Ket  ")
        self.assertEqual(hasil, [])

    def test_nama_kosong_ditolak(self):
        # Barang tanpa nama tak bisa dikenali di nota maupun laporan.
        for kosong in ("", "   "):
            with self.subTest(nilai=repr(kosong)):
                with self.assertRaises(ValueError):
                    master.update_nama_keterangan(self.g, "B1", kosong, "K")

    def test_keterangan_kosong_boleh(self):
        # keterangan NOT NULL di m_barang -> ditulis sebagai string kosong, bukan
        # NULL (yang akan ditolak server).
        hasil, _cur, _ = self._jalankan("Nama", "KetLama", "Nama", "")
        self.assertEqual(hasil, [{"field": "keterangan", "lama": "KetLama", "baru": ""}])

    def test_kode_barang_kosong_ditolak(self):
        with self.assertRaises(ValueError):
            master.update_nama_keterangan(self.g, "  ", "Nama", "K")

    def test_barang_tak_ada_ditolak_dengan_kodenya(self):
        with self.assertRaises(ValueError) as ctx:
            self._jalankan("x", "y", "Nama", "K", ada=False)
        self.assertIn("B1", str(ctx.exception))


class RutePenulisan(TestCase):
    """Rute HTTP-nya sendiri harus menolak, bukan hanya service-nya.

    Ini yang benar-benar terekspos: seseorang bisa mengirim POST ke
    /master/update-harga/identitas tanpa pernah membuka layarnya.
    """

    def setUp(self):
        from apps.auth_app.models import Role, User

        self.user = User.objects.create_user("bos", password="x", role=Role.SUPERADMIN)
        self.client.force_login(self.user)
        self.url = "/admin-panel/master/update-harga/identitas"

    def _post(self, tipe):
        """POST ke rute identitas dengan koneksi aktif bertipe `tipe`.

        POS_AUTO_INDEX dimatikan karena make_default() memicu pembangunan index
        di thread latar yang memakai cursor yang sama — tanpa ini panggilan index
        itu tercampur ke rekaman mock dan menyamarkan apa yang sedang diuji.
        """
        p = _profil(f"P-{tipe}", tipe)
        with mock.patch.dict(os.environ, {"POS_AUTO_INDEX": "0"}):
            p.make_default()
            with mock.patch.object(master.mssql, "cursor") as m_cursor:
                resp = self.client.post(
                    self.url,
                    {"kd_barang": "B1", "nama": "Nama Sisipan", "keterangan": "K"},
                )
        # Yang diperiksa: tak ada UPDATE yang terkirim. Lebih tepat daripada
        # "cursor tak pernah dipanggil" — jalur lain (mis. upkeep index) boleh
        # memakai cursor tanpa membuat tes ini berarti apa-apa.
        sql = " ".join(str(c) for c in m_cursor.mock_calls)
        return resp, sql

    def test_server_retail_tidak_menulis_apa_pun(self):
        resp, sql = self._post(DbType.RETAIL)
        self.assertEqual(resp.status_code, 302)           # dialihkan, bukan 500
        self.assertNotIn("UPDATE m_barang", sql)
        self.assertNotIn("Nama Sisipan", sql)
        self.assertIn("gudang", self.client.session.get("flash_error", ""))

    def test_server_grosir_tidak_menulis_apa_pun(self):
        resp, sql = self._post(DbType.GROSIR)
        self.assertEqual(resp.status_code, 302)
        self.assertNotIn("UPDATE m_barang", sql)
        self.assertNotIn("Nama Sisipan", sql)
        self.assertIn("gudang", self.client.session.get("flash_error", ""))

"""Invarian pemindahan pangkal SQLite -> MS SQL.

Keempat test di sini menjaga hal-hal yang **tidak menghasilkan galat apa pun**
kalau rusak. Jumlah barisnya tetap cocok, `check_constraints()` tetap bersih,
dan aplikasinya jalan seperti biasa — hanya isinya yang diam-diam salah. Itu
jenis kerusakan yang paling mahal: ia baru ketahuan berbulan-bulan kemudian,
saat seseorang bertanya "kapan ini terjadi" dan jawabannya sudah hilang.
"""
import datetime as dt
from types import SimpleNamespace

from django.db import models
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from apps.core.management.commands.pindah_pangkal import (
    LEWAT_ARUNIKA, _bekukan_waktu, keputusan_model, model_disalin,
)
from apps.core.models import ActivityLog, log_activity


class PkAsliBertahan(TestCase):
    """`bulk_create` dengan pk eksplisit harus menyimpan pk ITU.

    mssql-django membungkus insert yang menyertakan kolom auto-pk dengan
    `SET IDENTITY_INSERT ON/OFF` (mssql/compiler.py `fix_auto`). Kalau itu
    berubah, SQL Server menolak pk eksplisit atau menggantinya diam-diam dengan
    nilai identity berikutnya — dan seluruh foreign key di salinan menunjuk
    baris yang salah. Test ini tripwire-nya.
    """

    def test_pk_eksplisit_tidak_diganti(self):
        ActivityLog.objects.bulk_create([
            ActivityLog(pk=900_001, username="a", action="uji", detail="x"),
            ActivityLog(pk=900_002, username="b", action="uji", detail="y"),
        ])
        self.assertEqual(
            sorted(ActivityLog.objects.values_list("pk", flat=True)), [900_001, 900_002])


class WaktuTakDitimpa(TestCase):
    """`auto_now_add` HARUS mati selama penyalinan.

    Tanpa `_bekukan_waktu`, `bulk_create` memanggil `pre_save` dan menimpa
    setiap cap waktu dengan jam migrasi. Test kedua sengaja membuktikan
    perilaku bawaannya juga — penjaga yang tak pernah dibuktikan menjaga apa pun
    adalah penjaga yang bisa dihapus tanpa ada yang merah.
    """

    LAMA = dt.datetime(2024, 3, 17, 8, 30, tzinfo=dt.timezone.utc)

    def test_dibekukan_maka_cap_waktu_asli_bertahan(self):
        with _bekukan_waktu(ActivityLog):
            ActivityLog.objects.bulk_create(
                [ActivityLog(username="a", action="uji", timestamp=self.LAMA)])
        self.assertEqual(ActivityLog.objects.get().timestamp, self.LAMA)

    def test_tanpa_dibekukan_cap_waktu_ditimpa(self):
        ActivityLog.objects.bulk_create(
            [ActivityLog(username="a", action="uji", timestamp=self.LAMA)])
        tersimpan = ActivityLog.objects.get().timestamp
        self.assertNotEqual(tersimpan, self.LAMA)
        self.assertLess(timezone.now() - tersimpan, dt.timedelta(minutes=5))

    def test_flag_dikembalikan_sesudahnya(self):
        kolom = ActivityLog._meta.get_field("timestamp")
        with _bekukan_waktu(ActivityLog):
            self.assertFalse(kolom.auto_now_add)
        self.assertTrue(kolom.auto_now_add)


class UniqueTanpaSyaratTakBolehNullable(SimpleTestCase):
    """Unique constraint tanpa `condition` tak boleh memuat kolom nullable.

    SQLite menganggap dua NULL berbeda; SQL Server menganggapnya SAMA. Tiga
    tabel snapshot pernah melanggar ini dan baru ketahuan saat pemindahan:
    masing-masing sudah punya sepasang baris `profile IS NULL` berkunci sama,
    yang mustahil ada di MS SQL. Aturannya dijaga di sini supaya constraint
    berikutnya tak mengulanginya — kesalahannya tak terlihat sama sekali
    selama datanya masih di SQLite.
    """

    def test_tak_ada_yang_melanggar(self):
        pelanggar = []
        for m in model_disalin():
            kunci = [(list(u), None) for u in m._meta.unique_together]
            kunci += [(list(c.fields), c) for c in m._meta.constraints
                      if isinstance(c, models.UniqueConstraint) and c.fields and not c.condition]
            for kolom, _c in kunci:
                nullable = [k for k in kolom if m._meta.get_field(k).null]
                if nullable:
                    pelanggar.append(f"{m._meta.db_table}({'+'.join(kolom)}): {nullable} nullable")
        self.assertEqual(pelanggar, [], "tambahkan condition=Q(<kolom>__isnull=False)")


class DetailDipotongSaatDitulis(TestCase):
    """`log_activity` memotong ke 255 — di penulisnya, bukan di pemanggil.

    SQLite menerima 505 karakter di kolom CharField(255) tanpa sepatah kata pun;
    MS SQL menolaknya, dan penolakan itu muncul di tengah aksi pengguna yang
    sama sekali tak berhubungan (menyimpan hak menu).
    """

    def test_detail_panjang_tidak_meledak(self):
        log_activity(None, "menu", "x" * 600)
        self.assertEqual(len(ActivityLog.objects.get().detail), 255)


class SkemaArunikaTakIkutPindah(SimpleTestCase):
    """Tabel `apps.bisnis` milik database cabang, bukan pangkal.

    Sejak `apps/core/db_router.py` tabelnya tak lagi dibuat di pangkal baru, jadi
    menyalinnya ke sana akan gagal dengan "Invalid object name" di tengah jalan --
    sesudah tabel lain terlanjur masuk. Yang kosong dilewati; yang berisi
    menghentikan perintahnya, karena tak ada tujuan yang benar untuk isinya di
    database ini.

    Nama tabelnya polos (`merek`, `kategori`, `warna`) -- itu sendiri alasan tambahan
    kenapa tempatnya bukan di pangkal.
    """

    @staticmethod
    def _model(app_label: str):
        return SimpleNamespace(_meta=SimpleNamespace(app_label=app_label, db_table="merek"))

    def test_kosong_dilewati(self):
        tindakan, alasan = keputusan_model(self._model("bisnis"), ada=True, baris=0, kurang=[])
        self.assertEqual(tindakan, "lewati")
        self.assertEqual(alasan, LEWAT_ARUNIKA)

    def test_berisi_ditolak(self):
        tindakan, _ = keputusan_model(self._model("bisnis"), ada=True, baris=3, kurang=[])
        self.assertEqual(tindakan, "tolak_arunika")

    def test_app_pangkal_tetap_disalin(self):
        tindakan, _ = keputusan_model(self._model("core"), ada=True, baris=3, kurang=[])
        self.assertEqual(tindakan, "salin")

    def test_urutan_syarat_tak_berubah(self):
        """Tabel yang tak ada di sumber dilewati lebih dulu, apa pun app-nya --
        termasuk `bisnis`, yang di pemasangan baru memang tak akan punya tabelnya."""
        for app in ("bisnis", "core"):
            with self.subTest(app=app):
                tindakan, alasan = keputusan_model(self._model(app), ada=False, baris=0, kurang=[])
                self.assertEqual(tindakan, "lewati")
                self.assertIn("tak ada di sumber", alasan)

    def test_skema_lebih_tua_tetap_dibedakan(self):
        m = self._model("core")
        self.assertEqual(keputusan_model(m, True, 0, ["profile_id"])[0], "lewati")
        self.assertEqual(keputusan_model(m, True, 5, ["profile_id"])[0], "tolak_skema")

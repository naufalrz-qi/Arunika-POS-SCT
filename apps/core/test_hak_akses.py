"""Hak akses bertingkat — spec docs/superpowers/specs/2026-09-22-hak-akses-bertingkat-design.md."""
import json
from unittest.mock import patch

from django.test import TestCase

from apps.auth_app.models import (
    DATA_KEY_SET,
    Role,
    User,
    bisa_kelola,
    data_tersembunyi_baru,
    peran_terkelola,
)
from apps.connections.models import Lingkungan, ServerProfile
from apps.core.menus import (
    ALL_MENUS,
    assignable_menus,
    boleh_beri,
    default_keys_for,
    menu_baru,
    menus_for,
    wewenang_beri,
)

PW = "rahasia-kuat-123"


def _u(nama, role, **kw):
    return User.objects.create_user(nama, password=PW, role=role, **kw)


class UrutanPeranTests(TestCase):
    """§3.4 — satu urutan untuk Kelola Menu dan Manajemen User."""

    def setUp(self):
        self.boss = _u("boss", Role.SUPERADMIN)
        self.adm = _u("adm", Role.ADMIN)
        self.adm2 = _u("adm2", Role.ADMIN)
        self.spv = _u("spv", Role.SUPERVISOR)
        self.kasir = _u("kasir", Role.KASIR)

    def test_peran_terkelola_setara_atau_di_bawah(self):
        self.assertEqual(peran_terkelola(self.boss),
                         [Role.KASIR, Role.SUPERVISOR, Role.ADMIN, Role.SUPERADMIN])
        self.assertEqual(peran_terkelola(self.adm), [Role.KASIR, Role.SUPERVISOR, Role.ADMIN])
        self.assertEqual(peran_terkelola(self.spv), [Role.KASIR, Role.SUPERVISOR])

    def test_bisa_kelola(self):
        self.assertTrue(bisa_kelola(self.adm, self.adm2))
        self.assertTrue(bisa_kelola(self.adm, self.kasir))
        self.assertFalse(bisa_kelola(self.adm, self.adm), "diri sendiri")
        self.assertFalse(bisa_kelola(self.adm, self.boss))
        self.assertFalse(bisa_kelola(self.spv, self.adm))
        self.assertTrue(bisa_kelola(self.boss, self.boss))

    def test_supervisor_dengan_manajemen_user_tak_bisa_membuat_admin(self):
        """Celah lama: _managed_roles() memberi setiap non-superadmin wewenang atas admin."""
        self.spv.allowed_menu_keys = ["users"]
        self.spv.save(update_fields=["allowed_menu_keys"])
        self.client.force_login(self.spv)
        self.client.post("/admin-panel/users/save",
                         {"username": "naik", "name": "N", "role": "admin", "password": PW})
        self.assertFalse(User.objects.filter(username="naik").exists())

    def test_admin_tak_bisa_menyunting_dirinya_lewat_manajemen_user(self):
        self.adm.allowed_menu_keys = ["users"]
        self.adm.save(update_fields=["allowed_menu_keys"])
        self.client.force_login(self.adm)
        r = self.client.post("/admin-panel/users/save",
                             {"id": self.adm.pk, "username": "adm", "name": "Ganti", "role": "admin"})
        self.assertEqual(r.status_code, 404)


# `jejak_audit` teknis: ia membuka jejak SELURUH akun, sedangkan Log Aktivitas
# sengaja hanya jejak sendiri. `edit_nota` tulis_kritis: menulis ulang nota yang
# uangnya sudah berpindah tangan — supervisor hanya lewat superadmin.
TEKNIS = {"connections", "users", "menus", "tautan_user", "sync_health", "sync_history",
          "sync_harga", "sync_master", "transfer_arunika", "cadangan", "migrasi", "kode_nota",
          "jejak_audit"}
TULIS_KRITIS = {"opname", "koreksi_stok", "nota_mundur", "kas_biaya_input",
                "kas_pendapatan", "kas_penambahan", "kas_mutasi", "edit_nota"}


def _menu(key):
    return next(m for m in ALL_MENUS if m["key"] == key)


def _keys(user):
    return {m["key"] for m in menus_for(user, abaikan_tautan=True)}


class RegistryMenuTests(TestCase):
    def test_flag_teknis(self):
        self.assertEqual({m["key"] for m in ALL_MENUS if m.get("teknis")}, TEKNIS)

    def test_flag_tulis_kritis(self):
        self.assertEqual({m["key"] for m in ALL_MENUS if m.get("tulis_kritis")}, TULIS_KRITIS)

    def test_flag_lama_tak_tersisa(self):
        for m in ALL_MENUS:
            self.assertNotIn("superadmin_only", m, m["key"])
            self.assertNotIn("admin_only", m, m["key"])

    def test_assignable_memuat_teknis_tapi_bukan_always(self):
        keys = {m["key"] for m in assignable_menus()}
        self.assertTrue(TEKNIS <= keys)
        self.assertNotIn("bantuan", keys)

    def test_bawaan_admin_tanpa_teknis_tapi_dengan_tulis_kritis(self):
        bawaan = set(default_keys_for(Role.ADMIN))
        self.assertFalse(bawaan & TEKNIS)
        self.assertTrue(TULIS_KRITIS <= bawaan)


class MenusForTests(TestCase):
    def test_pemberian_superadmin_berlaku_untuk_kasir(self):
        """Dulu `admin_only` dibuang untuk kasir walau dicentang."""
        kasir = _u("k1", Role.KASIR, allowed_menu_keys=["kasir_stok", "opname", "cadangan"])
        self.assertTrue({"kasir_stok", "opname", "cadangan"} <= _keys(kasir))

    def test_superadmin_tetap_semua(self):
        self.assertEqual(_keys(_u("b1", Role.SUPERADMIN)), {m["key"] for m in ALL_MENUS})


class WewenangBeriTests(TestCase):
    def setUp(self):
        self.boss = _u("boss", Role.SUPERADMIN)
        self.editor = _u("editor", Role.ADMIN, allowed_menu_keys=[
            "menus", "dashboard", "products", "koreksi_stok", "connections", "kasir_penjualan"])

    def test_superadmin_memberi_semua_kecuali_always(self):
        semua = {m["key"] for m in assignable_menus()}
        for peran in (Role.KASIR, Role.SUPERVISOR, Role.ADMIN):
            self.assertEqual(wewenang_beri(self.boss, peran), semua)
        self.assertFalse(boleh_beri(self.boss, Role.KASIR, _menu("bantuan")))

    def test_tanpa_kelola_menu_tak_memberi_apa_pun(self):
        adm = _u("adm", Role.ADMIN, allowed_menu_keys=["dashboard", "products"])
        self.assertEqual(wewenang_beri(adm, Role.KASIR), set())

    def test_admin_ke_kasir(self):
        # menus & connections teknis; koreksi_stok tulis_kritis; sisanya dipegang.
        self.assertEqual(wewenang_beri(self.editor, Role.KASIR),
                         {"dashboard", "products", "kasir_penjualan"})

    def test_admin_ke_admin_termasuk_tulis_kritis(self):
        self.assertEqual(wewenang_beri(self.editor, Role.ADMIN),
                         {"dashboard", "products", "kasir_penjualan", "koreksi_stok"})

    def test_admin_ke_supervisor(self):
        # Sama seperti ke kasir: koreksi_stok (tulis_kritis) buang, menus &
        # connections (teknis) buang, sisanya yang dipegang editor.
        self.assertEqual(wewenang_beri(self.editor, Role.SUPERVISOR),
                         {"dashboard", "products", "kasir_penjualan"})

    def test_yang_tak_dipegang_tak_bisa_diberikan(self):
        self.assertFalse(boleh_beri(self.editor, Role.KASIR, _menu("stock")))

    def test_gerbang_tautan_tak_mengurangi_wewenang(self):
        """kasir_penjualan ber-butuh_tautan; editor tak punya TautanUser sama sekali."""
        self.assertTrue(boleh_beri(self.editor, Role.KASIR, _menu("kasir_penjualan")))


class MenuBaruTests(TestCase):
    def setUp(self):
        self.boss = _u("boss", Role.SUPERADMIN)
        self.editor = _u("editor", Role.ADMIN, allowed_menu_keys=["menus", "dashboard", "products"])

    def test_admin_mempertahankan_yang_di_luar_wewenang(self):
        target = _u("t1", Role.ADMIN, allowed_menu_keys=["dashboard", "connections"])
        baru = menu_baru(self.editor, target, ["products", "cadangan"])
        self.assertEqual(set(baru), {"connections", "products"})

    def test_admin_ke_kasir_bawaan_tak_hilang(self):
        kasir = _u("k2", Role.KASIR)  # allowed kosong = bawaan kasir
        self.assertEqual(menu_baru(self.editor, kasir, []), default_keys_for(Role.KASIR))

    def test_superadmin_menulis_apa_adanya(self):
        kasir = _u("k3", Role.KASIR)
        self.assertEqual(menu_baru(self.boss, kasir, ["koreksi_stok", "bantuan", "ngawur"]),
                         ["koreksi_stok"])

    def test_urutan_mengikuti_registry(self):
        target = _u("t2", Role.ADMIN)
        self.assertEqual(menu_baru(self.boss, target, ["users", "dashboard"]),
                         ["dashboard", "users"])

    def test_admin_simpan_kosong_jadi_bantuan(self):
        """Ruling R7: kosong dari NON-superadmin bukan `[]` — `menus_for` membaca
        `[]` sebagai "pakai bawaan peran", jadi editor yang mengosongkan target
        akan diam-diam MEMBERI target menu yang editornya sendiri tak pegang."""
        target = _u("t3", Role.ADMIN, allowed_menu_keys=["dashboard", "products"])
        self.assertEqual(menu_baru(self.editor, target, []), ["bantuan"])
        target.allowed_menu_keys = menu_baru(self.editor, target, [])
        target.save(update_fields=["allowed_menu_keys"])
        self.assertEqual({m["key"] for m in menus_for(target, abaikan_tautan=True)}, {"bantuan"})

    def test_superadmin_simpan_kosong_tetap_kosong(self):
        """Bagi superadmin `[]` memang berarti "kembali ke bawaan peran" — itu
        yang dijanjikan layar Kelola Menu, jadi tetap `[]`, bukan `["bantuan"]`."""
        target = _u("t4", Role.ADMIN, allowed_menu_keys=["dashboard"])
        self.assertEqual(menu_baru(self.boss, target, []), [])


class DataTersembunyiBaruTests(TestCase):
    def test_superadmin_seperti_dulu(self):
        boss = _u("boss", Role.SUPERADMIN)
        staf = _u("s1", Role.ADMIN)
        self.assertEqual(data_tersembunyi_baru(boss, staf, ["harga_jual"]),
                         ["harga_beli", "nominal"])

    def test_admin_tak_bisa_membuka_yang_tersembunyi_darinya(self):
        adm = _u("a1", Role.ADMIN, hidden_data_keys=["harga_beli"])
        staf = _u("s2", Role.KASIR, hidden_data_keys=["harga_beli"])
        self.assertEqual(data_tersembunyi_baru(adm, staf, sorted(DATA_KEY_SET)), ["harga_beli"])

    def test_admin_tak_bisa_menutup_yang_tersembunyi_darinya(self):
        adm = _u("a2", Role.ADMIN, hidden_data_keys=["harga_beli"])
        staf = _u("s3", Role.KASIR)
        self.assertEqual(data_tersembunyi_baru(adm, staf, []), ["harga_jual", "nominal"])


class KelolaMenuHttpTests(TestCase):
    def setUp(self):
        self.boss = _u("boss", Role.SUPERADMIN)
        self.editor = _u("editor", Role.ADMIN,
                         allowed_menu_keys=["menus", "dashboard", "products", "koreksi_stok"])
        self.admin2 = _u("admin2", Role.ADMIN, allowed_menu_keys=["dashboard", "connections"])
        self.kasir = _u("kasir", Role.KASIR)

    def _simpan(self, target, menu_keys, data_keys=None):
        return self.client.post(
            "/admin-panel/menus/save",
            {"user_id": target.pk, "menu_keys": menu_keys,
             "data_keys": sorted(DATA_KEY_SET) if data_keys is None else data_keys},
            content_type="application/json")

    def test_admin_dengan_kelola_menu_bisa_membuka(self):
        self.client.force_login(self.editor)
        self.assertEqual(self.client.get("/admin-panel/menus").status_code, 200)

    def test_layar_mengirim_wewenang_per_peran(self):
        self.client.force_login(self.editor)
        r = self.client.get("/admin-panel/menus", HTTP_X_INERTIA="true",
                            HTTP_X_INERTIA_VERSION="1.0")
        props = json.loads(r.content)["props"]
        self.assertEqual(set(props["boleh_beri"]["kasir"]), {"dashboard", "products"})
        self.assertIn("koreksi_stok", props["boleh_beri"]["admin"])
        self.assertFalse(props["saya_superadmin"])
        self.assertNotIn(self.editor.pk, [u["id"] for u in props["users"]])

    def test_simpan_admin_mempertahankan_menu_teknis_target(self):
        self.client.force_login(self.editor)
        self._simpan(self.admin2, ["products", "cadangan"])
        self.admin2.refresh_from_db()
        self.assertEqual(set(self.admin2.allowed_menu_keys), {"connections", "products"})

    def test_tulis_kritis_ke_kasir_diabaikan_ke_admin_diterima(self):
        self.client.force_login(self.editor)
        self._simpan(self.kasir, ["koreksi_stok"])
        self.kasir.refresh_from_db()
        self.assertNotIn("koreksi_stok", self.kasir.allowed_menu_keys)
        self._simpan(self.admin2, ["koreksi_stok"])
        self.admin2.refresh_from_db()
        self.assertIn("koreksi_stok", self.admin2.allowed_menu_keys)

    def test_tak_bisa_menyunting_diri_sendiri(self):
        self.client.force_login(self.editor)
        self.assertEqual(self._simpan(self.editor, ["dashboard"]).status_code, 403)

    def test_superadmin_memberi_menu_teknis_membuka_halamannya(self):
        """Dulu _deny_non_superadmin menolak di dalam view walau menunya diberikan."""
        self.client.force_login(self.boss)
        self._simpan(self.admin2, ["dashboard", "cadangan"])
        self.client.force_login(self.admin2)
        self.assertEqual(self.client.get("/admin-panel/pengaturan/cadangan").status_code, 200)

    def test_tanpa_pemberian_halaman_teknis_tetap_tertutup(self):
        self.client.force_login(self.admin2)
        self.assertNotEqual(self.client.get("/admin-panel/pengaturan/cadangan").status_code, 200)

    def test_simpan_kosong_admin_jadi_bantuan(self):
        """Ruling R7, lewat HTTP: editor tanpa keluarga keys di luar wewenangnya
        di target — jadi simpanan kosongnya betul-betul kosong sebelum dijaga."""
        editor = _u("editor3", Role.ADMIN, allowed_menu_keys=["menus", "dashboard", "products"])
        target = _u("t5", Role.ADMIN, allowed_menu_keys=["dashboard", "products"])
        self.client.force_login(editor)
        self._simpan(target, [])
        target.refresh_from_db()
        self.assertEqual(target.allowed_menu_keys, ["bantuan"])
        self.assertEqual({m["key"] for m in menus_for(target, abaikan_tautan=True)}, {"bantuan"})

    def test_simpan_kosong_superadmin_tetap_kosong(self):
        target = _u("t6", Role.ADMIN, allowed_menu_keys=["dashboard"])
        self.client.force_login(self.boss)
        self._simpan(target, [])
        target.refresh_from_db()
        self.assertEqual(target.allowed_menu_keys, [])

    def test_penanda_migrasi_ikut_menu(self):
        from apps.core.middleware import _migrasi_tertunda

        with patch("apps.core.migrasi.tertunda", return_value=["a", "b"]):
            self.assertEqual(_migrasi_tertunda(self.admin2), 0)
            self.admin2.allowed_menu_keys = ["dashboard", "migrasi"]
            self.admin2.save(update_fields=["allowed_menu_keys"])
            self.assertEqual(_migrasi_tertunda(self.admin2), 2)


class PerubahanPeranTests(TestCase):
    """Ruling R8 — ganti peran lewat Manajemen User mengosongkan pemberian
    menu & koneksi khusus, karena keduanya penilaian PER PERAN."""

    def setUp(self):
        self.boss = _u("boss_pp", Role.SUPERADMIN)
        self.profil = ServerProfile.objects.create(
            name="UJI-PP", host="h", db_name="d", username="u",
            lingkungan=Lingkungan.UJI)
        self.target = _u("naik_turun", Role.ADMIN,
                         allowed_menu_keys=["dashboard", "koreksi_stok", "connections"])
        self.target.koneksi_khusus.add(self.profil)

    def _simpan(self, role):
        self.client.force_login(self.boss)
        return self.client.post("/admin-panel/users/save", {
            "id": self.target.pk, "username": self.target.username,
            "name": "Nama Sama", "role": role})

    def test_ganti_peran_mengosongkan_menu_dan_koneksi_khusus(self):
        self._simpan(Role.KASIR)
        self.target.refresh_from_db()
        self.assertEqual(self.target.allowed_menu_keys, [])
        self.assertFalse(self.target.koneksi_khusus.exists())
        self.assertNotIn(
            "koreksi_stok",
            {m["key"] for m in menus_for(self.target, abaikan_tautan=True)})

    def test_tanpa_ganti_peran_menu_dan_koneksi_khusus_tetap(self):
        self._simpan(Role.ADMIN)
        self.target.refresh_from_db()
        self.assertEqual(set(self.target.allowed_menu_keys),
                         {"dashboard", "koreksi_stok", "connections"})
        self.assertTrue(self.target.koneksi_khusus.filter(pk=self.profil.pk).exists())

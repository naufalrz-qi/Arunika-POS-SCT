"""Hak akses bertingkat — spec docs/superpowers/specs/2026-09-22-hak-akses-bertingkat-design.md."""
from django.test import TestCase

from apps.auth_app.models import (
    DATA_KEY_SET,
    Role,
    User,
    bisa_kelola,
    data_tersembunyi_baru,
    peran_terkelola,
)
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


TEKNIS = {"connections", "users", "menus", "tautan_user", "sync_health", "sync_history",
          "sync_harga", "sync_master", "transfer_arunika", "cadangan", "migrasi", "kode_nota"}
TULIS_KRITIS = {"opname", "koreksi_stok", "nota_mundur", "kas_biaya_input",
                "kas_pendapatan", "kas_penambahan", "kas_mutasi"}


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

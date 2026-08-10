"""Rute Kelola Data Referensi: satu key menu menjaga sebelas entitas.

Yang dijaga di sini bukan tampilannya, melainkan tiga hal yang gampang bocor
saat satu menu melayani banyak sub-rute:

1. **Prefix menutup seluruh anaknya.** `menu_key_for_path` mencocokkan awalan
   href, jadi `/referensi/merk` dan `/referensi/merk/save` harus jatuh ke key
   `kelola_referensi` — kalau tidak, mencabut menunya tak menutup apa pun dan
   URL-nya tetap bisa diketik langsung.

2. **Entitas asing ditolak 404, bukan 500.** Entitasnya bagian dari URL; salah
   ketik itu wajar dan bukan kerusakan.

3. **Pelanggan & Supplier tak ikut lewat rute ini.** Keduanya punya key menu
   sendiri, dan menyajikannya di sini berarti memberi jalan pintas mengelilingi
   hak akses keduanya.
"""
from django.test import TestCase

from apps.auth_app.models import Role, User
from apps.connections.models import ServerProfile
from apps.core.menus import ALL_MENUS, assignable_menus, menu_key_for_path, menus_for
from apps.master_data import master_crud
from core import mssql

HREF = "/admin-panel/master/referensi"


class PetaMenuTests(TestCase):
    def test_menu_terdaftar_dan_bisa_diberikan(self):
        keys = {m["key"] for m in assignable_menus()}
        self.assertIn("kelola_referensi", keys)

    def test_seluruh_sub_rute_dimiliki_satu_key(self):
        for entitas in master_crud.REFERENSI:
            for path in (f"{HREF}/{entitas}", f"{HREF}/{entitas}/save"):
                self.assertEqual(menu_key_for_path(path), "kelola_referensi", path)

    def test_href_telanjang_juga_dimiliki_key_yang_sama(self):
        self.assertEqual(menu_key_for_path(HREF), "kelola_referensi")

    def test_href_menu_tak_membawa_entitas(self):
        """Kalau href-nya `/referensi/kategori`, sub-rute lain lolos dari penjaga."""
        menu = next(m for m in ALL_MENUS if m["key"] == "kelola_referensi")
        self.assertEqual(menu["href"], HREF)

    def test_pelanggan_dan_supplier_di_luar_daftar_referensi(self):
        self.assertNotIn("pelanggan", master_crud.REFERENSI)
        self.assertNotIn("supplier", master_crud.REFERENSI)


class RuteTests(TestCase):
    def setUp(self):
        self.profil = ServerProfile.objects.create(
            name="TOKO R", host="host-r", db_name="SOLID_SIM",
            username="sa", password_encrypted="x", is_default=True)
        self.boss = User.objects.create_user(
            "boss_r", password="rahasia-kuat-123", role=Role.SUPERADMIN)
        self.admin = User.objects.create_user(
            "admin_r", password="rahasia-kuat-123", role=Role.ADMIN,
            server_profile=self.profil)
        mssql.set_request_profile_id(self.profil.id)
        self.addCleanup(mssql.clear_request_profile)

    def test_href_telanjang_mengantar_ke_entitas_pertama(self):
        self.client.force_login(self.boss)
        r = self.client.get(HREF)
        self.assertEqual(r.status_code, 302)
        self.assertEqual(r["Location"], f"{HREF}/{master_crud.REFERENSI[0]}")

    def test_entitas_asing_404(self):
        self.client.force_login(self.boss)
        self.assertEqual(self.client.get(f"{HREF}/kambing").status_code, 404)

    def test_pelanggan_tak_bisa_lewat_rute_referensi(self):
        """Rute ini tidak boleh jadi pintu belakang ke Kelola Pelanggan."""
        self.client.force_login(self.boss)
        self.assertEqual(self.client.get(f"{HREF}/pelanggan").status_code, 404)

    def test_save_menolak_GET(self):
        self.client.force_login(self.boss)
        self.assertEqual(self.client.get(f"{HREF}/merk/save").status_code, 405)

    def test_menu_dicabut_menutup_sub_rute_yang_diketik_langsung(self):
        self.admin.allowed_menu_keys = ["dashboard"]
        self.admin.save()
        self.client.force_login(self.admin)
        for path in (HREF, f"{HREF}/merk"):
            r = self.client.get(path)
            self.assertIn(r.status_code, (302, 403), path)
            self.assertNotEqual(r.status_code, 200, path)

    def test_menu_diberikan_membuka_sub_rutenya(self):
        self.admin.allowed_menu_keys = ["dashboard", "kelola_referensi"]
        self.admin.save()
        self.assertIn("kelola_referensi", {m["key"] for m in menus_for(self.admin)})
        self.client.force_login(self.admin)
        # Halamannya sendiri butuh MS SQL (prop deferred), jadi yang diuji di
        # sini cuma bahwa penjaga menu melepasnya — bukan isi datanya.
        self.assertEqual(self.client.get(HREF).status_code, 302)

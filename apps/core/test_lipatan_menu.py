"""Lipatan sidebar di frontend/composables/useNav.js tetap sejalan dengan menus.py.

Lipatan hanya tampilan, jadi kesalahannya tak pernah melempar error: kunci yang
di-rename di ALL_MENUS membuat anggotanya diam-diam keluar dari lipatan, dan
anggota yang pindah section membuat satu entri terbelah dua di sidebar (lipat()
bekerja per subsection). Dua-duanya hanya kelihatan kalau ada yang membuka
sidebar dengan akun yang punya kedua menunya. Di sini keduanya jadi merah.
"""
import re
from pathlib import Path

from django.conf import settings
from django.test import TestCase

from apps.auth_app.models import Role, User
from apps.core.menus import ALL_MENUS, SECTIONS, menu_key_for_path

USE_NAV = Path(settings.BASE_DIR) / "frontend" / "composables" / "useNav.js"


def _lipatan():
    """[{key, hub, section, href, anggota: [kunci menu]}] dari blok LIPATAN."""
    teks = USE_NAV.read_text(encoding="utf-8")
    blok = teks[teks.index("const LIPATAN = [") : teks.index("\n];", teks.index("const LIPATAN = ["))]
    hasil = []
    # Setiap lipatan dibuka `key: "…"` di tingkat objeknya; anggota ada di
    # `anggota: { … }` sesudahnya, sebelum lipatan berikutnya dimulai.
    awal = [m for m in re.finditer(r'^\s*(?:\{\s*)?key: "([a-z_]+)"', blok, re.M)]
    for i, m in enumerate(awal):
        potong = blok[m.start() : awal[i + 1].start() if i + 1 < len(awal) else len(blok)]
        isi = re.search(r"anggota:\s*\{(.*?)\}", potong, re.S).group(1)
        hasil.append({
            "key": m.group(1),
            "hub": "hub: true" in potong,
            "section": (re.search(r'section: "([a-z_]+)"', potong) or [None, None])[1],
            "href": (re.search(r'href: "([^"]+)"', potong) or [None, None])[1],
            "anggota": re.findall(r"(\w+):\s*\"", isi),
        })
    return hasil


class LipatanMenuTests(TestCase):
    def setUp(self):
        self.lipatan = _lipatan()
        self.menu = {m["key"]: m for m in ALL_MENUS}

    def test_blok_terbaca(self):
        """Pengurai yang tak menemukan apa-apa membuat semua test di bawah lolos."""
        self.assertGreaterEqual(len(self.lipatan), 9)
        # 35 = 34 + `migrasi` (Pembaruan Database) di lipatan Pengaturan.
        self.assertEqual(sum(len(l["anggota"]) for l in self.lipatan), 35)

    def test_setiap_anggota_adalah_menu_yang_ada(self):
        for l in self.lipatan:
            for k in l["anggota"]:
                self.assertIn(k, self.menu, f"lipatan {l['key']}: menu {k} tak ada di ALL_MENUS")

    def test_satu_menu_satu_lipatan(self):
        dilihat = {}
        for l in self.lipatan:
            for k in l["anggota"]:
                self.assertNotIn(k, dilihat, f"{k} ada di {dilihat.get(k)} dan {l['key']}")
                dilihat[k] = l["key"]

    def test_anggota_non_hub_satu_section(self):
        for l in self.lipatan:
            if l["hub"]:
                continue
            section = {self.menu[k]["section"] for k in l["anggota"]}
            self.assertEqual(len(section), 1, f"lipatan {l['key']} terbelah: {section}")

    def test_hub_punya_section_dan_rute_di_luar_registry_menu(self):
        """Path hub tak boleh jatuh ke menu mana pun: kalau jatuh, penjaga menolak
        akun yang tak diberi menu itu, walau ia punya menu pengaturan lain."""
        for l in (x for x in self.lipatan if x["hub"]):
            self.assertIn(l["section"], SECTIONS)
            self.assertIsNone(menu_key_for_path(l["href"]), l["href"])

    def test_halaman_pengaturan_terbuka_untuk_admin(self):
        admin = User.objects.create_user("admin_lipat", password="rahasia-kuat-123", role=Role.ADMIN)
        self.client.force_login(admin)
        r = self.client.get("/admin-panel/pengaturan")
        self.assertEqual(r.status_code, 200)

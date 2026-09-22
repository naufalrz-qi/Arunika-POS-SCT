# Hak Akses Bertingkat: Rencana Implementasi

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Aturan akses menjawab "siapa boleh **memberi**", bukan lagi "siapa boleh **punya**".
Hasilnya:
- superadmin bisa memberi menu apa pun ke siapa pun;
- admin yang punya Kelola Menu bisa memberi, tapi terbatas;
- koneksi non-produksi (uji coba, internal/AMPHOREUS) tertutup kecuali diberikan per user.

**Architecture:**
- **Menu.** Flag menu diganti (`superadmin_only` → `teknis`, `admin_only` → `tulis_kritis`).
  `menus_for()` jadi murni berdasarkan hak yang diberikan. Aturan pemberian ada di satu
  fungsi, `wewenang_beri()` di `apps/core/menus.py`.
- **Urutan peran.** Satu fungsi di `apps/auth_app/models.py` (`bisa_kelola`/`peran_terkelola`),
  dipakai Manajemen User dan Kelola Menu.
- **Koneksi.** Aturan akses di `apps/connections/akses.py`. Ditegakkan di middleware
  `inertia_share`, `connections_set_default`, dan `users_save`.

**Tech Stack:** Django 5 + mssql-django (pangkal MS SQL, termasuk untuk test), Inertia-Django,
Vue 3 (JS biasa), Vite.

**Spec:** `docs/superpowers/specs/2026-09-22-hak-akses-bertingkat-design.md`

## Global Constraints

- **Repo & branch:** `D:\backup D\Project\Arunika-SCT-POS`, branch `feat/hak-akses-bertingkat`.
- **Git:** setiap perintah wajib memakai
  `git -c safe.directory=* -c user.name=naufalrz-qi -c user.email=estarossa.nrz@gmail.com`.
  Pesan commit diakhiri baris `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`.
- **Berkas repo ber-CRLF.** Sunting dengan tool Edit, **jangan `sed -i`**, karena ia menanggalkan
  CR di seluruh berkas.
- **Bahasa:** teks UI dan komentar kode dalam Bahasa Indonesia, mengikuti berkas sekitarnya.
- **Test:** jalan di MS SQL (`test_<POS_APP_DB_NAME>` di instans lokal). Perintahnya, dari
  root repo di Bash:
  `venv/Scripts/python.exe manage.py test <label> --noinput`.
  Patokan sebelum perubahan: **968 test, OK** (commit `4ff423f`).
- **Dependensi:** tidak ada yang baru, baik Python maupun npm.
- **Nama fungsi** harus persis seperti di blok *Interfaces* tiap task. Task lain memanggilnya.

---

### Task 1: Urutan peran untuk Manajemen User

Menutup celah yang sudah ada: `_managed_roles()` memberi setiap non-superadmin wewenang atas
admin, sehingga supervisor yang diberi Manajemen User bisa membuat akun admin.

**Files:**
- Modify: `apps/auth_app/models.py` (tambah fungsi sesudah `class Role`)
- Modify: `apps/monitoring/views.py` (`_managed_roles`, `users_index`, `users_save`,
  `users_reset_password`, `users_toggle`, `users_delete`, import)
- Create: `apps/core/test_hak_akses.py`

**Interfaces:**
- Produces:
  - `apps.auth_app.models.URUTAN_PERAN: list[str]`
  - `peringkat(role: str) -> int`
  - `peran_terkelola(pengelola) -> list[str]`
  - `bisa_kelola(pengelola, target) -> bool`
  - `apps.monitoring.views._qs_terkelola(user) -> QuerySet[User]`

- [ ] **Step 1: Tulis test yang gagal.** Buat `apps/core/test_hak_akses.py`:

```python
"""Hak akses bertingkat — spec docs/superpowers/specs/2026-09-22-hak-akses-bertingkat-design.md."""
from django.test import TestCase

from apps.auth_app.models import Role, User, bisa_kelola, peran_terkelola

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
```

- [ ] **Step 2: Pastikan gagal.**
  Jalankan `venv/Scripts/python.exe manage.py test apps.core.test_hak_akses --noinput`.
  Yang diharapkan: `ImportError: cannot import name 'bisa_kelola'`.

- [ ] **Step 3: Implementasi di `apps/auth_app/models.py`.** Sisipkan tepat sesudah
  `class Role(...)` (sebelum `DATA_KEYS`):

```python
# Urutan wewenang, dari yang paling sempit. Satu-satunya sumber untuk "siapa
# boleh mengelola siapa" — dipakai Manajemen User DAN Kelola Menu. Dulu
# Manajemen User punya aturannya sendiri (`_managed_roles`) yang memberi SETIAP
# non-superadmin wewenang atas admin: supervisor yang diberi menu itu bisa
# membuat akun admin.
URUTAN_PERAN = [Role.KASIR, Role.SUPERVISOR, Role.ADMIN, Role.SUPERADMIN]


def peringkat(role: str) -> int:
    return URUTAN_PERAN.index(role) if role in URUTAN_PERAN else -1


def peran_terkelola(pengelola) -> list[str]:
    """Peran yang boleh DIJANGKAU dan DIBERIKAN `pengelola`: setara atau di bawahnya."""
    batas = peringkat(pengelola.role)
    return [r for r in URUTAN_PERAN if peringkat(r) <= batas]


def bisa_kelola(pengelola, target) -> bool:
    """Superadmin mengelola siapa pun. Selain itu: peran setara atau di bawahnya,
    dan BUKAN dirinya sendiri — menyunting akun sendiri lewat layar pengelolaan
    adalah jalan pintas menaikkan hak."""
    if pengelola.role == Role.SUPERADMIN:
        return True
    return target.pk != pengelola.pk and peringkat(target.role) <= peringkat(pengelola.role)
```

- [ ] **Step 4: Implementasi di `apps/monitoring/views.py`.**
  1. Ubah baris import `from apps.auth_app.models import DATA_KEY_SET, DATA_KEYS, Role, TautanUser, User`
     menjadi
     `from apps.auth_app.models import DATA_KEY_SET, DATA_KEYS, Role, TautanUser, User, bisa_kelola, peran_terkelola`.
  2. Ganti seluruh fungsi `_managed_roles` beserta blok komentar di atasnya (mulai
     `# PRD §4 — operational-account management.`) dengan:

```python
# PRD §4 — siapa mengelola siapa. Aturannya satu, di
# apps/auth_app/models.peran_terkelola/bisa_kelola, dipakai juga Kelola Menu.
# Set ini tetap gerbang ganda: role target yang boleh dijangkau DAN nilai role
# yang boleh diberikan, sehingga eskalasi via save/delete/reset terblokir.
def _managed_roles(user):
    return peran_terkelola(user)


def _qs_terkelola(user):
    """Akun yang boleh dijangkau `user` di Manajemen User. Bukan dirinya
    sendiri, kecuali superadmin (yang dijaga `_last_superadmin_guard`)."""
    qs = User.objects.filter(role__in=peran_terkelola(user))
    if user.role != Role.SUPERADMIN:
        qs = qs.exclude(pk=user.pk)
    return qs
```

  3. `users_index`: ganti
     `users = User.objects.filter(role__in=roles).order_by("role", "username")` dengan
     `users = _qs_terkelola(request.user).order_by("role", "username")`.
  4. `users_save`: ganti `user = get_object_or_404(User, pk=user_id, role__in=managed)` dengan
     `user = get_object_or_404(_qs_terkelola(request.user), pk=user_id)`.
  5. `users_reset_password`, `users_toggle`, `users_delete`: ganti
     `get_object_or_404(User, pk=user_id, role__in=_managed_roles(request.user))` dengan
     `get_object_or_404(_qs_terkelola(request.user), pk=user_id)`.

- [ ] **Step 5: Pastikan lulus.**
  Jalankan `venv/Scripts/python.exe manage.py test apps.core.test_hak_akses apps.monitoring.tests --noinput`.
  Yang diharapkan: semua OK.

- [ ] **Step 6: Commit.**

```bash
git -c safe.directory=* -c user.name=naufalrz-qi -c user.email=estarossa.nrz@gmail.com add apps/auth_app/models.py apps/monitoring/views.py apps/core/test_hak_akses.py
git -c safe.directory=* -c user.name=naufalrz-qi -c user.email=estarossa.nrz@gmail.com commit -m "fix: urutan peran untuk Manajemen User — supervisor tak bisa lagi membuat admin" -m "Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 2: Aturan menu — flag baru, `menus_for` murni pemberian, `wewenang_beri`

**Files:**
- Modify: `apps/core/menus.py`: flag di `ALL_MENUS`, `assignable_menus`, `default_keys_for`,
  `menus_for`, dan fungsi baru.
- Modify: `apps/auth_app/models.py`: `data_tersembunyi_baru`.
- Modify tests: `apps/core/test_hak_akses.py` (tambah),
  `apps/monitoring/test_akses_kasir.py`, `apps/monitoring/test_sync_health.py`,
  `apps/core/test_migrasi.py`, `apps/monitoring/tests.py`.

**Interfaces:**
- Consumes: `bisa_kelola`, `peran_terkelola` (Task 1).
- Produces, di `apps.core.menus`:
  - `wewenang_beri(pemberi, peran_target: str) -> set[str]`
  - `boleh_beri(pemberi, peran_target: str, menu: dict) -> bool`
  - `menu_baru(pemberi, target, dicentang) -> list[str]`
  - flag menu `"teknis"` dan `"tulis_kritis"`
- Produces, di `apps.auth_app.models`:
  - `data_tersembunyi_baru(pemberi, target, boleh) -> list[str]`

- [ ] **Step 1: Tambah test yang gagal di `apps/core/test_hak_akses.py`.**
  1. Ganti baris import `from apps.auth_app.models import ...` dengan:

```python
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
```

  2. Tambahkan di akhir berkas:

```python
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
```

- [ ] **Step 2: Pastikan gagal.**
  Jalankan `venv/Scripts/python.exe manage.py test apps.core.test_hak_akses --noinput`.
  Yang diharapkan: `ImportError: cannot import name 'data_tersembunyi_baru'`.

- [ ] **Step 3: Ganti flag di `ALL_MENUS` (`apps/core/menus.py`).** Pakai skrip Python
  (bukan sed). Skrip ini menjaga CRLF dan gagal keras kalau jumlah penggantian meleset:

```bash
venv/Scripts/python.exe - <<'EOF'
import re
from pathlib import Path
p = Path("apps/core/menus.py")
t = p.read_bytes().decode("utf-8")
assert t.count('"superadmin_only": True') == 7, t.count('"superadmin_only": True')
assert t.count('"admin_only": True') == 7, t.count('"admin_only": True')
t = t.replace('"superadmin_only": True', '"teknis": True').replace('"admin_only": True', '"tulis_kritis": True')
for key in ("sync_harga", "sync_master", "sync_history", "users", "connections"):
    t, n = re.subn(r'(\{"key": "%s",[^\r\n]*?)\}' % key, r'\1, "teknis": True}', t, count=1)
    assert n == 1, key
p.write_bytes(t.encode("utf-8"))
print("ok")
EOF
```

  Yang diharapkan: `ok`.

- [ ] **Step 4: Perbarui komentar flag di `ALL_MENUS` dengan tool Edit.**
  1. Blok komentar yang diawali `# "admin_only": ketiga layar opname khusus admin/superadmin, dan itu bukan`
     (sampai `# selisih yang jadi dasar koreksi itu.`) diganti dengan:

```python
    # "tulis_kritis": bawaan admin, dan ke kasir/supervisor HANYA lewat
    # superadmin (spec 2026-09-22 K5). Koreksi Stok MENULIS: satu baris di
    # t_opname_stok langsung menggeser stok lewat trigger dan terkirim ke
    # pusat, dan tak ada layar mana pun yang bisa menariknya kembali. Kedua
    # layar laporannya ikut karena mereka memperlihatkan selisih yang jadi
    # dasar koreksi itu. Yang dijaga adalah siapa yang boleh MEMBERI — lihat
    # wewenang_beri().
```

  2. Di atas `{"key": "nota_mundur", ...`, baris `# admin_only. Bukan superadmin_only: ini pekerjaan yang mengelola toko,`
     diganti dengan `# tulis_kritis. Bukan teknis: ini pekerjaan yang mengelola toko,`.
  3. Setiap baris komentar yang diawali `# Superadmin-only:` diganti awalannya menjadi
     `# Teknis (hanya superadmin yang memberi):`. Ini berlaku untuk komentar di atas
     `sync_health`, `kode_nota`, `cadangan`, dan `menus`. Khusus komentar di atas `menus`,
     sisa kalimatnya `cannot be granted to a regular admin.` dihapus.
  4. Komentar di atas `migrasi` dan `tautan_user` yang memuat `Superadmin saja`: ganti
     frasa itu menjadi `Teknis`.
  5. Tambahkan blok ini tepat di atas `ALL_MENUS = [`:

```python
# Flag yang menentukan siapa boleh MEMBERI (bukan siapa boleh punya — spec
# docs/superpowers/specs/2026-09-22-hak-akses-bertingkat-design.md):
#   "teknis"       — hanya superadmin yang memberikannya, dan bukan bawaan
#                    peran mana pun. Layar yang menyentuh database, server,
#                    atau hak akses orang lain.
#   "tulis_kritis" — bawaan admin; ke kasir/supervisor hanya lewat superadmin.
#   "always"       — tak bisa dicabut dan tak tampil di Kelola Menu.
#   "butuh_tautan" — tertutup selama akun belum tertaut di koneksi aktif.
# Aturan pemberiannya satu, di wewenang_beri().
```

- [ ] **Step 5: Ganti fungsi di `apps/core/menus.py`.**
  1. Ganti seluruh `assignable_menus()` dengan:

```python
def assignable_menus():
    """Menu yang tampil di Kelola Menu: semuanya kecuali `always` (Bantuan) —
    menampilkan yang tak bisa dicabut cuma menyesatkan.

    Menu `teknis` ikut di sini. SIAPA yang boleh memberikannya diputuskan
    wewenang_beri(), bukan daftar ini."""
    return [m for m in ALL_MENUS if not m.get("always")]
```

  2. Di `default_keys_for()`, ganti baris
     `return [m["key"] for m in assignable_menus() if m["section"] not in SECTIONS_POS]` dengan:

```python
        # `teknis` bukan bawaan peran mana pun (spec K2): superadmin yang
        # memberikannya, satu per satu, kepada yang memang memerlukannya.
        return [m["key"] for m in assignable_menus()
                if m["section"] not in SECTIONS_POS and not m.get("teknis")]
```

  3. Di `menus_for()`, ganti isi cabang `else:` (dari
     `# Satu jalur untuk admin, kasir, dan supervisor.` sampai penutup list `dasar = [...]`) dengan:

```python
    else:
        # Murni pemberian: yang dicentang superadmin BERLAKU, apa pun peran
        # akunnya. Dulu `admin_only` membuang menu tulis untuk kasir/supervisor
        # walau dicentang — layar menjanjikan akses yang takkan terjadi.
        # Batasnya kini ada di siapa yang boleh MEMBERI (wewenang_beri).
        allowed = set(user.allowed_menu_keys or default_keys_for(user.role))
        dasar = [m for m in ALL_MENUS if m.get("always") or m["key"] in allowed]
```

  4. Tambahkan di akhir berkas:

```python
def wewenang_beri(pemberi, peran_target: str) -> set[str]:
    """Kunci menu yang boleh DIUBAH `pemberi` untuk akun berperan `peran_target`.

    Satu-satunya tempat aturan pemberian (spec 2026-09-22 §3.3). Layar Kelola
    Menu, `menu_baru()`, dan test membaca fungsi ini — jangan menyalinnya.
    """
    from apps.auth_app.models import Role

    bisa = assignable_menus()
    if pemberi.role == Role.SUPERADMIN:
        return {m["key"] for m in bisa}
    # Gerbang tautan diabaikan: ia bergantung pada koneksi yang sedang aktif,
    # sedangkan wewenang memberi tidak.
    dipegang = {m["key"] for m in menus_for(pemberi, abaikan_tautan=True)}
    if "menus" not in dipegang:
        return set()
    return {
        m["key"] for m in bisa
        if not m.get("teknis")
        and (not m.get("tulis_kritis") or peran_target == Role.ADMIN)
        and m["key"] in dipegang
    }


def boleh_beri(pemberi, peran_target: str, menu: dict) -> bool:
    return menu["key"] in wewenang_beri(pemberi, peran_target)


def menu_baru(pemberi, target, dicentang) -> list[str]:
    """`allowed_menu_keys` baru untuk `target` sesudah `pemberi` menyimpan.

    Yang di luar wewenang pemberi DIPERTAHANKAN dari keadaan efektif target:
    menyimpan menulis ulang seluruh daftar, jadi tanpa ini admin diam-diam
    mencabut menu teknis yang bahkan tak bisa ia lihat (spec §3.5). Urutannya
    mengikuti ALL_MENUS, dan kunci yang tak dikenal terbuang.
    """
    from apps.auth_app.models import Role

    wewenang = wewenang_beri(pemberi, target.role)
    dipilih = set(dicentang) & wewenang
    if pemberi.role == Role.SUPERADMIN:
        baru = dipilih
    else:
        efektif = set(target.allowed_menu_keys or default_keys_for(target.role))
        baru = (efektif - wewenang) | dipilih
    return [m["key"] for m in ALL_MENUS if m["key"] in baru]
```

- [ ] **Step 6: Tambah `data_tersembunyi_baru` di `apps/auth_app/models.py`.** Letakkan
  tepat sesudah `DATA_KEY_SET = {...}`:

```python
def data_tersembunyi_baru(pemberi, target, boleh) -> list[str]:
    """`hidden_data_keys` baru untuk `target`. `boleh` = yang dicentang "boleh dilihat".

    Kunci yang tersembunyi dari `pemberi` sendiri tak bisa ia ubah untuk orang
    lain — nilainya di target dipertahankan (spec §3.5). Superadmin tak pernah
    dibatasi, jadi baginya ini tetap "semua dikurangi yang dicentang"."""
    boleh = {k for k in boleh if k in DATA_KEY_SET}
    wewenang = DATA_KEY_SET - pemberi.hidden_data()
    lama = {k for k in (target.hidden_data_keys or []) if k in DATA_KEY_SET}
    return sorted((lama - wewenang) | (wewenang - boleh))
```

  Catatan: `pemberi.hidden_data()` adalah method `User`, jadi fungsi ini hanya dipanggil pada
  instance. Ia boleh ditaruh sebelum `class User`, karena Python baru mencari atributnya saat
  fungsi dipanggil.

- [ ] **Step 7: Pastikan test baru lulus.**
  Jalankan `venv/Scripts/python.exe manage.py test apps.core.test_hak_akses --noinput`.
  Yang diharapkan: OK.

- [ ] **Step 8: Sesuaikan test lama yang menguji aturan lama.** Pakai tool Edit.
  1. `apps/monitoring/test_akses_kasir.py`, method `test_admin_tetap_dapat_sisanya_seperti_dulu`
     diganti seluruhnya dengan:

```python
    def test_admin_tetap_dapat_sisanya_seperti_dulu(self):
        keys = _keys(self.admin)
        for tetap in ("dashboard", "logs", "stock"):
            self.assertIn(tetap, keys, f"{tetap} hilang dari admin")
        # Menu teknis bukan bawaan peran mana pun (spec 2026-09-22 K2).
        for teknis in ("users", "connections"):
            self.assertNotIn(teknis, keys, f"{teknis} masih bawaan admin")
```

  2. Di berkas yang sama, `class MenuKhususAdminTests` beserta docstring-nya, sampai sebelum
     `def test_admin_dan_superadmin_tetap_mendapatkannya`, diganti dengan versi di bawah.
     Atribut `KUNCI`, `setUp`, dan dua test terakhir kelas itu tetap apa adanya.

```python
class MenuTulisKritisTests(TestCase):
    """`tulis_kritis` — bawaan admin; ke kasir/supervisor HANYA lewat superadmin.

    Dulu `admin_only`: dicentang pun dibuang untuk kasir/supervisor. Sekarang
    superadmin yang memutuskan (spec 2026-09-22 K1/K5), dan yang dijaga adalah
    siapa yang boleh MEMBERI — lihat apps/core/test_hak_akses.py.
    """

    # Empat layar tulis kas ikut di sini dengan alasan yang sama: uang bergerak
    # begitu disimpan, dan tak ada layar yang bisa menariknya kembali.
    # `nota_mundur` masuk dengan alasan BERBEDA dari yang lain: ia tidak menulis
    # apa pun. Ia menyebut nama penginput tiap dokumen bertanggal janggal, dan
    # daftar semacam itu bukan bacaan sehari-hari kasir atau supervisor yang
    # justru namanya ada di sana.
    KUNCI = ("opname", "koreksi_stok", "nota_mundur",
             "kas_biaya_input", "kas_pendapatan", "kas_penambahan", "kas_mutasi")

    def setUp(self):
        self.spv = User.objects.create_user("spv7", password="rahasia-kuat-123", role=Role.SUPERVISOR)
        self.kasir = User.objects.create_user("kasir7", password="rahasia-kuat-123", role=Role.KASIR)
        self.admin = User.objects.create_user("admin7", password="rahasia-kuat-123", role=Role.ADMIN)

    def test_ditandai_tulis_kritis_di_registry(self):
        ditandai = {m["key"] for m in ALL_MENUS if m.get("tulis_kritis")}
        self.assertEqual(ditandai, set(self.KUNCI))

    def test_pemberian_superadmin_ke_kasir_dan_supervisor_berlaku(self):
        for user in (self.spv, self.kasir):
            user.allowed_menu_keys = ["kasir_stok", *self.KUNCI]
            user.save(update_fields=["allowed_menu_keys"])
            keys = {m["key"] for m in menus_for(user, abaikan_tautan=True)}
            for k in self.KUNCI:
                self.assertIn(k, keys, f"{k} tak berlaku untuk {user.role}")
            self.assertIn("kasir_stok", keys)

```

  3. Di berkas yang sama, baris `self.assertIn("users", default_keys_for(Role.ADMIN))` diganti
     `self.assertIn("dashboard", default_keys_for(Role.ADMIN))`.
  4. `apps/monitoring/test_sync_health.py`:
     - docstring `test_admin_tanpa_batasan_pun_tetap_tak_bisa` diganti
       `"""Menu teknis bukan bawaan peran mana pun, jadi admin dengan hak bawaan pun tetap tertutup."""`;
     - `test_tak_muncul_di_daftar_yang_bisa_diberikan` diganti seluruhnya dengan:

```python
    def test_teknis_hanya_superadmin_yang_memberi(self):
        from apps.core.menus import ALL_MENUS, wewenang_beri

        menu = next(m for m in ALL_MENUS if m["key"] == "sync_health")
        self.assertTrue(menu.get("teknis"))
        pemberi = User.objects.create_user(
            "admin_km", password="rahasia-kuat-123", role=Role.ADMIN,
            allowed_menu_keys=["menus", "sync_health"])
        self.assertNotIn("sync_health", wewenang_beri(pemberi, Role.ADMIN))
```

  5. `apps/core/test_migrasi.py`, method `test_menu_superadmin_saja`: ganti namanya menjadi
     `test_menu_teknis`, dan ganti `self.assertTrue(m.get("superadmin_only"))` dengan
     `self.assertTrue(m.get("teknis"))`.
  6. `apps/monitoring/tests.py`: admin di `test_admin_tak_bisa_bikin_superadmin` (`"adm"`) dan
     `test_admin_tak_bisa_edit_superadmin` (`"adm2"`) sekarang harus diberi Manajemen User
     secara eksplisit. Tambahkan argumen `allowed_menu_keys=["users"]` ke kedua
     `User.objects.create_user(...)`. Tanpa itu keduanya berhenti di penjaga menu dan tak pernah
     menguji view-nya.

- [ ] **Step 9: Jalankan seluruh suite, lalu bereskan sisanya.**
  Jalankan `venv/Scripts/python.exe manage.py test --noinput 2>&1 | tail -40`.
  Aturan untuk setiap kegagalan yang tersisa:
  - **Admin bawaan tak lagi memegang menu teknis.** Kalau sebuah test gagal karena admin
    bawaan kini tidak punya salah satu dari `users`, `connections`, `sync_history`,
    `sync_harga`, `sync_master` (gejalanya 302/403 di rute menu itu), beri menunya eksplisit
    lewat `allowed_menu_keys=[...]` di `create_user`. Jangan ubah aturannya.
  - **Test yang menegaskan perilaku lama.** Contohnya "admin_only dibuang untuk kasir". Test
    seperti itu diubah supaya menegaskan perilaku baru, sesuai spec §3.2.

  Yang diharapkan pada akhirnya: semua OK. Jumlahnya 968 ditambah test baru.

- [ ] **Step 10: Commit.**

```bash
git -c safe.directory=* -c user.name=naufalrz-qi -c user.email=estarossa.nrz@gmail.com add -A apps/
git -c safe.directory=* -c user.name=naufalrz-qi -c user.email=estarossa.nrz@gmail.com commit -m "feat: aturan menu menjawab siapa boleh MEMBERI — teknis, tulis_kritis, wewenang_beri" -m "menus_for() kini murni pemberian; superadmin memberi apa pun ke siapa pun, admin hanya menu non-teknis yang ia pegang, dan menu_baru() mempertahankan yang di luar wewenangnya." -m "Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 3: View teknis menghormati pemberian, dan backend Kelola Menu

**Files:**
- Modify: `apps/monitoring/views.py`:
  - `_deny_non_superadmin` → `_wajib_menu`;
  - hapus `_bukan_admin`;
  - `menus_index`, `menus_save`;
  - import.
- Modify: `apps/core/middleware.py` (`_migrasi_tertunda`).
- Test: `apps/core/test_hak_akses.py` (tambah).

**Interfaces:**
- Consumes: `wewenang_beri`, `menu_baru` (Task 2); `bisa_kelola` (Task 1);
  `data_tersembunyi_baru` (Task 2).
- Produces:
  - `apps.monitoring.views._wajib_menu(request) -> HttpResponse | None`
  - Props Kelola Menu yang dipakai Task 6: `boleh_beri: {peran: [key]}`,
    `boleh_data: [key]`, `saya_superadmin: bool`

- [ ] **Step 1: Tambah test yang gagal.** Di `apps/core/test_hak_akses.py`, tambahkan
  `import json` dan `from unittest.mock import patch` di atas, lalu kelas ini di akhir berkas:

```python
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

    def test_penanda_migrasi_ikut_menu(self):
        from apps.core.middleware import _migrasi_tertunda

        with patch("apps.core.migrasi.tertunda", return_value=["a", "b"]):
            self.assertEqual(_migrasi_tertunda(self.admin2), 0)
            self.admin2.allowed_menu_keys = ["dashboard", "migrasi"]
            self.admin2.save(update_fields=["allowed_menu_keys"])
            self.assertEqual(_migrasi_tertunda(self.admin2), 2)
```

- [ ] **Step 2: Pastikan gagal.**
  Jalankan `venv/Scripts/python.exe manage.py test apps.core.test_hak_akses.KelolaMenuHttpTests --noinput`.
  Yang diharapkan: beberapa FAIL. Contohnya editor mendapat 403 di `/admin-panel/menus`
  (dari `_deny_non_superadmin`), `KeyError: 'boleh_beri'`, dan cadangan 403.

- [ ] **Step 3: Ganti penjaga peran dengan penjaga menu di `apps/monitoring/views.py`.**
  1. Import `apps.core.menus`: tambahkan `menu_baru`, `menu_key_for_path`, `menus_for`,
     `wewenang_beri` ke daftar `from apps.core.menus import (...)`. Import `apps.auth_app.models`:
     tambahkan `data_tersembunyi_baru`.
  2. Ganti seluruh fungsi `_deny_non_superadmin` dengan:

```python
def _wajib_menu(request):
    """Lapis kedua di atas `admin_network_guard`: tolak kalau menu pemilik path
    ini tak dipegang.

    Dulu `_deny_non_superadmin` — pengecekan PERAN yang membatalkan pemberian
    superadmin: menu teknis yang dicentang untuk admin tetap ditolak di sini
    (spec 2026-09-22 §3.6). Path tanpa menu ditolak, bukan diloloskan.
    """
    key = menu_key_for_path(request.path)
    if key and key in {m["key"] for m in menus_for(request.user)}:
        return None
    return ditolak(
        request,
        "Halaman ini belum dibuka untuk Anda",
        "Kalau Anda memang perlu membukanya, minta ke pengelola aplikasi.",
    )
```

  3. Dengan tool Edit (`replace_all`), ganti setiap `_deny_non_superadmin(request)` dengan
     `_wajib_menu(request)`. Ada 16 pemanggilan.
  4. Hapus seluruh fungsi `_bukan_admin` (definisi beserta docstring-nya). Lalu dengan
     `replace_all`, ganti setiap `_bukan_admin(request)` dengan `_wajib_menu(request)`. Ada 4
     pemanggilan: `koreksi_stok_index`, `koreksi_stok_save`, `kas_input_index`,
     `kas_input_save`.
  5. Pastikan tak ada sisa: `grep -n "_deny_non_superadmin\|_bukan_admin" apps/monitoring/views.py`
     harus kosong.

- [ ] **Step 4: Tulis ulang `menus_index` dan `menus_save`.** Ganti keduanya dengan:

```python
def menus_index(request):
    if (denied := _wajib_menu(request)):
        return denied
    saya = request.user
    users = [
        u for u in User.objects.exclude(role=Role.SUPERADMIN).order_by("role", "username")
        if bisa_kelola(saya, u)
    ]
    menus = assignable_menus()
    return render(
        request,
        "Admin/Menus/Index",
        props={
            "users": [
                {
                    "id": u.id,
                    "username": u.username,
                    "name": u.get_full_name() or u.username,
                    "role": u.role,
                    "allowed_menu_keys": u.allowed_menu_keys or [],
                    # Dikirim sebagai "boleh melihat" walau disimpan sebagai
                    # larangan: layar pengaturan tak boleh memaksa siapa pun
                    # berpikir terbalik saat mencentang.
                    "allowed_data_keys": sorted(DATA_KEY_SET - u.hidden_data()),
                }
                for u in users
            ],
            "menus": menus,
            "data_keys": DATA_KEYS,
            # Menu bawaan tiap peran. Tanpa ini layar berbohong: user yang
            # `allowed_menu_keys`-nya kosong tampil tanpa satu centang pun,
            # padahal ia SEDANG memegang menu bawaan perannya.
            "role_defaults": {
                r: default_keys_for(r)
                for r in (Role.KASIR, Role.SUPERVISOR, Role.ADMIN)
            },
            # Kunci yang boleh DIUBAH pemakai layar ini, per peran target.
            # Layar hanya membaca; aturannya di wewenang_beri(), dan
            # menus_save menegakkannya sendiri lewat menu_baru().
            "boleh_beri": {
                r: sorted(wewenang_beri(saya, r))
                for r in (Role.KASIR, Role.SUPERVISOR, Role.ADMIN)
            },
            "boleh_data": sorted(DATA_KEY_SET - saya.hidden_data()),
            "saya_superadmin": saya.role == Role.SUPERADMIN,
            # Urutan + label section untuk pengelompokan di UI.
            "sections": [
                {"key": s, "label": SECTION_LABELS[s]}
                for s in SECTIONS
                if any(m["section"] == s for m in menus)
            ],
        },
    )


def menus_save(request):
    if (denied := _wajib_menu(request)):
        return denied
    data = get_data(request)
    user = get_object_or_404(User, pk=data.get("user_id"))
    if user.role == Role.SUPERADMIN:
        return HttpResponseForbidden("Superadmin tidak dapat dibatasi.")
    if not bisa_kelola(request.user, user):
        return HttpResponseForbidden("Akun ini di luar wewenang Anda.")
    # Yang di luar wewenang pemakai layar dipertahankan dari keadaan target —
    # aturannya di menu_baru() dan data_tersembunyi_baru(), bukan di sini.
    keys = menu_baru(request.user, user, data.get("menu_keys") or [])
    user.allowed_menu_keys = keys
    user.hidden_data_keys = data_tersembunyi_baru(
        request.user, user, data.get("data_keys") or [])

    user.save(update_fields=["allowed_menu_keys", "hidden_data_keys"])
    log_activity(request, "menu", f"Set menu {user.username}: {','.join(keys) or '(kosong)'}")
    if user.hidden_data_keys:
        log_activity(request, "menu",
                     f"Sembunyikan nilai untuk {user.username}: {','.join(user.hidden_data_keys)}")
    request.session["flash_success"] = f"Menu untuk {user.username} diperbarui."
    return redirect("/admin-panel/menus")
```

- [ ] **Step 5: Penanda migrasi ikut menu (`apps/core/middleware.py`).** Di `_migrasi_tertunda`,
  ganti blok dari `from apps.auth_app.models import Role` sampai `return 0` yang pertama
  dengan kode di bawah. Kalimat pertama docstring juga diganti menjadi
  `Jumlah migrasi pangkal yang belum diterapkan. 0 bagi yang tak memegang menu migrasi.`

```python
    if not (user and getattr(user, "is_authenticated", False)):
        return 0
    # Ikut MENU, bukan peran: superadmin bisa memberikan Pembaruan Database ke
    # admin, dan penandanya harus ikut ke sana (spec 2026-09-22 §3.6).
    if "migrasi" not in {m["key"] for m in menus_for(user, abaikan_tautan=True)}:
        return 0
```

- [ ] **Step 6: Pastikan lulus.**
  Jalankan `venv/Scripts/python.exe manage.py test apps.core.test_hak_akses apps.core.test_migrasi apps.core.test_cadangan apps.monitoring --noinput`.
  Yang diharapkan: OK.
  Kalau ada test di `apps.monitoring` yang menegaskan pesan lama "Koreksi stok hanya untuk
  pengelola" atau penolakan berdasarkan peran, ubah supaya menegaskan penolakan berdasarkan
  **menu**: akun tanpa menunya ditolak, akun yang diberi menunya lolos.

- [ ] **Step 7: Commit.**

```bash
git -c safe.directory=* -c user.name=naufalrz-qi -c user.email=estarossa.nrz@gmail.com add -A apps/
git -c safe.directory=* -c user.name=naufalrz-qi -c user.email=estarossa.nrz@gmail.com commit -m "feat: view teknis menghormati pemberian menu; Kelola Menu bisa dibuka admin" -m "_deny_non_superadmin dan _bukan_admin diganti _wajib_menu (menu dipegang?), sehingga menu teknis yang diberikan superadmin benar-benar terbuka. menus_index mengirim boleh_beri/boleh_data per peran; menus_save menegakkan lewat menu_baru dan data_tersembunyi_baru." -m "Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 4: Model koneksi — label Internal, izin per user, aturan akses

**Files:**
- Modify: `apps/connections/models.py` (`Lingkungan`).
- Create: `apps/connections/migrations/0008_lingkungan_internal.py`.
- Modify: `apps/auth_app/models.py` (`User.koneksi_khusus`).
- Create: `apps/auth_app/migrations/0009_user_koneksi_khusus.py`.
- Create: `apps/connections/akses.py`.
- Create: `apps/connections/test_akses_koneksi.py`.

**Interfaces:**
- Produces:
  - `Lingkungan.INTERNAL == "internal"`
  - `User.koneksi_khusus` (M2M ke `ServerProfile`, `related_name="pengguna_khusus"`)
  - di `apps.connections.akses`:
    - `koneksi_boleh(user) -> QuerySet[ServerProfile]`
    - `boleh_pakai(user, profile_or_id) -> bool`
    - `profil_untuk_sesi(user, pid_sesi: int | None) -> int | None`

- [ ] **Step 1: Tulis test yang gagal.** Buat `apps/connections/test_akses_koneksi.py`:

```python
"""Akses koneksi non-produksi — spec 2026-09-22 §4."""
import importlib
import json
from unittest.mock import patch

from django.apps import apps as django_apps
from django.test import TestCase

from apps.auth_app.models import Role, User
from apps.connections.akses import boleh_pakai, koneksi_boleh, profil_untuk_sesi
from apps.connections.models import Lingkungan, ServerProfile

PW = "rahasia-kuat-123"


def _profil(nama, lingkungan=Lingkungan.PRODUKSI, **kw):
    return ServerProfile.objects.create(name=nama, host="h", db_name="d", username="u",
                                        lingkungan=lingkungan, **kw)


class KoneksiBolehTests(TestCase):
    def setUp(self):
        self.prod = _profil("PUSAT", is_default=True)
        self.uji = _profil("Testing", Lingkungan.UJI)
        self.internal = _profil("AMPHOREUS", Lingkungan.INTERNAL)
        self.boss = User.objects.create_user("boss", password=PW, role=Role.SUPERADMIN)
        self.adm = User.objects.create_user("adm", password=PW, role=Role.ADMIN)
        self.kasir = User.objects.create_user("kasir", password=PW, role=Role.KASIR,
                                              server_profile=self.uji)

    def _ids(self, user):
        return set(koneksi_boleh(user).values_list("pk", flat=True))

    def test_superadmin_semua(self):
        self.assertEqual(self._ids(self.boss), {self.prod.pk, self.uji.pk, self.internal.pk})

    def test_admin_hanya_produksi(self):
        self.assertEqual(self._ids(self.adm), {self.prod.pk})

    def test_admin_ditambah_koneksi_khusus(self):
        self.adm.koneksi_khusus.add(self.internal)
        self.assertEqual(self._ids(self.adm), {self.prod.pk, self.internal.pk})
        self.assertTrue(boleh_pakai(self.adm, self.internal))
        self.assertFalse(boleh_pakai(self.adm, self.uji))

    def test_kasir_terkunci_ke_servernya_apa_pun_labelnya(self):
        self.assertEqual(self._ids(self.kasir), {self.uji.pk})

    def test_pilihan_sesi_ilegal_jatuh_ke_default(self):
        self.assertEqual(profil_untuk_sesi(self.adm, self.internal.pk), self.prod.pk)
        self.assertEqual(profil_untuk_sesi(self.adm, None), self.prod.pk)
        self.assertEqual(profil_untuk_sesi(self.adm, self.prod.pk), self.prod.pk)

    def test_superadmin_pilihannya_dihormati(self):
        self.assertEqual(profil_untuk_sesi(self.boss, self.internal.pk), self.internal.pk)

    def test_tanpa_koneksi_yang_diizinkan_hasilnya_none(self):
        self.prod.lingkungan = Lingkungan.UJI
        self.prod.save(update_fields=["lingkungan"])
        self.assertIsNone(profil_untuk_sesi(self.adm, None))


class MigrasiTandaiHubTests(TestCase):
    def test_profil_hub_ditandai_internal(self):
        hub = _profil("AMPHOREUS")
        lain = _profil("GUDANG")
        mig = importlib.import_module("apps.connections.migrations.0008_lingkungan_internal")
        with patch.dict("os.environ", {"HUB_NAME": "AMPHOREUS"}):
            mig.tandai(django_apps, None)
        hub.refresh_from_db()
        lain.refresh_from_db()
        self.assertEqual(hub.lingkungan, Lingkungan.INTERNAL)
        self.assertEqual(lain.lingkungan, Lingkungan.PRODUKSI)
```

  `json` diimpor sekarang, tapi baru dipakai di Task 5.

- [ ] **Step 2: Pastikan gagal.**
  Jalankan `venv/Scripts/python.exe manage.py test apps.connections.test_akses_koneksi --noinput`.
  Yang diharapkan: `ModuleNotFoundError: No module named 'apps.connections.akses'`.

- [ ] **Step 3: Label `Internal` (`apps/connections/models.py`).**
  1. Tambahkan anggota ketiga di `class Lingkungan`, sesudah `UJI = "uji", "Uji coba"`:
     `INTERNAL = "internal", "Internal"`.
  2. Paragraf docstring yang diawali `Sengaja TIDAK menggerakkan izin apa pun.` (sampai
     `operator selalu tahu sedang di mana.`) diganti dengan:

```text
    Sejak 2026-09-22 label ini MENGGERAKKAN izin: semua yang bukan Produksi
    hanya bisa dipilih superadmin, kecuali ia memberikannya per user lewat
    `User.koneksi_khusus` di Kelola Menu (apps/connections/akses.py). `Internal`
    untuk database milik kita sendiri yang bukan server POS — AMPHOREUS.
    Jalur tulis tak ikut berubah: pemeriksaan `== UJI` di muat.py,
    salin_legacy.py, dan transfer.py tetap persis seperti sebelumnya.
```

- [ ] **Step 4: Migrasi `connections`.** Buat `apps/connections/migrations/0008_lingkungan_internal.py`:

```python
"""Label Internal untuk database milik kita sendiri (AMPHOREUS).

Profil hub dikenali lewat HUB_NAME, nama yang sama yang dipakai scheduler dan
pull_hub untuk menemukannya — bukan tebakan dari host atau tipe.
"""
import os

from django.db import migrations, models


def tandai(apps, schema_editor):
    ServerProfile = apps.get_model("connections", "ServerProfile")
    nama = os.environ.get("HUB_NAME", "AMPHOREUS")
    ServerProfile.objects.filter(name=nama).update(lingkungan="internal")


def balik(apps, schema_editor):
    ServerProfile = apps.get_model("connections", "ServerProfile")
    ServerProfile.objects.filter(lingkungan="internal").update(lingkungan="produksi")


class Migration(migrations.Migration):
    dependencies = [("connections", "0007_tandai_profil_uji")]
    operations = [
        migrations.AlterField(
            model_name="serverprofile",
            name="lingkungan",
            field=models.CharField(
                choices=[("produksi", "Produksi"), ("uji", "Uji coba"), ("internal", "Internal")],
                default="produksi", max_length=10),
        ),
        migrations.RunPython(tandai, balik),
    ]
```

- [ ] **Step 5: `User.koneksi_khusus` dan migrasinya.**
  1. Di `apps/auth_app/models.py`, di dalam `class User`, sesudah field `server_profile`,
     tambahkan:

```python
    # Koneksi NON-produksi (uji coba / internal) yang boleh dipilih akun ini.
    # Produksi tak perlu dicantumkan — semua akun tak terkunci boleh memakainya.
    # Diatur superadmin di Kelola Menu; aturannya di apps/connections/akses.py.
    koneksi_khusus = models.ManyToManyField(
        "connections.ServerProfile", blank=True, related_name="pengguna_khusus",
    )
```

  2. Buat `apps/auth_app/migrations/0009_user_koneksi_khusus.py`:

```python
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("auth_app", "0008_rename_menu_update_harga"),
        ("connections", "0008_lingkungan_internal"),
    ]
    operations = [
        migrations.AddField(
            model_name="user",
            name="koneksi_khusus",
            field=models.ManyToManyField(
                blank=True, related_name="pengguna_khusus", to="connections.serverprofile"),
        ),
    ]
```

  3. Periksa bahwa tak ada migrasi yang terlewat:
     `venv/Scripts/python.exe manage.py makemigrations --check --dry-run`.
     Yang diharapkan: `No changes detected`.

- [ ] **Step 6: Aturan akses.** Buat `apps/connections/akses.py`:

```python
"""Siapa boleh memakai koneksi mana (spec 2026-09-22 §4).

Satu tempat untuk aturannya; middleware (pilihan sesi + daftar navbar),
connections_set_default, dan Manajemen User membacanya. Job latar belakang
tidak lewat sini — mereka tak punya user.
"""
from django.db.models import Q

from apps.auth_app.models import Role

from .models import Lingkungan, ServerProfile


def koneksi_boleh(user):
    """Profil yang boleh dipakai `user`.

    Superadmin: semua. Akun terkunci (kasir/supervisor): hanya servernya
    sendiri, apa pun labelnya — yang menentukannya Manajemen User. Selain itu:
    semua Produksi, ditambah `koneksi_khusus` pemberian superadmin.
    """
    qs = ServerProfile.objects.all()
    if user is None or not getattr(user, "is_authenticated", False):
        return qs.none()
    if user.role == Role.SUPERADMIN:
        return qs
    if user.koneksi_terkunci:
        return qs.filter(pk=user.server_profile_id) if user.server_profile_id else qs.none()
    return qs.filter(
        Q(lingkungan=Lingkungan.PRODUKSI) | Q(pk__in=user.koneksi_khusus.values("pk"))
    ).distinct()


def boleh_pakai(user, profile_or_id) -> bool:
    pk = getattr(profile_or_id, "pk", profile_or_id)
    return pk is not None and koneksi_boleh(user).filter(pk=pk).exists()


def profil_untuk_sesi(user, pid_sesi):
    """Profil yang dipakai permintaan ini untuk akun TAK terkunci.

    Pilihan di sesi dipakai kalau masih boleh; kalau tidak — izinnya dicabut,
    atau profilnya kini non-produksi — jatuh ke `is_default` bila boleh, lalu ke
    profil pertama yang boleh. None kalau tak ada satu pun. Superadmin tak
    disaring: pilihannya apa adanya (None = default global, seperti dulu).
    """
    if user.role == Role.SUPERADMIN:
        return pid_sesi
    boleh = list(koneksi_boleh(user).values_list("pk", "is_default"))
    ids = [pk for pk, _ in boleh]
    if pid_sesi in ids:
        return pid_sesi
    default = next((pk for pk, is_default in boleh if is_default), None)
    if default is not None:
        return default
    return ids[0] if ids else None
```

- [ ] **Step 7: Pastikan lulus.**
  Jalankan `venv/Scripts/python.exe manage.py test apps.connections apps.core.test_hak_akses --noinput`.
  Yang diharapkan: OK.

- [ ] **Step 8: Commit.**

```bash
git -c safe.directory=* -c user.name=naufalrz-qi -c user.email=estarossa.nrz@gmail.com add apps/connections apps/auth_app
git -c safe.directory=* -c user.name=naufalrz-qi -c user.email=estarossa.nrz@gmail.com commit -m "feat: label lingkungan Internal, izin koneksi per user, aturan koneksi_boleh" -m "AMPHOREUS (HUB_NAME) ditandai Internal oleh migrasi. Selain Produksi hanya superadmin, kecuali diberikan lewat User.koneksi_khusus." -m "Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 5: Menegakkan akses koneksi

**Files:**
- Modify: `apps/core/middleware.py` (`inertia_share`: pilihan sesi dan `connections_list`).
- Modify: `apps/connections/views.py` (`connections_set_default`).
- Modify: `apps/monitoring/views.py`:
  - `users_index` (`server_profiles`);
  - `users_save` (validasi server);
  - `menus_index`/`menus_save` (koneksi khusus).
- Test: `apps/connections/test_akses_koneksi.py` (tambah).

**Interfaces:**
- Consumes: `koneksi_boleh`, `boleh_pakai`, `profil_untuk_sesi` (Task 4); `_qs_terkelola`
  (Task 1); `_wajib_menu`, `menus_index`, `menus_save` (Task 3).
- Produces:
  - Props Kelola Menu untuk Task 6: `koneksi_nonprod: [{id, name, lingkungan}]` (hanya untuk
    superadmin) dan `users[].koneksi_khusus: [id]`
  - `menus_save` menerima `koneksi_khusus: [id]`

- [ ] **Step 1: Tambah test yang gagal.** Tambahkan di akhir `apps/connections/test_akses_koneksi.py`:

```python
def _props(client, url="/admin-panel/profile"):
    r = client.get(url, HTTP_X_INERTIA="true", HTTP_X_INERTIA_VERSION="1.0")
    return json.loads(r.content)["props"]


class PenegakanKoneksiTests(TestCase):
    def setUp(self):
        self.prod = _profil("PUSAT", is_default=True)
        self.uji = _profil("Testing", Lingkungan.UJI)
        self.internal = _profil("AMPHOREUS", Lingkungan.INTERNAL)
        self.boss = User.objects.create_user("boss", password=PW, role=Role.SUPERADMIN)
        self.adm = User.objects.create_user("adm", password=PW, role=Role.ADMIN,
                                            allowed_menu_keys=["dashboard", "users", "menus"])
        self.kasir = User.objects.create_user("kasir", password=PW, role=Role.KASIR,
                                              server_profile=self.prod)

    def test_daftar_koneksi_tersaring(self):
        self.client.force_login(self.adm)
        self.assertEqual({c["id"] for c in _props(self.client)["connections"]}, {self.prod.pk})
        self.client.force_login(self.boss)
        self.assertEqual(len(_props(self.client)["connections"]), 3)

    def test_pilihan_sesi_ilegal_diganti_default_dan_dibuang(self):
        self.client.force_login(self.adm)
        s = self.client.session
        s["active_profile_id"] = self.internal.pk
        s.save()
        self.assertEqual(_props(self.client)["active_connection"]["id"], self.prod.pk)
        self.assertNotIn("active_profile_id", self.client.session)

    def test_set_default_ditolak_tanpa_izin(self):
        self.client.force_login(self.adm)
        with patch("apps.connections.views.mssql.test_profile") as tes:
            self.client.post(f"/admin-panel/connections/{self.uji.pk}/set-default")
        tes.assert_not_called()
        self.assertNotEqual(self.client.session.get("active_profile_id"), self.uji.pk)

    def test_set_default_diterima_setelah_diberi(self):
        self.adm.koneksi_khusus.add(self.uji)
        self.client.force_login(self.adm)
        with patch("apps.connections.views.mssql.test_profile",
                   return_value={"ok": True, "message": ""}):
            self.client.post(f"/admin-panel/connections/{self.uji.pk}/set-default")
        self.assertEqual(self.client.session.get("active_profile_id"), self.uji.pk)

    def test_admin_tak_bisa_mengunci_kasir_ke_uji(self):
        self.client.force_login(self.adm)
        self.client.post("/admin-panel/users/save", {
            "id": self.kasir.pk, "username": "kasir", "name": "Kasir", "role": "kasir",
            "server_profile_id": str(self.uji.pk)})
        self.kasir.refresh_from_db()
        self.assertEqual(self.kasir.server_profile_id, self.prod.pk)

    def test_nilai_nonprod_yang_tak_berubah_diterima(self):
        self.kasir.server_profile = self.uji
        self.kasir.save(update_fields=["server_profile"])
        self.client.force_login(self.adm)
        self.client.post("/admin-panel/users/save", {
            "id": self.kasir.pk, "username": "kasir", "name": "Ganti Nama", "role": "kasir",
            "server_profile_id": str(self.uji.pk)})
        self.kasir.refresh_from_db()
        self.assertEqual(self.kasir.first_name, "Ganti")
        self.assertEqual(self.kasir.server_profile_id, self.uji.pk)

    def test_superadmin_memberi_koneksi_khusus_lewat_kelola_menu(self):
        self.client.force_login(self.boss)
        self.client.post("/admin-panel/menus/save", {
            "user_id": self.adm.pk, "menu_keys": ["dashboard"], "data_keys": [],
            "koneksi_khusus": [self.internal.pk, self.prod.pk]}, content_type="application/json")
        self.assertEqual(set(self.adm.koneksi_khusus.values_list("pk", flat=True)),
                         {self.internal.pk})

    def test_admin_tak_bisa_memberi_koneksi_khusus(self):
        adm2 = User.objects.create_user("adm2", password=PW, role=Role.ADMIN)
        self.client.force_login(self.adm)
        self.client.post("/admin-panel/menus/save", {
            "user_id": adm2.pk, "menu_keys": [], "data_keys": [],
            "koneksi_khusus": [self.internal.pk]}, content_type="application/json")
        self.assertFalse(adm2.koneksi_khusus.exists())

    def test_kelola_menu_mengirim_koneksi_nonprod_hanya_ke_superadmin(self):
        self.client.force_login(self.boss)
        ids = {k["id"] for k in _props(self.client, "/admin-panel/menus")["koneksi_nonprod"]}
        self.assertEqual(ids, {self.uji.pk, self.internal.pk})
        self.client.force_login(self.adm)
        self.assertEqual(_props(self.client, "/admin-panel/menus")["koneksi_nonprod"], [])
```

- [ ] **Step 2: Pastikan gagal.**
  Jalankan `venv/Scripts/python.exe manage.py test apps.connections.test_akses_koneksi.PenegakanKoneksiTests --noinput`.
  Yang diharapkan: beberapa FAIL. Contohnya `connections` berisi 3 untuk admin, `test_profile`
  terpanggil, dan `KeyError: 'koneksi_nonprod'`.

- [ ] **Step 3: Middleware (`apps/core/middleware.py`, `inertia_share`).**
  1. Ganti blok `if user is not None and ... koneksi_terkunci ...: ... else: mssql.set_request_profile_id(session.get(...))`
     dengan:

```python
        masuk = user is not None and getattr(user, "is_authenticated", False)
        if masuk and getattr(user, "koneksi_terkunci", False):
            mssql.set_request_profile_id(user.server_profile_id, strict=True)
        elif masuk:
            # Pilihan di sesi divalidasi setiap permintaan: izin koneksi bisa
            # dicabut, atau profilnya berubah jadi non-produksi, sesudah dipilih
            # (spec 2026-09-22 §4.3). Pilihan yang tak lagi boleh dibuang,
            # bukan dipakai diam-diam.
            from apps.connections.akses import profil_untuk_sesi

            pilihan = session.get("active_profile_id") if session is not None else None
            pid = profil_untuk_sesi(user, pilihan)
            if session is not None and pilihan is not None and pid != pilihan:
                session.pop("active_profile_id", None)
            # None bagi non-superadmin = tak ada koneksi yang boleh: jangan
            # jatuh ke is_default, yang bisa saja profil terbatas.
            mssql.set_request_profile_id(pid, strict=pid is None and user.role != "superadmin")
        else:
            mssql.set_request_profile_id(session.get("active_profile_id") if session else None)
```

  2. Ganti isi `connections_list()` dengan:

```python
        def connections_list():
            # Satu aturan untuk semua peran (apps/connections/akses.py): akun
            # terkunci mendapat servernya sendiri, admin mendapat Produksi +
            # pemberian superadmin, superadmin semuanya. Penjagaan sebenarnya
            # tetap di server (connections_set_default + validasi sesi di atas).
            from apps.connections.akses import koneksi_boleh

            return [p.as_dict() for p in koneksi_boleh(user)]
```

- [ ] **Step 4: `connections_set_default` (`apps/connections/views.py`).**
  1. Tambahkan import `from .akses import boleh_pakai`.
  2. Sesudah baris `profile = get_object_or_404(ServerProfile, pk=conn_id)`, sisipkan:

```python
    # Rute ini dikecualikan dari pemeriksaan menu (_MENU_EXEMPT_RE), jadi
    # izinnya harus dicek DI SINI — kalau tidak, profil non-produksi tetap bisa
    # dipilih dengan memanggil URL-nya langsung.
    if not boleh_pakai(request.user, profile):
        request.session["flash_error"] = (
            f"Koneksi {profile.name} bukan untuk akun Anda. "
            "Minta superadmin membukanya di Kelola Menu.")
        return redirect_aman(get_data(request), "/admin-panel/connections")
```

- [ ] **Step 5: Manajemen User (`apps/monitoring/views.py`).**
  1. Tambahkan import `from django.db.models import Q` (kalau belum ada) dan
     `from apps.connections.models import Lingkungan` (kalau `ServerProfile` sudah diimpor
     dari sana, gabungkan dengannya).
  2. Di `users_index`, ganti nilai `"server_profiles"` dengan pemanggilan fungsi baru
     `_pilihan_server(request.user, users)`, dan tambahkan fungsi ini di atas `users_index`:

```python
def _pilihan_server(pengelola, users):
    """Server yang boleh ditetapkan `pengelola` untuk akun terkunci.

    Selain superadmin: hanya Produksi — mengunci kasir ke server uji berarti
    notanya tertulis ke salinan, bukan ke toko. Server non-produksi yang SUDAH
    terpasang di akun yang tampil ikut dimuat supaya dropdown tidak kosong
    (dan tidak diam-diam mengosongkannya saat disimpan)."""
    qs = ServerProfile.objects.all().order_by("name")
    if pengelola.role != Role.SUPERADMIN:
        terpasang = {u.server_profile_id for u in users if u.server_profile_id}
        qs = qs.filter(Q(lingkungan=Lingkungan.PRODUKSI) | Q(pk__in=terpasang))
    return [{"value": p.pk, "label": f"{p.name} ({p.db_type})"} for p in qs]
```

  3. Di `users_save`, ganti dua baris
     `sp = data.get("server_profile_id")` / `user.server_profile_id = int(sp) if ... else None`
     dengan:

```python
    sp = data.get("server_profile_id")
    sp_baru = int(sp) if str(sp or "").isdigit() else None
    # Hanya superadmin yang boleh mengunci akun ke server non-produksi. Nilai
    # yang tidak berubah tetap diterima, supaya admin masih bisa menyunting nama
    # kasir yang oleh superadmin dikunci ke server uji.
    if (sp_baru and sp_baru != user.server_profile_id
            and request.user.role != Role.SUPERADMIN
            and not ServerProfile.objects.filter(
                pk=sp_baru, lingkungan=Lingkungan.PRODUKSI).exists()):
        request.session["flash_error"] = (
            "Server uji coba/internal hanya bisa ditetapkan superadmin.")
        return redirect("/admin-panel/users")
    user.server_profile_id = sp_baru
```

- [ ] **Step 6: Kelola Menu membawa koneksi khusus.**
  1. Di `menus_index`, ganti baris `users = [` sampai `]` dengan versi prefetch:

```python
    users = [
        u for u in User.objects.exclude(role=Role.SUPERADMIN)
        .prefetch_related("koneksi_khusus").order_by("role", "username")
        if bisa_kelola(saya, u)
    ]
    superadmin = saya.role == Role.SUPERADMIN
```

  2. Di dict per user di dalam `"users": [...]`, tambahkan:

```python
                    # Hanya untuk superadmin: pemberian koneksi non-produksi
                    # bukan wewenang admin (spec K6/K7).
                    "koneksi_khusus": (
                        [p.pk for p in u.koneksi_khusus.all()] if superadmin else []),
```

  3. Di dict `props`, ganti `"saya_superadmin": saya.role == Role.SUPERADMIN,` dengan:

```python
            "saya_superadmin": superadmin,
            "koneksi_nonprod": [
                {"id": p.pk, "name": p.name, "lingkungan": p.lingkungan}
                for p in ServerProfile.objects.exclude(
                    lingkungan=Lingkungan.PRODUKSI).order_by("name")
            ] if superadmin else [],
```

  4. Di `menus_save`, sebelum `user.save(update_fields=...)`, sisipkan:

```python
    # Izin koneksi non-produksi: HANYA superadmin. Kunci yang dikirim akun lain
    # diabaikan, bukan ditolak — layar admin memang tak menampilkannya.
    if request.user.role == Role.SUPERADMIN and "koneksi_khusus" in data:
        ids = [int(x) for x in (data.get("koneksi_khusus") or []) if str(x).isdigit()]
        user.koneksi_khusus.set(ServerProfile.objects.filter(pk__in=ids)
                                .exclude(lingkungan=Lingkungan.PRODUKSI))
        log_activity(request, "menu", f"Koneksi khusus {user.username}: "
                     f"{','.join(str(i) for i in sorted(user.koneksi_khusus.values_list('pk', flat=True))) or '(tidak ada)'}")
```

- [ ] **Step 7: Pastikan lulus.**
  Jalankan `venv/Scripts/python.exe manage.py test apps.connections apps.core apps.monitoring apps.auth_app --noinput`.
  Yang diharapkan: OK.

- [ ] **Step 8: Commit.**

```bash
git -c safe.directory=* -c user.name=naufalrz-qi -c user.email=estarossa.nrz@gmail.com add -A apps/
git -c safe.directory=* -c user.name=naufalrz-qi -c user.email=estarossa.nrz@gmail.com commit -m "feat: akses koneksi non-produksi ditegakkan — sesi, set-default, daftar navbar, Manajemen User" -m "Superadmin memberi izin koneksi khusus per user di Kelola Menu." -m "Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 6: Layar — Kelola Menu, pemilih koneksi, label

**Files:**
- Modify: `frontend/utils/labels.js` (`LINGKUNGAN_LABELS`).
- Modify: `frontend/components/nav/ConnectionMenu.vue`.
- Modify: `frontend/pages/Admin/Menus/Index.vue`.

**Interfaces:**
- Consumes props Kelola Menu dari Task 3 dan Task 5: `boleh_beri`, `boleh_data`,
  `saya_superadmin`, `koneksi_nonprod`, `users[].koneksi_khusus`.
- Consumes shared prop `connections[].lingkungan` (sudah ada).

- [ ] **Step 1: Label.** Di `frontend/utils/labels.js`, `LINGKUNGAN_LABELS` menjadi:

```js
export const LINGKUNGAN_LABELS = {
  produksi: "Produksi",
  uji: "Uji coba",
  internal: "Internal",
};
```

- [ ] **Step 2: `ConnectionMenu.vue`.**
  1. Di `<script setup>`, tambahkan `import { computed } from "vue";`. Ganti tiga baris
     `// Lencana hanya muncul untuk uji...` / `const uji = ...` / `const ujiLabel = ...`
     dengan:

```js
// Lencana untuk semua yang BUKAN produksi. Produksi tetap tanpa lencana dengan
// sengaja: kalau setiap koneksi berlencana, tak ada yang menonjol -- dan yang
// perlu menonjol justru keadaan yang tidak biasa.
const bukanProduksi = (c) => Boolean(c?.lingkungan) && c.lingkungan !== "produksi";
const labelLingkungan = (c) => LINGKUNGAN_LABELS[c?.lingkungan] || c?.lingkungan;

// Dua grup (spec 2026-09-22 K8). Daftarnya sudah disaring server: yang tak
// berhak tak menerima profil non-produksi sama sekali, jadi grup kedua pun
// tak pernah muncul baginya.
const grup = computed(() => [
  { judul: "Produksi", isi: list.value.filter((c) => !bukanProduksi(c)) },
  { judul: "Uji coba & internal", isi: list.value.filter(bukanProduksi) },
].filter((g) => g.isi.length));
```

  2. Di tombol atas, ganti `v-if="uji(active)"` dengan `v-if="bukanProduksi(active)"`, dan
     `{{ ujiLabel }}` dengan `{{ labelLingkungan(active) }}`.
  3. Ganti blok `<div v-if="list.length" class="max-h-96 overflow-y-auto py-1"> ... </div>`
     dengan:

```html
        <div v-if="list.length" class="max-h-96 overflow-y-auto py-1">
          <template v-for="g in grup" :key="g.judul">
            <!-- Judul grup hanya kalau memang ada dua grup: satu grup berjudul
                 "Produksi" sendirian cuma menambah baris. -->
            <p
              v-if="grup.length > 1"
              class="px-4 pb-1 pt-2 text-[10px] font-semibold uppercase tracking-wider text-ink-subtle"
            >{{ g.judul }}</p>
            <button
              v-for="c in g.isi"
              :key="c.id"
              class="flex w-full items-center gap-2 px-4 py-2 text-left text-sm hover:bg-surface-3"
              @click="choose(c)"
            >
              <span :class="['h-2 w-2 shrink-0 rounded-full', dot(c.status)]" />
              <span class="min-w-0 flex-1 truncate text-ink">
                {{ c.name }}
                <span class="text-xs text-ink-muted">· {{ typeName[c.db_type] || c.db_type }}</span>
              </span>
              <span
                v-if="bukanProduksi(c)"
                class="shrink-0 rounded bg-warning-bg px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-warning-fg"
              >{{ labelLingkungan(c) }}</span>
              <span v-if="c.id === active?.id" class="shrink-0 rounded bg-brand-bg px-1.5 py-0.5 text-xs font-medium text-brand-fg">
                Aktif
              </span>
            </button>
          </template>
        </div>
```

- [ ] **Step 3: `Menus/Index.vue`, bagian skrip.**
  1. Tambahkan `import { LINGKUNGAN_LABELS } from "@/utils/labels";`.
  2. Di `defineProps`, tambahkan:

```js
  // Kunci menu yang boleh DIUBAH pemakai layar ini, per peran target
  // (wewenang_beri di server). Server tetap menegakkannya sendiri.
  boleh_beri: { type: Object, default: () => ({}) },
  boleh_data: { type: Array, default: () => [] }, // kunci nilai uang yang boleh diubah
  saya_superadmin: { type: Boolean, default: false },
  koneksi_nonprod: { type: Array, default: () => [] }, // [{id, name, lingkungan}], superadmin saja
```

  3. Ganti blok komentar `// Menu ber-admin_only tak berlaku ...` beserta `const terkunci = ...`
     dengan:

```js
// Centang yang TIDAK boleh diubah pemakai layar ini. Penjagaan sebenarnya di
// server — menu_baru() mempertahankan yang di luar wewenang — jadi ini hanya
// supaya layar tak menjanjikan perubahan yang takkan tersimpan.
const terkunci = (m) =>
  Boolean(selected.value) && !(props.boleh_beri[selected.value.role] || []).includes(m.key);
function alasanKunci(m) {
  if (m.teknis) return "khusus superadmin";
  if (m.tulis_kritis && selected.value?.role !== "admin") return "superadmin saja untuk peran ini";
  return "tidak Anda pegang";
}
const dataTerkunci = (d) => !props.boleh_data.includes(d.key);
const koneksiChecked = reactive({});
const tampilKoneksi = computed(
  () => props.saya_superadmin && selected.value?.role === "admin" && props.koneksi_nonprod.length > 0,
);
```

  4. Ganti `toggleSection` dan `setAll` dengan versi yang melewati kotak terkunci:

```js
function toggleSection(s) {
  const bisa = s.items.filter((m) => !terkunci(m));
  const target = !bisa.every((m) => checked[m.key]);
  bisa.forEach((m) => (checked[m.key] = target));
}
// `value` boleh boolean (semua/kosong) atau daftar kunci (mis. bawaan peran).
// Kotak terkunci tak disentuh: tombol massal tak boleh tampak mengubah yang
// memang tak bisa diubah.
function setAll(value) {
  const daftar = Array.isArray(value) ? value : null;
  props.menus.forEach((m) => {
    if (terkunci(m)) return;
    checked[m.key] = daftar ? daftar.includes(m.key) : value;
  });
}
```

  5. Di akhir `select(user)`, tambahkan:

```js
  const khusus = user.koneksi_khusus || [];
  props.koneksi_nonprod.forEach((k) => {
    koneksiChecked[k.id] = khusus.includes(k.id);
  });
```

  6. Di `save()`, ganti objek yang dikirim `{ user_id: selected.value.id, menu_keys, data_keys }`
     dengan variabel `payload`:

```js
  const payload = { user_id: selected.value.id, menu_keys, data_keys };
  if (tampilKoneksi.value) {
    payload.koneksi_khusus = props.koneksi_nonprod.filter((k) => koneksiChecked[k.id]).map((k) => k.id);
  }
```

  Lalu `router.post("/admin-panel/menus/save", payload, {...})`.

- [ ] **Step 4: `Menus/Index.vue`, bagian template.**
  1. Paragraf pembuka diganti dengan:

```html
    <p class="mb-4 text-sm text-ink-muted">
      Atur menu yang boleh diakses tiap user. <strong>Superadmin</strong> selalu punya akses penuh dan tidak muncul di daftar.
      <template v-if="!saya_superadmin">
        Anda hanya bisa mengubah menu yang Anda pegang sendiri; menu teknis hanya bisa diberikan superadmin.
      </template>
    </p>
```

  2. Di kotak Nilai Uang:
     - tambahkan `:disabled="dataTerkunci(d)"` ke `<input type="checkbox" v-model="dataChecked[d.key]" ...>`;
     - tambahkan `dataTerkunci(d) ? 'cursor-not-allowed opacity-50' : 'cursor-pointer',` ke array
       `:class` label-nya, dan buang `cursor-pointer` yang tertulis tetap di string pertama.
  3. Tepat sesudah `</section>` Nilai Uang, sisipkan:

```html
          <!-- Koneksi non-produksi: superadmin saja, dan hanya untuk admin —
               kasir/supervisor dikunci ke satu server lewat Manajemen User. -->
          <section v-if="tampilKoneksi" class="mb-5 rounded-control border border-border-default p-3">
            <div class="mb-2 border-b border-border-default pb-1.5">
              <h3 class="text-xs font-semibold uppercase tracking-wider text-ink-muted">Akses Koneksi Non-Produksi</h3>
              <p class="mt-1 text-xs text-ink-subtle">
                Koneksi uji coba dan internal (mis. AMPHOREUS) hanya muncul di pemilih koneksi
                superadmin, kecuali dicentang di sini. Koneksi produksi selalu tersedia.
              </p>
            </div>
            <div class="grid grid-cols-1 gap-2 sm:grid-cols-3">
              <label
                v-for="k in koneksi_nonprod"
                :key="k.id"
                :class="[
                  'flex cursor-pointer items-center gap-3 rounded-control border px-3 py-2.5 transition-colors',
                  koneksiChecked[k.id] ? 'border-brand-500/60 bg-brand-bg' : 'border-border-default hover:bg-surface-2',
                ]"
              >
                <input
                  type="checkbox"
                  v-model="koneksiChecked[k.id]"
                  class="h-4 w-4 rounded border-border-strong text-brand-600 focus:ring-brand-500"
                />
                <span class="flex-1 text-sm text-ink-muted">{{ k.name }}</span>
                <Badge variant="neutral" class="shrink-0 text-[10px]">{{ LINGKUNGAN_LABELS[k.lingkungan] || k.lingkungan }}</Badge>
              </label>
            </div>
          </section>
```

  4. Pada label menu:
     - `:title` diganti `terkunci(m) ? `${m.label}: ${alasanKunci(m)}.` : undefined`;
     - isi badge `admin saja` diganti `{{ alasanKunci(m) }}`.

     Penghitung `Pilih semua (x/y)` tetap menghitung semua item. Itu memang yang dipegang akun
     itu.

- [ ] **Step 5: Build.** Jalankan `npm run build`.
  Yang diharapkan: `✓ built in ...` tanpa error kompilasi Vue.

- [ ] **Step 6: Verifikasi di browser.**
  1. `preview_start` dengan nama `arunika` (runserver :8001, `.claude/launch.json`).
  2. **Pengguna yang login** (Claude tak mengetik password).
  3. Periksa:
     - **Sebagai superadmin:**
       - Kelola Menu menampilkan ke-12 menu teknis tanpa kunci;
       - memilih akun admin memunculkan bagian *Akses Koneksi Non-Produksi*;
       - pemilih koneksi di navbar punya dua grup.
     - **Sebagai admin yang diberi Kelola Menu:**
       - dirinya tak ada di daftar user;
       - menu teknis terkunci dengan badge "khusus superadmin";
       - `koreksi_stok` untuk kasir terkunci dengan badge "superadmin saja untuk peran ini";
       - bagian koneksi tidak ada;
       - pemilih koneksi hanya berisi Produksi.
  4. Periksa `read_console_messages` bersih, lalu ambil screenshot sebagai bukti.

- [ ] **Step 7: Commit.**

```bash
git -c safe.directory=* -c user.name=naufalrz-qi -c user.email=estarossa.nrz@gmail.com add frontend/utils/labels.js frontend/components/nav/ConnectionMenu.vue frontend/pages/Admin/Menus/Index.vue
git -c safe.directory=* -c user.name=naufalrz-qi -c user.email=estarossa.nrz@gmail.com commit -m "feat: Kelola Menu mengunci yang di luar wewenang; pemilih koneksi dua grup" -m "Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 7: Dokumen, lalu verifikasi penuh

**Files:**
- Modify: `CLAUDE.md` (paragraf koneksi aktif; paragraf RBAC di "Routing").
- Modify: `context.md` (dua penyebutan flag lama).
- Modify: `apps/transactions/kas.py` (komentar), `apps/monitoring/urls.py` (komentar).

- [ ] **Step 1: `CLAUDE.md`.** Pakai tool Edit.
  1. Paragraf yang diawali `**Single active connection, multi-server.**` diganti seluruhnya
     dengan:

```markdown
**Per-session active connection, multi-server.** All MS SQL access flows through `core/mssql.py` → `get_active_profile()`, which returns the profile `inertia_share` stamped for the current request: kasir/supervisor are locked to `User.server_profile`; everyone else picks from the navbar (stored in their own session) and the pick is re-validated every request by `apps/connections/akses.py` — Produksi profiles for everyone, non-Produksi (`uji`, and `internal` such as AMPHOREUS) only for superadmin or for accounts granted them via `User.koneksi_khusus` in Kelola Menu. A pick that is no longer allowed is dropped and replaced by `is_default` (if allowed) or the first allowed profile. Background jobs have no request and fall back to `is_default`. Profile passwords are **Fernet-encrypted** (`POS_FERNET_KEY`) and only decrypted in-process inside `core/mssql.py`.
```

  2. Di paragraf `**Routing.**`, kalimat dari `Three menu flags override the per-user grants:`
     sampai `sub-paths included, via prefix matching.` diganti dengan:

```markdown
Menu flags decide who may **grant**, not who may **hold** (spec `docs/superpowers/specs/2026-09-22-hak-akses-bertingkat-design.md`): `teknis` (12 technical menus — Koneksi Server, Manajemen User, Kelola Menu, Kelola Tautan User, and the sync/backup/migration/kode-nota screens; only superadmin grants them and they are no role's default), `tulis_kritis` (the stock/cash write screens + Nota Tanggal Mundur; admin default, granted to kasir/supervisor only by superadmin), and `butuh_tautan` (the screens that WRITE to the legacy server, dropped when the account has no `TautanUser` for the *currently active connection* — superadmin included; derive the count from `KEYS_BUTUH_TAUTAN`, don't trust a number written in prose). `menus_for()` itself is purely grant-based: whatever superadmin ticks, applies. The grant rule is one function, `menus.wewenang_beri(pemberi, peran_target)` — superadmin grants anything but `always`; anyone else holding Kelola Menu grants only non-`teknis` menus they hold themselves (`tulis_kritis` only to admins), and `menu_baru()` preserves every key outside that authority on save (money keys likewise, via `auth_app.models.data_tersembunyi_baru`). Who manages whom is `auth_app.models.bisa_kelola()` — rank-based, never self — shared by Kelola Menu and Manajemen User. Views of technical menus double-check with `_wajib_menu(request)` (is the owning menu held?), never with a role test, so a grant actually opens the page. `menus_for()` is also what `admin_network_guard` reads, so a revoked menu cannot be reached by typing its URL — sub-paths included, via prefix matching.
```

- [ ] **Step 2: `context.md`.**
  1. Di bullet `**Satu aturan untuk TIGA layar.**`, ganti `menu \`logs\` bukan \`superadmin_only\``
     dengan `menu \`logs\` bukan \`teknis\``.
  2. Bullet yang diawali `- **Aksesnya \`admin_only\`**` diganti dengan:

```markdown
- **Aksesnya `tulis_kritis`** (flag di `apps/core/menus.py`, dipakai `opname`, `koreksi_stok`, `nota_mundur`, dan keempat layar tulis kas): bawaan admin, dan ke kasir/supervisor hanya lewat superadmin — admin dengan Kelola Menu tak bisa memberikannya ke mereka (`wewenang_beri`). Sampai 2026-09-22 flagnya `admin_only` dan membuang menu ini untuk kasir/supervisor walau dicentang; sekarang pemberian superadmin berlaku. View-nya memeriksa ulang lewat `_wajib_menu` (menu dipegang?), bukan peran.
```

- [ ] **Step 3: Komentar kode.**
  - `apps/transactions/kas.py`: `Itu alasan menunya admin_only + butuh_tautan` diganti
    `Itu alasan menunya tulis_kritis + butuh_tautan`.
  - `apps/monitoring/urls.py`: `Sub-path mewarisi \`superadmin_only\` milik` diganti
    `Sub-path mewarisi flag \`teknis\` milik`.
  - `frontend/layouts/AdminLayout.vue`: di komentar penanda migrasi,
    `Server mengirim 0 bagi selain superadmin, jadi tak ada pengecekan peran di sini.` diganti
    `Server mengirim 0 bagi yang tak memegang menu Pembaruan Database, jadi tak ada pengecekan
    di sini.` Berkas ini juga ikut di-`git add` pada Step 5, lalu `npm run build` diulang di
    Step 4.
  - Terakhir, `grep -rn "superadmin_only\|admin_only\|_managed_roles\|_deny_non_superadmin" apps core config frontend/pages frontend/components --include=*.py --include=*.vue --include=*.js`
    harus hanya menyisakan `_managed_roles` (masih dipakai `users_index`/`users_save`) dan teks
    sejarah di docstring test.

- [ ] **Step 4: Verifikasi penuh.**
  1. `venv/Scripts/python.exe manage.py test --noinput 2>&1 | tail -5`: 0 failure, jumlah test
     = 968 + test baru.
  2. `venv/Scripts/python.exe manage.py makemigrations --check --dry-run` → `No changes detected`.
  3. `npm run build` → sukses.

- [ ] **Step 5: Commit.**

```bash
git -c safe.directory=* -c user.name=naufalrz-qi -c user.email=estarossa.nrz@gmail.com add CLAUDE.md context.md apps/transactions/kas.py apps/monitoring/urls.py frontend/layouts/AdminLayout.vue
git -c safe.directory=* -c user.name=naufalrz-qi -c user.email=estarossa.nrz@gmail.com commit -m "docs: CLAUDE.md & context.md mengikuti hak akses bertingkat" -m "Paragraf koneksi aktif 'global' sudah lama basi (koneksi per sesi); paragraf RBAC kini menjelaskan teknis/tulis_kritis/wewenang_beri." -m "Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Sesudah rencana ini (bukan bagian eksekusi)

Deploy ke produksi (`D:\App\arunikasct_POS_Prod`, layanan `APP_SCTPOS`) setelah branch ini
di-merge. Urutannya:
1. `nssm stop APP_SCTPOS` (elevated).
2. `git pull`.
3. `pip install -r requirements.txt`. Pertahankan `mssql-django==1.8.0`.
4. `npm ci && npm run build`.
5. `manage.py migrate`, yang menjalankan `connections.0008` (menandai AMPHOREUS Internal) dan
   `auth_app.0009`.
6. `collectstatic --noinput --clear`.
7. `nssm start APP_SCTPOS`.

Pastikan juga `NT AUTHORITY\SYSTEM` punya hak menulis tabel baru `auth_app_user_koneksi_khusus`.
Peran `db_datawriter` sudah mencakupnya.

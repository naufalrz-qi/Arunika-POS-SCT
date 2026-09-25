"""Kolom yang WAJIB ditulis Arunika supaya payload sync legacy tidak jadi NULL.

Trigger feed legacy (`insert_temp_m_*` / `update_temp_m_*`) merangkai setiap
kolom baris ke `tbl_tmp_post.query` (dikirim job legacy ke sink pusat) dan ke
`tbl_log_transaksi.formatted_data` (dibaca `feed_sync`, `riwayat_log`, dan Nota
Tanggal Mundur) dengan operator `+`. Di SQL Server `'x' + NULL` adalah NULL,
jadi SATU kolom NULL membuat seluruh payload NULL — tanpa galat apa pun. Baris
dokumennya tersimpan rapi di server toko, dan tak pernah sampai ke mana pun.

Aturannya karena itu: **setiap kolom payload yang boleh NULL dan tak punya
DEFAULT harus ditulis Arunika.** Aplikasi POS lama selalu mengisinya sendiri —
itulah sebabnya data lama tak pernah bermasalah.

Modul ini satu sumber untuk tiga pemakai:

- `test_payload_sync` — penjaga statis atas dump `docs/skema/`, supaya jalur
  tulis baru yang lupa satu kolom gagal di test, bukan di server toko;
- `manage.py cek_payload_sync` — pemeriksaan server HIDUP (trigger dan DEFAULT
  dibaca dari katalognya sendiri) plus hitungan baris yang sudah terlanjur NULL;
- siapa pun yang menambah jalur tulis berikutnya: daftarkan tabelnya di
  `kolom_ditulis()`.

Kenapa dump saja tak cukup: `scripts/dump_skema_aturan.py` dulu hanya membaca
`sys.default_constraints`, sehingga *bound default* gaya lama (`sp_bindefault`)
tak terlihat. Kolom yang "tanpa DEFAULT" menurut dump bisa saja ber-DEFAULT di
server. Jalur tulis tetap menulisnya eksplisit — nilainya sama dengan yang akan
diisi DEFAULT atau yang ditulis aplikasi lama — jadi benar di kedua dunia.
"""
from __future__ import annotations

import re

# `val__<kolom>__<nilai>` adalah bentuk setiap kolom di `formatted_data`;
# `divisi_id` diisi `dbo.getDivisionID()`, bukan dari baris, jadi tak ikut.
_POLA_PAYLOAD = re.compile(r"val__(\w+?)__")
_BUKAN_KOLOM = {"divisi_id"}

# Trigger yang merangkai baris jadi payload. `delete_temp_*` hanya membawa
# kolom kunci yang NOT NULL, jadi tak pernah jadi NULL karena kolom lain.
AWALAN_TRIGGER = ("insert_temp_m_", "update_temp_m_")


def kolom_payload(teks_trigger: str) -> set[str]:
    """Kolom baris yang dirangkai trigger feed ke payload-nya."""
    return set(_POLA_PAYLOAD.findall(teks_trigger or "")) - _BUKAN_KOLOM


def kolom_ditulis() -> dict[str, set[str]]:
    """{tabel legacy: kolom yang ditulis Arunika saat INSERT}.

    Dirangkai dari konstanta jalur tulis yang sama dengan yang dipakai INSERT-
    nya, bukan daftar kedua yang bisa berbeda diam-diam. Kolom yang diisi
    ekspresi SQL (`tanggal_server = GETDATE()`) ikut disebut: ia tertulis.
    """
    from apps.transactions import kas, opname, transaksi
    from apps.transactions import penjualan as pj

    out = {
        "t_penjualan": set(pj._HEADER) | set(pj.EKSPRESI_NOTA),
        "t_penjualan_detail": set(pj._DETAIL),
        "t_penjualan_total": {"no_transaksi", "total"},
        "t_penjualan_order": set(pj._ORDER_HEADER) | set(pj.EKSPRESI_ORDER),
        "t_penjualan_order_detail": set(pj._ORDER_DETAIL),
        "t_opname_stok": set(opname.KOLOM),
    }
    for s in transaksi.SPEC.values():
        out[s["tabel"]] = set(s["header"]) | set(s.get("ekspresi", {}))
        out[s["tabel_detail"]] = set(s["detail"])
    for s in kas.SPEC.values():
        out[s["tabel"]] = set(s["kolom"])
    return out


def berisiko(payload: set[str], kolom: dict[str, dict], ditulis: set[str]) -> list[str]:
    """Kolom payload yang bisa membuat payload NULL untuk baris tulisan Arunika.

    `kolom` = {nama: {"nullable": bool, "default": str|None, "computed": bool}}.
    Kolom yang tak dikenal tabelnya dilewati: trigger boleh merujuk kolom yang
    sudah dibuang, dan itu masalah trigger, bukan jalur tulis.
    """
    keluar = []
    for k in sorted(payload):
        info = kolom.get(k)
        if (info and info["nullable"] and not info.get("computed")
                and not info.get("default") and k not in ditulis):
            keluar.append(k)
    return keluar

"""Shared per-profile TTL cache for legacy master-data reads.

m_* tables change rarely but streaming them costs seconds per page load on
slow links (54k products ≈ 9s over WAN). Cached per profile with a TTL;
master-data writes must call invalidate_master_cache(). Shared between
apps.inventory.services and apps.master_data.services so ONE invalidation
call busts both — do not give each app its own cache dict.
"""
import os
import time

# Ongkos cache dingin sangat berbeda per server. Terukur pada _barang_meta
# (55rb barang): 1,2 detik lewat LAN, 21,8 detik lewat Tailscale antar-kota.
# Dengan TTL 600 detik, pengguna server jauh menanggung 22 detik itu tiap 10
# menit. Naikkan POS_MASTER_TTL (mis. 3600) kalau ada profil lewat WAN —
# tabel m_* memang jarang berubah, dan setiap tulis master memanggil
# invalidate_master_cache() sehingga perubahan tetap langsung terlihat.
_MASTER_TTL = int(os.environ.get("POS_MASTER_TTL", 600))  # seconds
_master_cache: dict = {}


def _cached(profile, name, build, ttl=None, force=False):
    """Ambil dari cache, atau bangun dan simpan.

    `force` + `ttl`: dipakai pemanas terjadwal (apps/core/scheduler.py) yang
    membangun ulang isi cache SEBELUM kedaluwarsa dengan umur lebih panjang dari
    jeda tick-nya, sehingga tak pernah ada celah waktu di mana seorang pengguna
    yang membuka halaman menanggung ongkos cache dingin."""
    key = (profile.pk, name)
    if not force:
        hit = _master_cache.get(key)
        if hit and hit[0] > time.monotonic():
            return hit[1]
    val = build()
    _master_cache[key] = (time.monotonic() + (ttl or _MASTER_TTL), val)
    return val


def invalidate_master_cache(profile_id=None, prefix=None):
    """Call after writing to m_* tables so pages see fresh master data.

    `prefix`: buang hanya key yang namanya berawalan itu. Dipakai untuk key
    berkunci tanggal (mis. "purchase_prices:2026-07-27") supaya set hari kemarin
    tak menumpuk di dict — tanpa ini key lama tak pernah terhapus, cuma
    kedaluwarsa, dan tiap key memuat puluhan ribu entri."""
    if profile_id is None:
        _master_cache.clear()
        return
    for k in [k for k in _master_cache if k[0] == profile_id]:
        if prefix is None or (isinstance(k[1], str) and k[1].startswith(prefix)):
            del _master_cache[k]

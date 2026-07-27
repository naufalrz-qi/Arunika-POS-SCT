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


def _cached(profile, name, build):
    key = (profile.pk, name)
    hit = _master_cache.get(key)
    if hit and hit[0] > time.monotonic():
        return hit[1]
    val = build()
    _master_cache[key] = (time.monotonic() + _MASTER_TTL, val)
    return val


def invalidate_master_cache(profile_id=None):
    """Call after writing to m_* tables so pages see fresh master data."""
    if profile_id is None:
        _master_cache.clear()
    else:
        for k in [k for k in _master_cache if k[0] == profile_id]:
            del _master_cache[k]

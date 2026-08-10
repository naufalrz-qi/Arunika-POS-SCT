"""Request helpers.

Inertia's `useForm().post()` sends the payload as application/json (not form-encoded),
so `request.POST` is empty. `get_data` returns whichever is populated, as a dict-like
object exposing `.get()`.
"""
import ipaddress
import json

from django.conf import settings
from django.shortcuts import redirect
from django.utils.http import url_has_allowed_host_and_scheme


def ip_dalam(ip: str, jaringan) -> bool:
    """Apakah `ip` termasuk salah satu `jaringan` (daftar `ip_network`).

    Satu tempat untuk `try/except ValueError`-nya. Dua penjaga memakai bentuk ini
    — proxy tepercaya di sini, dan rentang yang boleh membuka /admin-panel di
    `middleware._ip_allowed` — dan alamat tak terbaca harus berarti TIDAK di
    keduanya. Dua salinan akan menyimpang persis di penanganan galat itu, yaitu
    di satu-satunya cabang yang tak pernah dijalani saat semuanya normal.
    """
    try:
        alamat = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return any(alamat in n for n in jaringan)


def _tepercaya(ip: str) -> bool:
    """Apakah `ip` salah satu proxy yang kita pasang sendiri (`TRUSTED_PROXIES`)."""
    return ip_dalam(ip, settings.TRUSTED_PROXIES)


def client_ip(request) -> str:
    """Alamat asli penelepon — sadar reverse proxy, tapi tidak mudah dibohongi.

    `REMOTE_ADDR` adalah lawan bicara TCP. Tanpa proxy ia memang si klien; DI
    BELAKANG proxy ia selalu proxy-nya, dan di situlah tiga hal di aplikasi ini
    rusak sekaligus tanpa satu pun galat:

    - `admin_network_guard` membandingkannya dengan rentang CGNAT Tailscale, dan
      `ADMIN_IP_ALLOWLIST` memuat `127.0.0.1`. Proxy di mesin yang sama membuat
      SETIAP permintaan lolos — `ENFORCE_TAILSCALE=1` berubah jadi hiasan, dan
      tak ada yang berubah di layar, di log, maupun di pesan galat.
    - Setiap baris `ActivityLog` mencatat `127.0.0.1`, jadi audit trail berhenti
      bisa menjawab "dari mana".
    - Kunci throttle login jadi sama untuk semua orang: satu kasir salah ketik
      lima kali mengunci seluruh toko.

    Karena itu `X-Forwarded-For` hanya dibaca kalau lawan bicaranya memang proxy
    yang KITA daftarkan di `TRUSTED_PROXIES`. Header itu dikirim klien dan bisa
    diisi apa saja; memercayainya tanpa syarat sama dengan membiarkan siapa pun
    mengetik "saya dari Tailscale".

    Ditelusuri dari KANAN, melewati alamat yang dikenal sebagai proxy sendiri.
    nginx `$proxy_add_x_forwarded_for` MENAMBAHKAN peer asli di ujung kanan, jadi
    nilai yang dipalsukan klien selalu berada di kiri dan tak pernah terpilih.
    """
    peer = request.META.get("REMOTE_ADDR", "") or ""
    if not (settings.TRUSTED_PROXIES and _tepercaya(peer)):
        return peer
    rantai = [p.strip() for p in request.META.get("HTTP_X_FORWARDED_FOR", "").split(",")]
    for kandidat in reversed(rantai):
        if kandidat and not _tepercaya(kandidat):
            return kandidat
    # Seluruh rantai proxy kita sendiri (atau headernya kosong): tak ada yang
    # bisa disimpulkan, jadi jawab apa adanya alih-alih menebak.
    return peer


def redirect_aman(data, default: str):
    """Redirect ke `redirect_to` di payload, tapi HANYA bila ia path di situs ini.

    Jalur simpan yang bisa dipanggil dari lebih dari satu halaman perlu tahu ke
    mana harus kembali (Update Barang dipanggil dari Pergerakan Harga; pemilih
    koneksi dipanggil dari halaman mana pun). Tanpa pemeriksaan di sini,
    `redirect_to` adalah open redirect — dan bentuk yang paling meyakinkan pula,
    karena tautannya memang benar-benar berasal dari domain aplikasi sebelum
    melempar korban ke halaman login palsu.

    Dipakai `url_has_allowed_host_and_scheme` alih-alih `startswith("/")` buatan
    sendiri: `//evil.com` dan `/\\evil.com` sama-sama diawali "/" tapi dibaca
    peramban sebagai host lain. `allowed_hosts=None` berarti hanya URL tanpa host
    yang lolos, jadi tak ada daftar domain yang perlu dirawat.

    Sengaja TIDAK dibatasi ke prefiks `/admin-panel/` seperti versi lamanya:
    pemilih koneksi menempel di navbar setiap halaman, termasuk `/kasir/*`, dan
    batasan itu akan melempar orang keluar dari layar yang sedang ia pakai.
    """
    target = (data.get("redirect_to") or "").strip()
    if target and url_has_allowed_host_and_scheme(target, allowed_hosts=None):
        return redirect(target)
    return redirect(default)


def get_data(request):
    if request.POST:
        return request.POST
    ctype = request.content_type or ""
    if "application/json" in ctype and request.body:
        try:
            return json.loads(request.body)
        except ValueError:
            return {}
    return {}

"""Halaman harian kasir & supervisor (prefix /kasir).

Terpisah dari views.py bukan karena rapi-rapian: penjaga di apps/core/middleware.py
memperlakukan /kasir berbeda dari /admin-panel (tanpa syarat Tailscale), jadi
memisahkan berkasnya membuat batas itu terlihat saat membaca kode.
"""
import datetime as dt

import pyodbc
from django.http import JsonResponse
from django.shortcuts import redirect
from django.views.decorators.http import require_POST
from inertia import defer, render

from apps.auth_app.tautan import tautan_untuk, tautan_wajib
from apps.core.http import get_data
from apps.core.models import log_activity
from apps.inventory import services as inv
from apps.master_data import master_crud
from apps.transactions import penjualan as pj
from apps.transactions import transaksi as tx
from apps.monitoring.views import CONN_ERROR, _active, _hidden_fields
from core import mssql


def cek_stok(request):
    """Cari barang lalu lihat stok + harganya. Hanya baca."""
    cari = (request.GET.get("cari") or "").strip()
    kd_divisi = (request.GET.get("kd_divisi") or "").strip()

    def muat():
        rows, divisi_list, conn_error = [], [], None
        profile = _active()
        if not profile:
            return {"rows": [], "divisi_list": [], "conn_error": CONN_ERROR}
        try:
            divisi_list = inv.list_divisi(profile)
            rows = inv.cek_stok(profile, cari, kd_divisi=kd_divisi or None)
        except pyodbc.Error as exc:
            conn_error = mssql.friendly_error(exc, "Gagal membaca stok")

        # Kasir umumnya tak boleh melihat modal. Penjagaannya HARUS di sini —
        # membuang kolomnya di Vue hanya kosmetik.
        buang = _hidden_fields(request)
        if buang:
            rows = [{k: v for k, v in r.items() if k not in buang} for r in rows]
        return {"rows": rows, "divisi_list": divisi_list, "conn_error": conn_error}

    return render(
        request,
        "Kasir/CekStok",
        props={"stok": defer(muat), "filters": {"cari": cari, "kd_divisi": kd_divisi}},
    )


def _layar_penjualan(request, mode: str):
    """Layar buat nota penjualan (mode "nota") atau order (mode "order").

    Satu layar untuk keduanya, bukan dua salinan: bentuk isiannya sama persis —
    pelanggan, keranjang barang, diskon, pajak. Yang berbeda cuma ke tabel mana
    ia ditulis dan apakah ada uang yang berpindah, dan itu dikirim sebagai prop.
    """
    cari = (request.GET.get("cari") or "").strip()
    order = mode == "order"

    # Tautan koneksi AKTIF, bukan tautan akun: kode legacy berbeda artinya di
    # tiap server, jadi layar harus menunjukkan yang berlaku di server ini.
    tautan = tautan_untuk(request.user, _active())

    def muat():
        profile = _active()
        if not profile:
            return {"opsi": {}, "hasil_cari": [], "conn_error": CONN_ERROR}
        try:
            opsi = pj.opsi_nota(profile)
            return {
                "opsi": opsi,
                "hasil_cari": pj.cari_barang(profile, cari),
                "bawaan": pj.bawaan_form(
                    profile, "penjualan_order" if order else "penjualan"),
                "nama_divisi": _label(inv.list_divisi(profile), "kd_divisi", "nama",
                                      tautan.kd_divisi),
                "nama_pegawai": _label(opsi["pegawai"], "value", "label",
                                       tautan.kd_pegawai),
                "conn_error": None,
            }
        except pyodbc.Error as exc:
            return {"opsi": {}, "hasil_cari": [],
                    "conn_error": mssql.friendly_error(exc, "Gagal membaca data nota")}

    return render(request, "Kasir/Penjualan", props={
        "nota": defer(muat),
        "filters": {"cari": cari},
        "mode": mode,
        "base": "/kasir/penjualan-order" if order else "/kasir/penjualan",
        # Ditampilkan di layar supaya kasir tahu nota akan tercatat atas nama
        # siapa — dan tahu sejak awal kalau akunnya belum ditautkan.
        "kd_user": tautan.kd_user,
        "kd_divisi": tautan.kd_divisi,
        "kd_pegawai": tautan.kd_pegawai,
        # Hanya layar nota yang boleh MENGAMBIL penanda ini: kalau layar order
        # ikut mem-pop-nya, tombol Cetak di layar nota kehilangan nomornya
        # begitu kasir sempat mampir ke order.
        "nota_terakhir": "" if order else request.session.pop("nota_terakhir", ""),
    })


def penjualan(request):
    return _layar_penjualan(request, "nota")


def penjualan_order(request):
    return _layar_penjualan(request, "order")


@require_POST
def penjualan_save(request):
    data = get_data(request)
    profile = _active()
    if not profile:
        request.session["flash_error"] = CONN_ERROR
        return redirect("/kasir/penjualan")
    try:
        # Tautan koneksi aktif. `tautan_wajib` menolak kalau belum ada — TIDAK
        # meminjam tautan koneksi lain, sebab kode yang sama milik orang lain di
        # server lain dan notanya akan tersimpan tanpa galat atas nama mereka.
        tautan = tautan_wajib(request.user, profile)
        hasil = pj.buat_nota(
            profile,
            kd_user=tautan.kd_user,
            # kd_divisi dari TAUTAN, tidak pernah dari kiriman layar: ia
            # menentukan awalan nomor nota dan milik cabang mana nota tercatat.
            kd_divisi=tautan.kd_divisi,
            kd_customer=data.get("kd_customer"),
            kd_jenis=data.get("kd_jenis"),
            kd_kas=data.get("kd_kas"),
            kd_voucher=data.get("kd_voucher"),
            kd_pegawai=data.get("kd_pegawai") or tautan.kd_pegawai,
            items=data.get("items") or [],
            keterangan=data.get("keterangan") or pj.KOSONG,
            no_bukti=data.get("no_bukti") or pj.KOSONG,
            tanggal=_waktu(data.get("tanggal")),
            no_order=(data.get("no_order") or "").strip(),
            jatuh_tempo=_waktu(data.get("jatuh_tempo")),
            diskon_uang=float(data.get("diskon_uang") or 0),
            pajak=float(data.get("pajak") or 0),
            status=int(data.get("status") or 1),
        )
    except ValueError as exc:
        request.session["flash_error"] = str(exc)
        return redirect("/kasir/penjualan")
    except (pyodbc.Error, RuntimeError) as exc:
        request.session["flash_error"] = (
            str(exc) if isinstance(exc, RuntimeError)
            else mssql.friendly_error(exc, "Gagal menyimpan nota"))
        return redirect("/kasir/penjualan")

    log_activity(request, "penjualan",
                 f"Nota {hasil['no_transaksi']} — {hasil['baris']} baris, "
                 f"total {hasil['total']:.0f}"
                 + (f", dari order {hasil['no_order']}" if hasil.get("no_order") else ""))
    # Nomor ASLI, bukan ancar-ancar yang tampil sebelum simpan: nomor bisa
    # bergeser kalau kasir lain (atau POS lama) mendahului, dan tombol Cetak
    # yang memakai ancar-ancar akan mencetak nota MILIK ORANG LAIN.
    request.session["nota_terakhir"] = hasil["no_transaksi"]
    request.session["flash_success"] = (
        f"Nota {hasil['no_transaksi']} tersimpan. Total Rp {hasil['total']:,.0f}".replace(",", "."))
    return redirect("/kasir/penjualan")


@require_POST
def penjualan_order_save(request):
    data = get_data(request)
    profile = _active()
    if not profile:
        request.session["flash_error"] = CONN_ERROR
        return redirect("/kasir/penjualan-order")
    try:
        tautan = tautan_wajib(request.user, profile)
        hasil = pj.buat_order(
            profile,
            kd_user=tautan.kd_user,
            # Dari TAUTAN koneksi aktif, tak pernah dari kiriman layar —
            # alasannya sama dengan nota: kd_divisi menentukan order ini milik
            # cabang mana.
            kd_divisi=tautan.kd_divisi,
            kd_customer=data.get("kd_customer"),
            kd_jenis=data.get("kd_jenis"),
            kd_kas=data.get("kd_kas"),
            kd_voucher=data.get("kd_voucher"),
            kd_pegawai=data.get("kd_pegawai") or tautan.kd_pegawai,
            items=data.get("items") or [],
            keterangan=data.get("keterangan") or pj.KOSONG,
            no_bukti=data.get("no_bukti") or pj.KOSONG,
            tanggal=_waktu(data.get("tanggal")),
            diskon_uang=float(data.get("diskon_uang") or 0),
            pajak=float(data.get("pajak") or 0),
        )
    except ValueError as exc:
        request.session["flash_error"] = str(exc)
        return redirect("/kasir/penjualan-order")
    except (pyodbc.Error, RuntimeError) as exc:
        request.session["flash_error"] = (
            str(exc) if isinstance(exc, RuntimeError)
            else mssql.friendly_error(exc, "Gagal menyimpan order"))
        return redirect("/kasir/penjualan-order")

    log_activity(request, "penjualan_order",
                 f"Order {hasil['no_order']} — {hasil['baris']} baris, "
                 f"total {hasil['total']:.0f}")
    request.session["flash_success"] = (
        f"Order {hasil['no_order']} tersimpan. "
        f"Total Rp {hasil['total']:,.0f}".replace(",", "."))
    return redirect("/kasir/penjualan-order")


def faktur(request):
    """Cetak ulang faktur — satu isian: nomor transaksi.

    Fakturnya dirender DI HALAMAN INI, bukan dengan mengarahkan ke
    /kasir/penjualan/<no>/cetak: rute itu milik menu Penjualan, jadi orang yang
    hanya diberi menu Cetak Faktur akan terpental dari halaman cetaknya sendiri.

    Kolom uang tidak disaring di sini, sama seperti jalur cetak yang sudah ada —
    faktur memang lembar harga untuk pembeli. Yang tak boleh melihat harga
    dicabut menunya, bukan dikosongkan fakturnya.
    """
    no = (request.GET.get("no") or "").strip()

    def muat():
        if not no:
            return {"nota": None, "pesan": "", "conn_error": None}
        profile = _active()
        if not profile:
            return {"nota": None, "pesan": "", "conn_error": CONN_ERROR}
        try:
            nota = pj.baca_nota(profile, no)
        except pyodbc.Error as exc:
            return {"nota": None, "pesan": "",
                    "conn_error": mssql.friendly_error(exc, "Gagal membaca nota")}
        return {"nota": nota, "conn_error": None,
                "pesan": "" if nota else f"Nota {no} tidak ditemukan."}

    return render(request, "Kasir/Faktur",
                  props={"hasil": defer(muat), "filters": {"no": no}})


def _transaksi_index(request, jenis: str):
    """Layar buat transaksi (retur penjualan / pembelian / retur pembelian)."""
    s = tx.spec(jenis)
    cari = (request.GET.get("cari") or "").strip()
    pihak_supplier = s["pihak"] == "kd_supplier"
    tautan = tautan_untuk(request.user, _active())

    def muat():
        profile = _active()
        if not profile:
            return {"opsi": {}, "hasil_cari": [], "conn_error": CONN_ERROR}
        try:
            opsi = pj.opsi_nota(profile)
            if pihak_supplier:
                # Pihaknya supplier, bukan pelanggan — dan m_supplier kecil,
                # jadi seluruhnya muat sebagai pilihan.
                opsi["pihak"] = [
                    {"value": r["kd_supplier"], "label": r["nama"]}
                    for r in master_crud.list_master(profile, "supplier", limit=500)
                ]
            else:
                opsi["pihak"] = opsi["pelanggan"]
            return {"opsi": opsi, "hasil_cari": pj.cari_barang(profile, cari),
                    "conn_error": None}
        except pyodbc.Error as exc:
            return {"opsi": {}, "hasil_cari": [],
                    "conn_error": mssql.friendly_error(exc, "Gagal membaca data transaksi")}

    return render(request, "Kasir/Transaksi", props={
        "nota": defer(muat),
        "filters": {"cari": cari},
        "jenis": jenis,
        "label": s["label"],
        "label_pihak": "Supplier" if pihak_supplier else "Pelanggan",
        "aksi_url": f"/kasir/{jenis.replace('_', '-')}",
        "pakai_pegawai": "kd_pegawai" in s["detail"],
        "kd_user": tautan.kd_user,
        "kd_divisi": tautan.kd_divisi,
    })


def _transaksi_save(request, jenis: str):
    s = tx.spec(jenis)
    tujuan = f"/kasir/{jenis.replace('_', '-')}"
    data = get_data(request)
    profile = _active()
    if not profile:
        request.session["flash_error"] = CONN_ERROR
        return redirect(tujuan)
    try:
        tautan = tautan_wajib(request.user, profile)
        hasil = tx.buat(
            profile, jenis,
            # Dari TAUTAN koneksi aktif, tak pernah dari kiriman layar: keduanya
            # menentukan atas nama siapa dan cabang mana transaksi ini tercatat.
            kd_user=tautan.kd_user,
            kd_divisi=tautan.kd_divisi,
            kd_pihak=data.get("kd_pihak"),
            kd_jenis=data.get("kd_jenis"),
            kd_kas=data.get("kd_kas"),
            kd_pegawai=data.get("kd_pegawai") or "",
            items=data.get("items") or [],
            keterangan=data.get("keterangan") or tx.KOSONG,
            pajak=float(data.get("pajak") or 0),
            ppnbm=float(data.get("ppnbm") or 0),
        )
    except ValueError as exc:
        request.session["flash_error"] = str(exc)
        return redirect(tujuan)
    except (pyodbc.Error, RuntimeError) as exc:
        request.session["flash_error"] = (
            str(exc) if isinstance(exc, RuntimeError)
            else mssql.friendly_error(exc, f"Gagal menyimpan {s['label'].lower()}"))
        return redirect(tujuan)

    log_activity(request, jenis,
                 f"{s['label']} {hasil['nomor']} — {hasil['baris']} baris, total {hasil['total']:.0f}")
    request.session["flash_success"] = (
        f"{s['label']} {hasil['nomor']} tersimpan. "
        f"Total Rp {hasil['total']:,.0f}".replace(",", "."))
    return redirect(tujuan)


def retur_penjualan(request):
    return _transaksi_index(request, "penjualan_retur")


@require_POST
def retur_penjualan_save(request):
    return _transaksi_save(request, "penjualan_retur")


def pembelian(request):
    return _transaksi_index(request, "pembelian")


@require_POST
def pembelian_save(request):
    return _transaksi_save(request, "pembelian")


def retur_pembelian(request):
    return _transaksi_index(request, "pembelian_retur")


@require_POST
def retur_pembelian_save(request):
    return _transaksi_save(request, "pembelian_retur")


def _waktu(nilai):
    """Parse waktu kiriman layar (jam PC kasir). None kalau tak masuk akal —
    pemanggil lalu memakai jam mesin ini, bukan menolak nota karena satu kolom."""
    teks = (nilai or "").strip().replace("Z", "")
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d"):
        try:
            return dt.datetime.strptime(teks, fmt)
        except ValueError:
            continue
    return None


def _tanpa_harga(request, rows):
    """Buang kolom uang yang dicabut dari user ini. Penjagaannya di server —
    membuangnya di Vue hanya kosmetik (lihat useHiddenData.js)."""
    buang = _hidden_fields(request)
    if not buang:
        return rows
    return [{k: v for k, v in r.items() if k not in buang} for r in rows]


def _label(rows, kunci, nama, kode):
    """Nama untuk sebuah kode. Divisi & pegawai datang dari akun, jadi layar
    hanya menampilkannya — dan kode mentah tak berarti apa pun bagi kasir."""
    kode = (kode or "").strip()
    for r in rows:
        if (r.get(kunci) or "").strip() == kode:
            return r.get(nama) or ""
    return ""


def cari_barang_json(request):
    """Pencarian barang tanpa memuat ulang halaman.

    Sebelumnya kotak cari memakai router.get, yang berarti satu kunjungan Inertia
    penuh — seluruh prop layar dibangun ulang hanya untuk mengganti daftar hasil.
    Di layar kasir yang dipakai puluhan kali per nota, itu terasa lambat.
    """
    profile = _active()
    if not profile:
        return JsonResponse({"rows": [], "error": CONN_ERROR})
    kode = (request.GET.get("kode") or "").strip()
    try:
        if kode:  # jalur pemindai: kode persis, satu hasil, langsung dipakai
            b = pj.barang_persis(profile, kode)
            return JsonResponse(
                {"rows": _tanpa_harga(request, [b] if b else []), "persis": True})
        rows = pj.cari_barang(profile, request.GET.get("cari") or "")
        return JsonResponse({"rows": _tanpa_harga(request, rows)})
    except pyodbc.Error as exc:
        return JsonResponse({"rows": [], "error": mssql.friendly_error(exc, "Gagal mencari barang")})


def satuan_json(request):
    """Satuan-satuan sebuah barang, untuk mengganti satuan di baris keranjang.

    Dimuat saat kotak satuan disentuh, bukan saat barang ditambahkan: mengambil
    daftar ini tiap kali barang masuk berarti satu round-trip tambahan PER
    BARANG, dan di profil WAN round-trip-lah biayanya, bukan besar datanya.
    Mengganti satuan jarang terjadi; memindainya tidak.
    """
    profile = _active()
    if not profile:
        return JsonResponse({"rows": [], "error": CONN_ERROR})
    try:
        rows = pj.satuan_barang(profile, request.GET.get("kd_barang") or "")
        return JsonResponse({"rows": _tanpa_harga(request, rows)})
    except pyodbc.Error as exc:
        return JsonResponse(
            {"rows": [], "error": mssql.friendly_error(exc, "Gagal membaca satuan")})


def cari_customer_json(request):
    """Pencarian pelanggan tanpa memuat ulang halaman — 9.367 baris tak layak
    jadi dropdown."""
    profile = _active()
    if not profile:
        return JsonResponse({"rows": [], "error": CONN_ERROR})
    try:
        return JsonResponse(
            {"rows": pj.cari_customer(profile, request.GET.get("cari") or "")})
    except pyodbc.Error as exc:
        return JsonResponse(
            {"rows": [], "error": mssql.friendly_error(exc, "Gagal mencari pelanggan")})


def order_json(request):
    """Daftar order terbuka, atau isi satu order kalau `no_order` diberikan."""
    profile = _active()
    if not profile:
        return JsonResponse({"rows": [], "error": CONN_ERROR})
    no_order = (request.GET.get("no_order") or "").strip()
    try:
        if no_order:
            return JsonResponse({"order": pj.baca_order(profile, no_order)})
        return JsonResponse({"rows": pj.daftar_order(profile)})
    except pyodbc.Error as exc:
        return JsonResponse(
            {"rows": [], "error": mssql.friendly_error(exc, "Gagal membaca order")})


def nota_cetak(request, no_transaksi):
    """Faktur siap cetak untuk Epson LX-310.

    Dot matrix 9-pin: yang dicetak dengan benar adalah TEKS monospace pada lebar
    kolom tetap, bukan tata letak grafis. Halaman ini sengaja polos — satu
    kolom monospace 40 karakter, tanpa warna dan tanpa bingkai — supaya driver
    Windows LX-310 mengeluarkannya apa adanya dan cepat, alih-alih merender
    grafis baris demi baris.
    """
    profile = _active()
    nota = pj.baca_nota(profile, no_transaksi) if profile else None
    if not nota:
        request.session["flash_error"] = f"Nota {no_transaksi} tidak ditemukan."
        return redirect("/kasir/penjualan")
    return render(request, "Kasir/NotaCetak", props={"nota": nota})

"""Self-check untuk logika margin & whitelist status (money/security path)."""
from apps.master_data.services import _margin, _STATUS_TABLES


def test_margin_markup_atas_modal():
    # markup 25%: jual 12500 atas modal 10000
    assert _margin(12500, 10000) == 25.0
    # rugi (jual < modal) -> negatif
    assert _margin(8000, 10000) == -20.0
    # modal 0 / tak valid -> 0 (hindari bagi nol)
    assert _margin(12500, 0) == 0.0
    assert _margin(12500, None) == 0.0


def test_status_table_whitelist():
    # hanya 3 tabel yang boleh di-update statusnya
    assert _STATUS_TABLES == {"m_barang", "m_barang_divisi", "m_barang_satuan"}

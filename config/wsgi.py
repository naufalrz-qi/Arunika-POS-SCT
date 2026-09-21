import os

from django.core.wsgi import get_wsgi_application

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

application = get_wsgi_application()

# Scheduler in-process: hanya jalan saat server serving (wsgi di-load oleh
# runserver/waitress, TIDAK oleh migrate/shell/dll). Idempotent + fail-safe.
try:
    from apps.core.scheduler import start_scheduler

    start_scheduler()
except Exception:  # noqa: BLE001 — jangan gagalkan boot server gara-gara scheduler
    import logging

    logging.getLogger(__name__).exception("Gagal memulai scheduler snapshot harga")

# Catat mode laporan Arunika saat ia BERUBAH antar-restart.
#
# `ARUNIKA_LAPORAN` dibaca sekali saat impor `views`, jadi nilai yang berlaku
# adalah nilai saat proses mulai — tak ada momen lain yang bisa dicatat. Yang
# berarti karena itu bukan "sekarang menyala", melainkan "kapan ia berpindah",
# dan itulah satu-satunya pertanyaan yang selama ini tak bisa dijawab siapa pun.
#
# Hanya saat BERUBAH: restart-loop akan membanjiri Riwayat Operasi dengan baris
# identik sampai perpindahan yang sungguhan tak bisa ditemukan lagi — aturan
# sunyi yang sama dengan job sinkronisasi.
try:
    from apps.core.models import SyncLog, log_sync
    from apps.monitoring import views as _views

    _mode = "on" if _views.LAPORAN_ARUNIKA else "off"
    _lama = (SyncLog.objects.filter(feature="mode_arunika")
             .values_list("mode", flat=True).first())
    if _lama != _mode:
        log_sync(None, feature="mode_arunika", mode=_mode, src=None, dst=None,
                 compared=0, applied=0, username="(sistem)")
except Exception:  # noqa: BLE001 — sebuah baris log tak boleh menggagalkan boot
    import logging

    logging.getLogger(__name__).exception("Gagal mencatat mode laporan Arunika")

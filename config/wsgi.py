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

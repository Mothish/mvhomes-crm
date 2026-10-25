import sqlite3

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone


class Command(BaseCommand):
    help = "Create a consistent copy of the database in BACKUP_DIR and keep the last BACKUP_KEEP copies. Run daily from cron."

    def handle(self, *args, **options):
        backup_dir = settings.BACKUP_DIR
        backup_dir.mkdir(parents=True, exist_ok=True)
        target = backup_dir / f"mvhomes-{timezone.localtime():%Y%m%d-%H%M%S}.sqlite3"
        src = sqlite3.connect(settings.DATABASES["default"]["NAME"])
        dst = sqlite3.connect(target)
        with dst:
            src.backup(dst)
        src.close()
        dst.close()
        target.chmod(0o600)
        backups = sorted(backup_dir.glob("mvhomes-*.sqlite3"))
        for old in backups[: -settings.BACKUP_KEEP]:
            old.unlink()
        self.stdout.write(self.style.SUCCESS(f"Backup written to {target}"))

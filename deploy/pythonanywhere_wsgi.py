# PythonAnywhere WSGI config. pythonanywhere_setup.sh fills in __USERNAME__ and __APP_DIR__
# and copies this over /var/www/<username>_pythonanywhere_com_wsgi.py
import os
import sys

APP_DIR = "__APP_DIR__"
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
os.environ.setdefault("DJANGO_DEBUG", "0")
os.environ.setdefault("DJANGO_ALLOWED_HOSTS", "__USERNAME__.pythonanywhere.com")
os.environ.setdefault("DJANGO_CSRF_TRUSTED_ORIGINS", "https://__USERNAME__.pythonanywhere.com")
os.environ.setdefault("DJANGO_HTTPS", "1")
os.environ.setdefault("DEMO_MODE", "1")

from django.core.wsgi import get_wsgi_application  # noqa: E402

application = get_wsgi_application()

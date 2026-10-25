#!/usr/bin/env bash
# Run once in a PythonAnywhere Bash console, from the project folder:  bash deploy/pythonanywhere_setup.sh
set -euo pipefail

PYTHON="${PYTHON:-python3.11}"
APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
DOMAIN="${USER}.pythonanywhere.com"
cd "$APP_DIR"

echo "==> Creating virtualenv"
[[ -d .venv ]] || $PYTHON -m venv .venv
.venv/bin/pip install --upgrade pip -q
.venv/bin/pip install -r requirements.txt -q

export DJANGO_DEBUG=0 DJANGO_ALLOWED_HOSTS="$DOMAIN"
echo "==> Database + static files"
.venv/bin/python manage.py migrate --noinput
.venv/bin/python manage.py collectstatic --noinput -v 0
if [[ -z "$(.venv/bin/python manage.py shell -c 'from crm.models import Lead; print(Lead.objects.exists() or "")')" ]]; then
  echo "==> Loading demo data (takes ~15 seconds)"
  .venv/bin/python manage.py seed_demo
fi

WSGI="${WSGI_DIR:-/var/www}/${USER//./_}_pythonanywhere_com_wsgi.py"
sed -e "s|__USERNAME__|$USER|g" -e "s|__APP_DIR__|$APP_DIR|g" deploy/pythonanywhere_wsgi.py > /tmp/mvhomes_wsgi.py
if [[ -f "$WSGI" ]]; then
  cp /tmp/mvhomes_wsgi.py "$WSGI"
  echo "==> WSGI file updated: $WSGI"
else
  echo "==> Web app not created yet. After creating it (Web tab > Manual configuration > Python 3.11), run this script again."
fi

cat <<EOF

Next, on the Web tab:
  Virtualenv:   $APP_DIR/.venv
  Static files: URL /static/  ->  Directory $APP_DIR/staticfiles
  Force HTTPS:  enabled
  Then press the green Reload button and open https://$DOMAIN/
EOF

#!/usr/bin/env bash
# One-time setup on a fresh Ubuntu 22.04/24.04 server. Run from the project folder: sudo bash deploy/setup_server.sh
set -euo pipefail

APP_DIR=/opt/mvhomes
APP_USER=mvhomes

apt-get update
apt-get install -y python3 python3-venv python3-pip nginx sqlite3 rsync

id -u "$APP_USER" >/dev/null 2>&1 || useradd --system --home "$APP_DIR" --shell /usr/sbin/nologin "$APP_USER"
mkdir -p "$APP_DIR"
rsync -a --exclude .venv --exclude __pycache__ --exclude staticfiles --exclude backups --exclude .secret_key ./ "$APP_DIR"/

if [[ ! -f /etc/mvhomes.env ]]; then
  cp "$APP_DIR/deploy/mvhomes.env.example" /etc/mvhomes.env
  sed -i "s|replace-with-a-long-random-string|$(python3 -c 'import secrets; print(secrets.token_urlsafe(50))')|" /etc/mvhomes.env
  PUBLIC_IP=$(curl -s https://api.ipify.org || hostname -I | awk '{print $1}')
  sed -i "s|^DJANGO_ALLOWED_HOSTS=.*|DJANGO_ALLOWED_HOSTS=$PUBLIC_IP,localhost,127.0.0.1|" /etc/mvhomes.env
  sed -i "s|^DJANGO_CSRF_TRUSTED_ORIGINS=.*|DJANGO_CSRF_TRUSTED_ORIGINS=http://$PUBLIC_IP|" /etc/mvhomes.env
  chmod 600 /etc/mvhomes.env
fi

cd "$APP_DIR"
python3 -m venv .venv
.venv/bin/pip install --upgrade pip -q
.venv/bin/pip install -r requirements.txt -q
set -a; source /etc/mvhomes.env; set +a
.venv/bin/python manage.py migrate --noinput
.venv/bin/python manage.py collectstatic --noinput -v 0
[[ -n "$(.venv/bin/python manage.py shell -c 'from crm.models import Lead; print(Lead.objects.exists() or "")')" ]] \
  || .venv/bin/python manage.py seed_demo
chown -R "$APP_USER:$APP_USER" "$APP_DIR"

cp deploy/mvhomes.service /etc/systemd/system/mvhomes.service
cp deploy/nginx-mvhomes.conf /etc/nginx/sites-available/mvhomes
ln -sf /etc/nginx/sites-available/mvhomes /etc/nginx/sites-enabled/mvhomes
rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl daemon-reload
systemctl enable --now mvhomes
systemctl restart nginx

# Daily database backup at 02:30
echo "30 2 * * * $APP_USER cd $APP_DIR && set -a && . /etc/mvhomes.env && set +a && .venv/bin/python manage.py backup_db >/dev/null 2>&1" \
  > /etc/cron.d/mvhomes-backup

echo
echo "MV Homes CRM is running. Open: http://$(grep ^DJANGO_ALLOWED_HOSTS /etc/mvhomes.env | cut -d= -f2 | cut -d, -f1)/"

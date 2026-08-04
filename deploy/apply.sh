#!/bin/bash
# Install the server-side operational files from this repo onto the production
# host. Idempotent -- safe to re-run. Must run as root on the VPS.
#
#   cd /var/www/iprm && git pull && sudo ./deploy/apply.sh
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STAMP="$(date +%Y%m%d-%H%M%S)"

# install_file <src> <dst> <mode> -- backs up only when content actually differs.
install_file() {
    local src="$1" dst="$2" mode="$3"
    if [ -f "$dst" ] && cmp -s "$src" "$dst"; then
        echo "unchanged:  $dst"
        return 0
    fi
    if [ -f "$dst" ]; then
        cp -a "$dst" "$dst.bak-$STAMP"
        echo "backed up:  $dst.bak-$STAMP"
    fi
    install -D -m "$mode" "$src" "$dst"
    echo "installed:  $dst"
}

install_file "$REPO_DIR/nginx/snippets/iprm-app.conf"        /etc/nginx/snippets/iprm-app.conf                   644
install_file "$REPO_DIR/nginx/iprm.conf"                     /etc/nginx/conf.d/iprm.conf                        644
install_file "$REPO_DIR/systemd/nginx.service.d-restart.conf" /etc/systemd/system/nginx.service.d/restart.conf   644
install_file "$REPO_DIR/systemd/iprm-watchdog.service"       /etc/systemd/system/iprm-watchdog.service           644
install_file "$REPO_DIR/systemd/iprm-watchdog.timer"         /etc/systemd/system/iprm-watchdog.timer             644
install_file "$REPO_DIR/watchdog/iprm-healthcheck.sh"        /usr/local/bin/iprm-healthcheck.sh                  755
install_file "$REPO_DIR/watchdog/iprm-alert.py"              /usr/local/bin/iprm-alert.py                        755

echo '--- verifying ---'
nginx -t
systemctl daemon-reload
systemctl reload nginx
systemctl enable --now iprm-watchdog.timer

echo '--- state ---'
systemctl is-active nginx iprm iprm-watchdog.timer
systemctl list-timers iprm-watchdog.timer --no-pager | head -3

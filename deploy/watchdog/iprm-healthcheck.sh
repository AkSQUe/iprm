#!/bin/bash
# Health check + conservative self-heal for the IPRM site.
#
# Runs from iprm-watchdog.timer. Probes the site through nginx on loopback; if it
# does not answer, performs the one repair that is known to be safe for the
# observed symptom, re-probes, and mails the admins (rate-limited).
#
# Deliberately does NOT auto-repair 5xx: that means nginx is healthy and the
# application is at fault, and iprm.service already carries Restart=always.
# Restarting things on 5xx would only add flapping on top of a real bug.
set -uo pipefail

URL='https://iprm.space/'
RESOLVE='iprm.space:443:127.0.0.1'
STATE_DIR='/var/lib/iprm-watchdog'
FAIL_FLAG="$STATE_DIR/failing"
ALERT_FLAG="$STATE_DIR/last-alert"
ALERT_COOLDOWN=3600
ALERT_SCRIPT='/usr/local/bin/iprm-alert.py'
TAG='iprm-watchdog'

mkdir -p "$STATE_DIR"

log() { logger -t "$TAG" -- "$*"; }

probe() {
    local out
    # curl already prints 000 on connection failure, so do NOT add a fallback
    # echo on non-zero exit -- that concatenates into "000000" and stops the
    # "$code = 000" branch below from ever matching.
    out=$(curl -sk --max-time 10 --resolve "$RESOLVE" \
        -o /dev/null -w '%{http_code}' "$URL" 2>/dev/null)
    printf '%s' "${out:-000}"
}

# alert <subject> <body> -- best effort, never fatal, at most one per cooldown.
alert() {
    local subject="$1" body="$2" age
    if [ -f "$ALERT_FLAG" ]; then
        age=$(( $(date +%s) - $(stat -c %Y "$ALERT_FLAG") ))
        if [ "$age" -lt "$ALERT_COOLDOWN" ]; then
            log "alert suppressed (${age}s into ${ALERT_COOLDOWN}s cooldown)"
            return 0
        fi
    fi
    if [ -x "$ALERT_SCRIPT" ] && printf '%s\n' "$body" | timeout 60 "$ALERT_SCRIPT" "$subject"; then
        touch "$ALERT_FLAG"
        log 'alert e-mail sent'
    else
        log 'alert e-mail FAILED (condition is still recorded in this journal)'
    fi
    return 0
}

context() {
    printf 'host: %s\ntime: %s\nnginx: %s   iprm: %s\n\n--- nginx (last 20) ---\n%s\n\n--- iprm (last 20) ---\n%s\n' \
        "$(hostname)" "$(date -Is)" \
        "$(systemctl is-active nginx)" "$(systemctl is-active iprm)" \
        "$(journalctl -u nginx -n 20 --no-pager 2>/dev/null)" \
        "$(journalctl -u iprm -n 20 --no-pager 2>/dev/null)"
}

code=$(probe)

if [ "$code" = '200' ]; then
    if [ -f "$FAIL_FLAG" ]; then
        log 'recovered: site answers 200 again'
        rm -f "$FAIL_FLAG"
    fi
    exit 0
fi

log "health check FAILED (http=$code)"
touch "$FAIL_FLAG"

if ! systemctl is-active --quiet nginx; then
    action='nginx was not running -> systemctl start nginx'
    log "$action"
    systemctl start nginx
elif [ "$code" = '000' ]; then
    action='nginx running but not answering -> systemctl restart nginx'
    log "$action"
    systemctl restart nginx
else
    action="http=$code -- application fault, no automatic repair attempted"
    log "$action"
fi

sleep 5
after=$(probe)

if [ "$after" = '200' ]; then
    log "self-heal SUCCEEDED (http=$after)"
    rm -f "$FAIL_FLAG"
    alert "site recovered automatically (was http=$code)" \
"The IPRM site failed a health check and was repaired automatically.

  first probe  : HTTP $code
  action taken : $action
  after repair : HTTP $after

$(context)"
else
    log "self-heal FAILED (http=$after) -- site still down"
    alert "SITE DOWN (http=$after)" \
"The IPRM site is DOWN and automatic repair did not fix it.
Manual intervention required.

  first probe  : HTTP $code
  action taken : $action
  after repair : HTTP $after

$(context)"
fi

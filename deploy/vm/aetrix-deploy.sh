#!/usr/bin/env bash
# Aetrix V5.5 — VM-side release management.
#
# Runs as root on arm-free-1 (invoked through `sudo -n`). Every release lives in
# its own directory under /opt/aetrix/releases and is selected by the
# /opt/aetrix/current symlink, swapped atomically with `mv -Tf`. Persistent data
# (/opt/aetrix/shared) is never inside a release, so activating or rolling back
# an application release cannot touch documents, logs or configuration.
#
#   aetrix-deploy.sh install  <release-id> <tarball>
#   aetrix-deploy.sh activate <release-id> [--no-restart]
#   aetrix-deploy.sh rollback
#   aetrix-deploy.sh status
#   aetrix-deploy.sh releases
#
# Exit codes: 0 success, 1 usage/validation error, 2 health check failed
# (the previous release is restored before exiting 2).
set -euo pipefail

ROOT=/opt/aetrix
RELEASES="$ROOT/releases"
CURRENT="$ROOT/current"
SHARED="$ROOT/shared"
STATE="$ROOT/deploy"
API_UNIT=aetrix-api
HEALTH_URL=http://127.0.0.1:8000/health
READY_URL=http://127.0.0.1:8000/ready
HEALTH_TIMEOUT_SECONDS=${HEALTH_TIMEOUT_SECONDS:-60}

log() { printf '[aetrix-deploy] %s\n' "$*"; }
die() { printf '[aetrix-deploy] ERROR: %s\n' "$*" >&2; exit 1; }

require_root() {
  [ "$(id -u)" -eq 0 ] || die "must run as root (use sudo)"
}

health() {
  # /health proves the process answers; /ready proves the database is reachable.
  local health_code ready_code
  health_code=$(curl -sS -o /dev/null -w '%{http_code}' --max-time 3 "$HEALTH_URL" 2>/dev/null || echo 000)
  ready_code=$(curl -sS -o /dev/null -w '%{http_code}' --max-time 5 "$READY_URL" 2>/dev/null || echo 000)
  log "health=$health_code ready=$ready_code"
  [ "$health_code" = "200" ] && [ "$ready_code" = "200" ]
}

wait_healthy() {
  local deadline=$((SECONDS + HEALTH_TIMEOUT_SECONDS))
  while [ "$SECONDS" -lt "$deadline" ]; do
    if health; then return 0; fi
    sleep 3
  done
  return 1
}

point_current() {
  local rid=$1
  [ -d "$RELEASES/$rid" ] || die "release not found: $rid"
  ln -sfn "$RELEASES/$rid" "$CURRENT.new"
  mv -Tf "$CURRENT.new" "$CURRENT"          # atomic rename over the symlink
  log "current -> $rid"
}

current_release() {
  if [ -L "$CURRENT" ]; then basename "$(readlink -f "$CURRENT")"; else echo ""; fi
}

cmd_install() {
  require_root
  local rid=$1 tarball=$2 dir
  [ -f "$tarball" ] || die "tarball not found: $tarball"
  dir="$RELEASES/$rid"
  if [ -e "$dir" ]; then die "release directory already exists: $dir"; fi

  log "extracting $rid"
  install -d -m 755 "$dir"
  tar -xzf "$tarball" -C "$dir" --strip-components=1
  [ -f "$dir/app/main.py" ] || die "artifact does not contain app/main.py"

  log "creating virtual environment"
  python3 -m venv "$dir/.venv"
  "$dir/.venv/bin/pip" install --quiet --upgrade pip >/dev/null
  log "installing dependencies (this is the slow step)"
  "$dir/.venv/bin/pip" install --quiet --no-cache-dir "$dir"
  [ -x "$dir/.venv/bin/aetrix-worker" ] || die "worker entry point missing"
  [ -x "$dir/.venv/bin/uvicorn" ] || die "uvicorn missing"

  chown -R aetrix:aetrix "$dir"
  echo "$rid" > "$STATE/staged"
  log "installed $rid"
}

cmd_activate() {
  require_root
  local rid=$1 restart=${2:-}
  [ -d "$RELEASES/$rid" ] || die "release not found: $rid"
  local previous; previous=$(current_release)

  if [ -n "$previous" ] && [ "$previous" != "$rid" ]; then
    echo "$previous" > "$STATE/previous"
  fi

  point_current "$rid"
  if [ "$restart" = "--no-restart" ]; then
    log "symlink switched; services not restarted"
    return 0
  fi

  systemctl restart "$API_UNIT"
  if wait_healthy; then
    echo "$rid" > "$STATE/active"
    log "activated $rid"
    return 0
  fi

  log "health check failed for $rid"
  journalctl -u "$API_UNIT" -n 40 --no-pager || true
  if [ -n "$previous" ] && [ "$previous" != "$rid" ]; then
    log "rolling back to $previous"
    point_current "$previous"
    systemctl restart "$API_UNIT"
    if wait_healthy; then
      echo "$previous" > "$STATE/active"
      log "rollback to $previous succeeded"
    else
      log "ROLLBACK FAILED — both releases are unhealthy; manual attention required"
    fi
  else
    log "no previous release to roll back to"
  fi
  exit 2
}

cmd_rollback() {
  require_root
  local previous
  previous=$(cat "$STATE/previous" 2>/dev/null || true)
  [ -n "$previous" ] || die "no previous release recorded in $STATE/previous"
  [ -d "$RELEASES/$previous" ] || die "previous release directory missing: $previous"
  local doomed; doomed=$(current_release)
  log "rolling back $doomed -> $previous (database is NOT downgraded)"
  point_current "$previous"
  systemctl restart "$API_UNIT"
  if wait_healthy; then
    echo "$previous" > "$STATE/active"
    # Allow rolling forward again by recording what we just left.
    [ -n "$doomed" ] && echo "$doomed" > "$STATE/previous"
    log "rollback complete"
    return 0
  fi
  log "ROLLBACK HEALTH CHECK FAILED"
  exit 2
}

cmd_status() {
  echo "release   : $(current_release)"
  echo "active    : $(cat "$STATE/active" 2>/dev/null || echo unknown)"
  echo "previous  : $(cat "$STATE/previous" 2>/dev/null || echo none)"
  echo "api       : $(systemctl is-active "$API_UNIT" 2>/dev/null || true) / $(systemctl is-enabled "$API_UNIT" 2>/dev/null || true)"
  echo "worker    : $(systemctl is-active aetrix-worker 2>/dev/null || true) / $(systemctl is-enabled aetrix-worker 2>/dev/null || true)"
  echo "funnel    : $(tailscale funnel status 2>/dev/null | head -3 | tr '\n' ' ')"
  echo -n "health    : "; health || true
  echo "disk      : $(df -h /opt/aetrix | tail -1 | awk '{print $4" free of "$2}')"
}

cmd_releases() {
  local rid
  for rid in $(ls -1 "$RELEASES" 2>/dev/null | sort); do
    [ -d "$RELEASES/$rid" ] || continue
    local marker=""
    [ "$rid" = "$(current_release)" ] && marker="  <- current"
    printf '%s%s\n' "$rid" "$marker"
  done
}

case "${1:-}" in
  install)  shift; cmd_install "$@" ;;
  activate) shift; cmd_activate "$@" ;;
  rollback) cmd_rollback ;;
  status)   cmd_status ;;
  releases) cmd_releases ;;
  *) sed -n '2,20p' "$0"; exit 1 ;;
esac

#!/usr/bin/env bash
set -uo pipefail

ROOT_DIR="/home/pwnb0t/g/trailcam-automation"
CONFIG_PATH="${TRAILCAM_CONFIG:-$ROOT_DIR/config.yaml}"
LOCK_PATH="$ROOT_DIR/out/state/trailcam-sync.lock"
LOG_DIR="$ROOT_DIR/out/logs"
STATS_PATH="$ROOT_DIR/out/state/retry_stats.json"
SYNC_OVERRIDE="$ROOT_DIR/scripts/sync.sh"
SYNC_FALLBACK="$ROOT_DIR/scripts/sync.example.sh"

# Retry policy for one scheduled run.
MAX_ATTEMPTS="${TRAILCAM_SYNC_MAX_ATTEMPTS:-5}"
RETRY_DELAY_S="${TRAILCAM_SYNC_RETRY_DELAY_S:-300}"

is_truthy() {
  case "${1:-}" in
    1|true|TRUE|yes|YES|on|ON) return 0 ;;
    *) return 1 ;;
  esac
}

send_outcome_email() {
  local subject="$1"
  local body="$2"

  TRAILCAM_CONFIG_PATH="$CONFIG_PATH" \
  TRAILCAM_EMAIL_SUBJECT="$subject" \
  TRAILCAM_EMAIL_BODY="$body" \
  /usr/bin/env python3 - <<'PY'
import os
from src.config import load_config
from src.notify.email_notifier import EmailNotifier

cfg = load_config(os.environ["TRAILCAM_CONFIG_PATH"])
notifier = EmailNotifier(cfg.alerts.email)
notifier.send_message(
    subject=os.environ["TRAILCAM_EMAIL_SUBJECT"],
    body=os.environ["TRAILCAM_EMAIL_BODY"],
)
PY
}

record_retry_stats() {
  local result="$1"         # success|failure
  local attempts_used="$2"  # integer >= 1
  local max_attempts="$3"   # integer >= 1
  local exit_code="$4"      # integer exit code
  local host
  host="$(hostname -s 2>/dev/null || hostname || echo unknown-host)"
  local ts
  ts="$(date -Is)"

  TRAILCAM_RETRY_STATS_PATH="$STATS_PATH" \
  TRAILCAM_RETRY_HOST="$host" \
  TRAILCAM_RETRY_RESULT="$result" \
  TRAILCAM_RETRY_ATTEMPTS_USED="$attempts_used" \
  TRAILCAM_RETRY_MAX_ATTEMPTS="$max_attempts" \
  TRAILCAM_RETRY_EXIT_CODE="$exit_code" \
  TRAILCAM_RETRY_TIMESTAMP="$ts" \
  /usr/bin/env python3 - <<'PY'
import json
import os
from pathlib import Path

path = Path(os.environ["TRAILCAM_RETRY_STATS_PATH"])
path.parent.mkdir(parents=True, exist_ok=True)

host = os.environ["TRAILCAM_RETRY_HOST"]
result = os.environ["TRAILCAM_RETRY_RESULT"].strip().lower()
attempts_used = max(1, int(os.environ["TRAILCAM_RETRY_ATTEMPTS_USED"]))
max_attempts = max(1, int(os.environ["TRAILCAM_RETRY_MAX_ATTEMPTS"]))
exit_code = int(os.environ["TRAILCAM_RETRY_EXIT_CODE"])
ts = os.environ["TRAILCAM_RETRY_TIMESTAMP"]
retry_attempts = max(0, attempts_used - 1)

raw = {}
if path.exists():
    try:
        raw = json.loads(path.read_text("utf-8"))
    except Exception:
        raw = {}

if not isinstance(raw, dict):
    raw = {}
raw.setdefault("version", 1)
hosts = raw.setdefault("hosts", {})
if not isinstance(hosts, dict):
    hosts = {}
    raw["hosts"] = hosts

h = hosts.setdefault(host, {})
if not isinstance(h, dict):
    h = {}
    hosts[host] = h

h["runs_total"] = int(h.get("runs_total", 0)) + 1
if result == "success":
    h["runs_succeeded"] = int(h.get("runs_succeeded", 0)) + 1
else:
    h["runs_failed"] = int(h.get("runs_failed", 0)) + 1
if retry_attempts > 0:
    h["runs_with_retry"] = int(h.get("runs_with_retry", 0)) + 1
h["retry_attempts_total"] = int(h.get("retry_attempts_total", 0)) + retry_attempts

h["last_run_at"] = ts
h["last_result"] = result
h["last_attempts_used"] = attempts_used
h["last_max_attempts"] = max_attempts
h["last_exit_code"] = exit_code

path.write_text(json.dumps(raw, indent=2, sort_keys=True) + "\n", "utf-8")
PY
}

mkdir -p "$(dirname "$LOCK_PATH")" "$LOG_DIR"
cd "$ROOT_DIR"

if ! [[ "$MAX_ATTEMPTS" =~ ^[0-9]+$ ]] || [ "$MAX_ATTEMPTS" -lt 1 ]; then
  echo "invalid TRAILCAM_SYNC_MAX_ATTEMPTS=$MAX_ATTEMPTS (must be >=1 integer)" >&2
  exit 2
fi
if ! [[ "$RETRY_DELAY_S" =~ ^[0-9]+$ ]]; then
  echo "invalid TRAILCAM_SYNC_RETRY_DELAY_S=$RETRY_DELAY_S (must be integer seconds)" >&2
  exit 2
fi

exec 9>"$LOCK_PATH"
if ! /usr/bin/flock -n 9; then
  echo "trailcam sync already running; skipping this scheduled invocation"
  exit 0
fi

attempt=1
rc=1
while [ "$attempt" -le "$MAX_ATTEMPTS" ]; do
  ts="$(date -Is)"
  echo "[$ts] trailcam sync attempt $attempt/$MAX_ATTEMPTS"

  if [ -f "$SYNC_OVERRIDE" ]; then
    SYNC_SCRIPT="$SYNC_OVERRIDE"
  else
    SYNC_SCRIPT="$SYNC_FALLBACK"
  fi
  if [ ! -f "$SYNC_SCRIPT" ]; then
    echo "sync launcher not found: $SYNC_SCRIPT" >&2
    exit 2
  fi

  TRAILCAM_CONFIG="$CONFIG_PATH" /usr/bin/env bash "$SYNC_SCRIPT"
  rc=$?
  if [ "$rc" -eq 0 ]; then
    ts="$(date -Is)"
    echo "[$ts] trailcam sync succeeded on attempt $attempt/$MAX_ATTEMPTS"

    record_retry_stats "success" "$attempt" "$MAX_ATTEMPTS" "$rc"

    if is_truthy "${TRAILCAM_SCHEDULED:-0}"; then
      host="$(hostname -s 2>/dev/null || hostname || echo unknown-host)"
      subject="Trailcam Scheduled Sync SUCCESS"
      body="Host: ${host}
When: ${ts}
Result: success
Attempts used: ${attempt}/${MAX_ATTEMPTS}
Config: ${CONFIG_PATH}"
      if ! send_outcome_email "$subject" "$body"; then
        echo "[$ts] WARNING: success email send failed" >&2
      fi
    fi
    exit 0
  fi

  ts="$(date -Is)"
  echo "[$ts] trailcam sync failed on attempt $attempt/$MAX_ATTEMPTS (exit=$rc)"
  if [ "$attempt" -lt "$MAX_ATTEMPTS" ]; then
    echo "[$ts] retrying in ${RETRY_DELAY_S}s"
    sleep "$RETRY_DELAY_S"
  fi
  attempt=$((attempt + 1))
done

ts="$(date -Is)"
echo "[$ts] trailcam sync failed after $MAX_ATTEMPTS attempts"
record_retry_stats "failure" "$MAX_ATTEMPTS" "$MAX_ATTEMPTS" "$rc"

if is_truthy "${TRAILCAM_SCHEDULED:-0}"; then
  host="$(hostname -s 2>/dev/null || hostname || echo unknown-host)"
  subject="Trailcam Scheduled Sync FINAL FAILURE"
  body="Host: ${host}
When: ${ts}
Result: final failure
Attempts used: ${MAX_ATTEMPTS}/${MAX_ATTEMPTS}
Last exit code: ${rc}
Config: ${CONFIG_PATH}"
  if ! send_outcome_email "$subject" "$body"; then
    echo "[$ts] WARNING: failure email send failed" >&2
  fi
fi

exit "$rc"

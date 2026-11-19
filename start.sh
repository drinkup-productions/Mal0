#!/bin/sh
# Starts MalO on Linux. Ensures the Letta app server, the broker token, and the app.
#   --no-app       services only, no window (exit once they are up)
#   --headless     app in server mode, no window, no tray
#   --port=N       letta server port (default 4500)
#   --broker-port=N  broker port warning threshold (default 8766)

say() { printf '[%s] %s\n' "$(date +%H:%M:%S)" "$*"; }
die() { say "ERROR: $*" >&2; exit 1; }

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$ROOT" || die "cannot cd to $ROOT"

PORT=4500
BROKER_PORT=8766
NOAPP=0
HEADLESS=0
for a in "$@"; do
    case "$a" in
        --no-app) NOAPP=1 ;;
        --headless) HEADLESS=1 ;;
        --port=*) PORT=${a#--port=} ;;
        --broker-port=*) BROKER_PORT=${a#--broker-port=} ;;
        *) say "ignoring unknown flag: $a" ;;
    esac
done

DATA=${MALO_DATA:-$HOME/MalOAvatar}
CFG="$DATA/config.json"

PY=$(command -v python3 || command -v python)

port_open() {
    (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null && { exec 3>&-; return 0; }
    return 1
}

have_token() {
    [ -f "$CFG" ] || return 1
    "$PY" - "$CFG" <<'EOF'
import json, sys
try:
    tok = (json.load(open(sys.argv[1])) or {}).get("broker_token")
except Exception:
    tok = None
sys.exit(0 if tok else 1)
EOF
}

# ---- preflight -----------------------------------------------------------
say "preflight"
[ -n "$PY" ] || die "python3 not on PATH"
command -v node >/dev/null 2>&1 || die "node not on PATH (see docs/REQUIREMENTS-LINUX.md)"
if ! command -v letta >/dev/null 2>&1; then
    say "WARNING: letta CLI missing - the legacy letta backend will not work" \
        "(pip install -U letta-ai); starting anyway"
fi
say "node $(node -v), $("$PY" -V 2>&1)"

# ---- letta server --------------------------------------------------------
if ! command -v letta >/dev/null 2>&1; then
    say "skipping letta server (CLI not installed)"
elif port_open "$PORT"; then
    say "letta server already on $PORT"
else
    say "starting letta server on $PORT"
    mkdir -p "$DATA" || die "cannot create data dir $DATA"
    LOG="$DATA/letta-server.log"
    nohup letta server --backend local --listen "ws://127.0.0.1:$PORT" \
        >"$LOG" 2>"$LOG.err" &
    i=0
    while ! port_open "$PORT"; do
        i=$((i + 1))
        [ $i -ge 80 ] && { say "server did not bind $PORT - see $LOG" >&2; tail -15 "$LOG.err" 2>/dev/null; exit 1; }
        sleep 0.5
    done
    say "server up"
fi

# ---- broker token --------------------------------------------------------
if have_token; then
    say "broker token present"
else
    say "no broker token - pairing this machine"
    "$PY" -m malo --pair desktop || die "pairing failed"
    have_token || die "pairing did not write a token (see $CFG)"
fi

CFG_BROKER_PORT=$("$PY" - "$CFG" <<'EOF' 2>/dev/null
import json, sys
try:
    print((json.load(open(sys.argv[1])) or {}).get("broker_port") or "")
except Exception:
    pass
EOF
)
if [ -n "$CFG_BROKER_PORT" ] && [ "$CFG_BROKER_PORT" != "$BROKER_PORT" ]; then
    say "config broker_port is $CFG_BROKER_PORT, script uses $BROKER_PORT"
fi

if port_open "$BROKER_PORT"; then
    say "broker already on $BROKER_PORT"
else
    say "broker will start with the app on $BROKER_PORT"
fi

# ---- app -----------------------------------------------------------------
if [ "$NOAPP" = 1 ]; then
    say "services ready - exiting (--no-app)"
    exit 0
fi

if [ "$HEADLESS" = 1 ]; then
    say "starting headless"
    exec "$PY" -m malo --broker --server
else
    say "starting app"
    exec "$PY" -m malo --broker
fi

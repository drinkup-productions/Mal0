#!/bin/sh
# Restarts MalO on Linux. Asks the running app to shut down gracefully first
# (quit flag, which triggers its shutdown sequence), waits for it to exit,
# then relaunches start.sh detached. Usage: restart.sh [delay_seconds]

DELAY=${1:-3}
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
DATA=${MALO_DATA:-$HOME/MalOAvatar}
FLAG="$DATA/quit.flag"

say() { printf '[%s] %s\n' "$(date +%H:%M:%S)" "$*"; }

pids() { pgrep -f 'python.*-m malo\b' 2>/dev/null; }

procs=$(pids)
if [ -z "$procs" ]; then
    say "no running MalO process found"
else
    say "asking to shut down gracefully: $(echo $procs | tr '\n' ' ')"
    mkdir -p "$DATA" 2>/dev/null || true
    : >"$FLAG" 2>/dev/null || true
    i=0
    while [ "$(pids)" ] && [ $i -lt 240 ]; do
        sleep 0.5
        i=$((i + 1))
    done
    left=$(pids)
    if [ -n "$left" ]; then
        say "graceful shutdown timed out (120s) - forcing: $(echo $left | tr '\n' ' ')"
        kill -9 $left 2>/dev/null || true
        sleep 2
    fi
fi
rm -f "$FLAG" 2>/dev/null || true

say "relaunching in ${DELAY}s"
sleep "$DELAY"

mkdir -p "$DATA" 2>/dev/null || true
nohup /bin/sh "$ROOT/start.sh" >>"$DATA/restart.log" 2>&1 &
disown 2>/dev/null || true
say "relaunched (log: $DATA/restart.log)"

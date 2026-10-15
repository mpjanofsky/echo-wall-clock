#!/bin/bash
CLOCK_DIR="${CLOCK_DIR:-$HOME/clock}"
# Send one step to the running session and show what was transmitted (from the JSON log).
LOG=$(ls -t $CLOCK_DIR/logs/*-piecho.jsonl | head -1)
BEFORE=$(wc -l < "$LOG")
echo "$1" | sudo tee $CLOCK_DIR/control.fifo >/dev/null
sleep 1.5
tail -n +$((BEFORE+1)) "$LOG" | python3 -c "
import sys, json, datetime
for l in sys.stdin:
    r = json.loads(l)
    t = datetime.datetime.fromtimestamp(r[\"t\"]).strftime(\"%H:%M:%S\")
    print(t, r[\"kind\"], r.get(\"what\", r.get(\"decoded\", \"\")))"
systemctl is-active --quiet clocksession || echo "!! session ended"

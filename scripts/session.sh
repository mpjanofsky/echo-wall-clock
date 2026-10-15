#!/bin/bash
CLOCK_DIR="${CLOCK_DIR:-$HOME/clock}"
# Hold an interactive Echo session with the clock. Send steps with: scripts/cmd.sh "timer:A:3"
sudo systemctl stop clocksession 2>/dev/null; sudo systemctl reset-failed clocksession 2>/dev/null
rm -f $CLOCK_DIR/control.fifo
sudo systemd-run --unit=clocksession --quiet --working-directory=$CLOCK_DIR \
  -p StandardOutput=truncate:$CLOCK_DIR/session.txt -p StandardError=file:$CLOCK_DIR/session.txt \
  /usr/bin/python3 -u $CLOCK_DIR/pi_echo.py --fresh --listen 3600 --control $CLOCK_DIR/control.fifo
echo started

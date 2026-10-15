#!/bin/bash
CLOCK_DIR="${CLOCK_DIR:-$HOME/clock}"
# Start the fake clock + HCI capture as transient services (survive SSH disconnects).
cd $CLOCK_DIR
sudo systemctl stop fakeclock fakeclock-btmon 2>/dev/null
sudo systemctl reset-failed fakeclock fakeclock-btmon 2>/dev/null
STAMP=$(date +%H%M%S)
sudo systemd-run --unit=fakeclock-btmon --quiet /usr/bin/btmon -w $CLOCK_DIR/capture-$STAMP.btsnoop
sudo systemd-run --unit=fakeclock --quiet --working-directory=$CLOCK_DIR \
  -p StandardOutput=file:$CLOCK_DIR/live-$STAMP.txt -p StandardError=file:$CLOCK_DIR/live-$STAMP.txt \
  /usr/bin/python3 -u $CLOCK_DIR/fake_clock.py
ln -sf live-$STAMP.txt $CLOCK_DIR/live.txt
echo "started $STAMP"

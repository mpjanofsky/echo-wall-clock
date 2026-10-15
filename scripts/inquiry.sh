#!/bin/bash
# Capture the clock EIR during a Classic inquiry. Usage: inquiry.sh <seconds>
set -u
SECS=${1:-60}
OUT=$CLOCK_DIR/inquiry-$(date +%H%M%S)
sudo btmgmt power on >/dev/null
sudo btmon -w $OUT.btsnoop >/dev/null 2>&1 &
sleep 1
END=$((SECONDS+SECS))
while [ $SECONDS -lt $END ]; do
  sudo timeout 12 btmgmt find -b 2>&1 | grep -i -A8 "cc:9e:a2\|wallclk" | tee -a $OUT.txt
done
sudo pkill btmon
sleep 1
sudo btmon -r $OUT.btsnoop 2>/dev/null > $OUT.decoded.txt
echo "DONE $OUT"

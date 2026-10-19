# Quick start (Raspberry Pi)

Tested on a Raspberry Pi 3B (Raspberry Pi OS, BlueZ 5.82). Any Linux box with BlueZ and a Classic
Bluetooth adapter should work.

1. `sudo apt install python3-dbus python3-gi rfkill` and `sudo rfkill unblock bluetooth`.
2. On a Pi 3, turn Wi-Fi off (`sudo nmcli radio wifi off`) and use Ethernet. Classic BT is flaky
   while the shared radio is also doing Wi-Fi.
3. Put the clock in pairing mode: hold its button until the center LED flashes amber. Pair and connect
   in one run, because the window closes quickly:

   ```bash
   sudo python3 pi_echo.py --address CC:9E:A2:xx:xx:xx --fresh --timer 3 --listen 200
   ```

   Find the address with `sudo btmgmt find -b` or in your phone's Bluetooth scan (name `EchoWallClk...`, or `EWCMickeyMouse...` on the Mickey Mouse Edition).
   Use `--tz` for your time zone. The clock shows local wall-clock time and ignores the offset.
4. Afterwards the clock stays bonded. Reconnect any time without pairing mode by omitting `--fresh`.
   The clock only talks to one partner, so pairing it to an Echo again takes it away from the Pi.

For interactive control, run `pi_echo.py --control /path/to/fifo --listen 3600` and write lines such as
`timer:A:3`, `delete:A`, `alarm:X:5`, `reminder:X:5`, `state:timers=active`, `indicator:on`, or `sync`
to the FIFO. [`scripts/`](../scripts) wraps this; it expects the repo in `~/clock`, or set `CLOCK_DIR`.

To see the bytes without any hardware, run `python3 examples/set_timer.py`.

# Capturing a real Echo, or your own clock's identity

## Your clock's `Discover.Response`

`pi_echo.py` logs every frame to `logs/<timestamp>-piecho.jsonl`. Extract the clock's reply:

```bash
python3 tools/extract_response.py logs/<timestamp>-piecho.jsonl clock_discover_response.bin
```

The file contains the clock's serial number (DSN) and device token. **Never commit or share it.**
`.gitignore` excludes `*.bin` and `logs/` for this reason.

## Recording what a real Echo sends

`fake_clock.py` copies the clock's Bluetooth identity (name, class of device, EIR, SDP records), so a
real Echo can pair with the Pi as if it were the clock, and logs every byte it sends:

1. Take the real clock's batteries out so the Echo cannot find it.
2. `sudo python3 fake_clock.py --response clock_discover_response.bin` (without `--response` the Echo
   gets no reply and stops after `Discover`).
3. In the Alexa app, add a Wall Clock. Pair the Echo, then use voice to set, pause, resume, cancel and
   stop timers.
4. For raw HCI traces, run `sudo btmon -w capture.btsnoop` alongside. `scripts/start.sh` does both.

Logs include your Echo's address; scrub before sharing.

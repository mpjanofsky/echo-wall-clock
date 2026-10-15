# Troubleshooting

1. BLE scanners find nothing — it's Classic only.
2. macOS: the process aborts with exit 134 if the app running it has no Bluetooth permission → grant it in System Settings, or run from an app that has it.
3. Messages with a messageId/scope are silently ignored.
4. Pi not connectable → link supervision timeout right after pairing.
5. Pi 3 Wi-Fi on → flaky Classic BT.
6. BlueZ hands profile fds over non-blocking → `setblocking(True)` before recv.
7. Raspberry Pi OS soft-blocks Bluetooth (rfkill) by default.

See also [PROTOCOL.md §2](../PROTOCOL.md) for the pairing and call-back behavior behind most of these.

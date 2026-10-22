# Validation

## 2026-10-22

| Check | Result |
| --- | --- |
| Connected adapter | USB VID/PID `1a86:55d9`; CH348Q version `0x90`; macOS location `0x00100000` |
| Native SDK build | Xcode 27.1, DriverKit 27 SDK, unsigned DriverKit extension and installer; `arm64` and `x86_64` |
| Host protocol tests | PASS with AddressSanitizer and UndefinedBehaviorSanitizer: UART configuration, all eight channels, binary RX/TX framing, truncated/malformed records, status parsing |
| Host serial-ring tests | PASS with AddressSanitizer and UndefinedBehaviorSanitizer: wrap, empty/full, capacity, invalid indices, 10000 iterations |
| Normal automatic signing | PASS: Apple Development signature; Apple-issued DriverKit USB/Serial and installer profiles; the driver signature is restricted to `1a86:55d9` |
| Signature/profile preflight | PASS: bundle IDs, team, profile expiry, and required entitlements verified |
| Native driver activation | NOT RUN: signed installer is ready; macOS activation is the next acceptance step |
| Eight native serial services | NOT VERIFIED: the driver has not been activated; no `IOSerialBSDClient` acceptance evidence exists |
| UART electrical and data-path acceptance | NOT RUN: attached boards were excluded from this task |
| Hot-plug, restart, sleep and uninstall | NOT RUN: require native activation first |

The earlier PTY experiment was stopped and its GizOS changes and local port aliases were removed. PTY evidence is excluded from native-driver acceptance.

## Remaining acceptance

1. Sign using a valid Apple account and profiles granting the declared DriverKit USB/Serial entitlements.
2. Activate the extension through the included installer and confirm its enabled state with `systemextensionsctl list`.
3. Observe eight real `IOSerialBSDClient` services and matching `/dev/cu.CH348*` nodes with `scripts/verify-ports.py`, without sending any board commands.
4. Unplug/reconnect the adapter and restart macOS; verify that eight native ports return without relaunching a bridge process.
5. Separately authorize loopback or attached-board testing to qualify concurrent data paths, UART settings, modem pins, disconnect with pending I/O, and RX/TX backpressure.

Until these checks pass, the repository is a buildable driver implementation, not a tested driver release.

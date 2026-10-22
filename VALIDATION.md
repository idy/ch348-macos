# Validation

## 2026-10-22

| Check | Result |
| --- | --- |
| Connected adapter | USB VID/PID `1a86:55d9`; CH348Q version `0x90`; macOS location `0x00100000` |
| Native SDK build | PASS: Xcode 27.1, DriverKit 27 SDK, signed and unsigned DriverKit extension and installer; `arm64` and `x86_64` |
| Host protocol tests | PASS with AddressSanitizer and UndefinedBehaviorSanitizer: UART configuration, all eight channels, binary RX/TX framing, truncated/malformed records, status parsing |
| Host serial-ring tests | PASS with AddressSanitizer and UndefinedBehaviorSanitizer: wrap, empty/full, capacity, invalid indices, 10000 iterations |
| Normal development signing | PASS: Apple Development signatures and Apple-issued profiles containing this Mac; explicit operator approval for Apple's development-only USB wildcard entitlement |
| Signature/profile checks | PASS: bundle IDs, team, expiry, device membership, USB/Serial grants, and CH348-only matching verified; production template and development signing remain separate |
| Native driver activation | PASS: version `0.1.0/3` is `activated enabled`, the driver process runs, and IOKit reports `UsbExclusiveOwner=CH348Device` |
| Eight native serial services | PASS: eight real `IOSerialBSDClient` services and eight `/dev/cu.CH34800100000-0` through `-7` nodes, plus corresponding `/dev/tty.*` nodes |
| UART electrical and data-path acceptance | NOT RUN: attached boards were excluded from this task |
| Hot-plug, restart, sleep and uninstall | NOT RUN: require native activation first |

The earlier PTY experiment was stopped and its GizOS changes and local port aliases were removed. PTY evidence is excluded from native-driver acceptance.

`scripts/verify-ports.py` completed with exit code 0 and `count: 8`. It performs only native IOKit enumeration; no serial endpoint was opened and no attached-board command was sent. The current installation is a local development build, not a notarized distributable release. SIP and system extension validation remain enabled.

Two signing integration defects were corrected during installation: the installer must reside in global `/Applications`, and the concrete **My Mac (DriverKit)** destination must be provisioned before the generic app build. Apple's development USB entitlement must match its profile (`idVendor=*`); a restricted USB entitlement cannot be substituted into that development profile. The driver matching dictionary and runtime device check continue to accept only `1a86:55d9`.

## Remaining acceptance

1. Unplug/reconnect the adapter and restart macOS; verify that eight native ports return without relaunching a bridge process.
2. Separately authorize loopback or attached-board testing to qualify concurrent data paths, UART settings, modem pins, disconnect with pending I/O, and RX/TX backpressure.
3. Qualify Intel runtime and other supported macOS versions.
4. Obtain the appropriate production transport grants and distribution signing/notarization before publishing installable releases for other machines.

Native enumeration acceptance is complete. The remaining checks are outside the completed eight-port enumeration scope and prevent a production-qualified driver release.

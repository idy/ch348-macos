# Validation

## 2026-11-20

Development-signed build `0.1.1/15` was installed over SSH with another team's
bundle IDs and Apple-issued profiles containing the target Mac. The installer
submitted activation without an `NSApplication` session. After the operator's
initial macOS approval, two CH348 devices published all 16 native channels.
Subsequent replacement required USB device reenumeration: registration of a new
extension alone left the connected ports served by the previous build. The
runtime build check confirmed build 15 on all 16 channels after reenumeration.
SIP and system extension validation remained enabled. This was a software
reenumeration, not a physical hot-plug or whole-Mac restart qualification.

An unmodified application's pySerial 3.5 write/read path exposed `EINVAL` while
updating a read timeout. On macOS, the custom-baud path temporarily submits
38400 through `tcsetattr`, then restores the requested rate through
`IOSSIOSPEED`. Skipping identical settings in build 14 did not fix this path.
Build 15 validates and retains only the latest 12-byte configuration per active
UART while its write is outstanding. It applies that configuration after both
USB and UART completion, before publishing consumption or sending another
packet. Close discards pending settings; retired clients remain busy; failed
configuration terminates the transport. The existing TX watchdog remains in
effect, with no polling worker or unbounded configuration queue.

On the target, the original immediate write/read reproducer passed 10 times.
Three unchanged application serial callers completed 48 open/configure/read
timeout/close checks across the 16 channels. A further 800 one-byte carriage
return write/read API cycles passed at 115200, 460800, 921600, 1500000 and
2000000 baud. Driver counters recorded 810 submitted and completed bytes,
including the reproducer. These are API and transmit-completion checks: no
valid board reply was received. They do not establish a physical loopback,
end-to-end UART data integrity, sustained throughput, BREAK/modem-pin behavior,
or flashing readiness. No firmware was flashed or user data erased.

All 56 Python tests passed with the universal build present. The protocol/ring
executables and production-function configuration, completion and teardown
harnesses passed with AddressSanitizer and UndefinedBehaviorSanitizer. New
cases cover latest-setting coalescing, invalid-input rejection, both completion
orders, close, retired ownership, independent UARTs, stopping and command
failure. Default/custom bundle-ID packaging was verified earlier in this
change; build 15 was rebuilt universally with the custom ID. Hosted CI had no
runner for the first two attempts, so those cancelled jobs are not passing
build evidence.

## 2026-11-04

Host regression checks now compile the production receive, queue teardown, command recovery, and status-dispatch method bodies with memory-only substitutes for DriverKit services. The real C protocol and ring helpers are linked where used. AddressSanitizer and UndefinedBehaviorSanitizer are enabled. These harnesses check control flow and data handling, not the SDK ABI, native RPC scheduling, or physical hardware.

The pre-fix receive harness reproduced 18 failures across the overflow subcases: one full UART ring stopped the shared device and prevented later records from reaching other ports. The fixed path reports the affected port's overrun, preserves its buffered data and indices, continues delivery to healthy ports, rearms the USB receive, and resumes that UART after its client drains the ring. Invalid ring state and malformed USB transfers remain fatal. Queue-lifetime tests cover retired writes and replacement rings in both completion orders; command tests cover one-time stall clearing without command replay; status tests cover modem delta preservation, zero interrupt identifiers, four-byte modem-read replies, and whole-transfer validation before callbacks.

An activation-query regression captures the query emitted by the production activation method for each of the eight UARTs. It checks the target source tag and register address, then constructs the simulated readback from that actual request and verifies that only the intended port receives the modem snapshot. This covers request routing in addition to the independent response-parser tests.

`scripts/test.sh` passes all 44 Python tests and both C test executables. Protocol tests include in-place transmit payloads, mixed-length status records, truncation boundaries, and modem-bit merge combinations. A separate deterministic 100,000-input protocol stress check passed under both sanitizers. The unsigned `0.1.1` / build `13` installer and extension build successfully for both `arm64` and `x86_64`.

No driver was installed or activated during these checks, and no serial port was opened or UART payload transmitted. Physical overflow, continuous multi-port traffic, modem-pin behavior, USB fault recovery, and sleep/wake remain unqualified for this revision. The watchdog's clock accounting excludes system sleep; that change alone does not establish complete suspend/resume support.

## 2026-11-02

The icon update is installed as development-signed build `0.1.0/12`. Both `/Applications/CH348.app` and the new system-managed driver extension contain the checked-in `CH348.icns` resource and declare it through `CFBundleIconFile`. Signature validation passed, and `systemextensionsctl list` reports build 12 as `activated enabled` with the display name `CH348 Serial Driver`. The app icon resolves correctly through macOS; the icon in System Settings has not been visually verified.

An activation request using build 11 kept the existing same-version extension, so the project build number was advanced to 12. Immediately after activation, the connected adapter remained served by build 11 while that extension was marked `terminating for upgrade via delegate`; the runtime build check correctly reported the mismatch. After the operator physically disconnected and reconnected the adapter, `verify-ports.py --expected-build 12 --statistics` passed: all eight native ports at USB location `0x02110000` report build 12, the serving process runs from the new system-managed extension, and the old build 11 registration is gone. This verifies one physical reconnect and runtime replacement; UART communication, restart, sleep/wake and multiple adapters were not retested. No UART payload was transmitted during this installation check.

The unmodified H2Loader CLI, built from Firmwares' pinned GizOS revision `d8ff4db46ea8670dafdf5970077f7e36a1b5d20f`, enumerated all eight CH348 channels with `--no-ble scan`. UART7 responded with `board=bk7258_v3_202405`, `target=bk7258`, active role `h2loader`, version `0.7.0`. UART0–UART6 and the other three serial endpoints timed out with `H2_PAL_ERR_TIMEOUT` (`-6`) at the default ten-second probe timeout. The scan exited successfully, but only UART7 completed the status exchange; the timeouts do not establish whether other channels have connected boards. Unique device identifiers and raw scan output remain outside tracked files.

The default Bluetooth-inclusive `scan` aborted with `SIGABRT` before producing results. The macOS crash report identifies TCC enforcement for a missing `NSBluetoothAlwaysUsageDescription` in the CLI. The serial-only scan used the CLI's existing `--no-ble` option; no CLI source or firmware was modified.

## 2026-10-22

| Check | Result |
| --- | --- |
| Adapter and host | USB `1a86:55d9`, CH348Q version `0x90`, USB location `0x20131000`; Apple Silicon Mac, macOS 26.6.2 |
| Native SDK build | PASS: Xcode 27.1 and DriverKit 27 SDK; signed extension and installer compile for `arm64` and `x86_64` |
| Native activation and version | PASS: all eight live serial services report runtime build `0.1.0/11`, checked with `verify-ports.py --expected-build 11` |
| Eight native serial ports | PASS: `/dev/cu.CH34820131000-0` through `-7`, eight real `IOSerialBSDClient` services and corresponding `/dev/tty.*` nodes |
| Native serial APIs | PASS: all eight ports open, configure as 8N1, and accept the macOS `IOSSIOSPEED` custom-baud ioctl |
| Raw UART0 receive | PASS at 460800/8N1: a five-second capture received 183 bytes, all readable text, including ESP-IDF `W (...) wifi:` log output |
| Operator channel-swap check | OPERATOR-REPORTED PASS: the same working ESP32-S3 board communicates on each of UART0–UART5; this is distinct from the independently captured checks below |
| Raw UART6 and UART7 receive | PASS at 460800/8N1: an eight-second concurrent capture received 214 readable text bytes from each port, including ESP-IDF logs |
| Bidirectional command communication | PASS on UART0, UART1, UART4, UART6 and UART7 using the unmodified H2Loader CLI and read-only `status`; UART4 required about 14 seconds, so a short timeout was insufficient |
| Concurrent UART6 and UART7 command exchange | PASS at 460800/8N1: independent CLI processes returned the expected, distinct ESP32-S3 board identities in 1.518 and 1.302 seconds respectively |
| Existing GUI client | PASS on UART6 and UART7: the unmodified H6 Batch Loader displays the attached boards' identities and active App versions and completes a subsequent status refresh on both |
| Repeated queue setup | PASS: raw capture opened and closed all eight ports at 115200, 460800 and 921600, followed by a successful application connection at 460800 |
| Protocol tests | PASS with ASan/UBSan: configuration, version-gated packet-upload initialization, eight-channel framing, and malformed/truncated records |
| Serial-ring tests | PASS with ASan/UBSan: physical buffer wrap, monotonic counters beyond the ring capacity, 10000 iterations, full/invalid states and `UINT32_MAX` rollover |
| Python checks | PASS: 11 cases covering signing validation, passive binary capture, and the binary-probe validator's partial I/O, corruption, extra-data and timeout cases; PTY fixtures qualify the test tool only |
| Development signing | PASS: Apple Development signatures and Apple-issued profiles containing this Mac; explicit operator approval for Apple's development USB wildcard grant; device matching remains CH348-only |
| Driver replacement | PASS: the current driver runs and publishes ports after replacing prior builds; registration alone was not used as evidence of the running build |
| Physical binary loopback | NOT RUN: no isolated loopback fixture was provided; successful protocol exchanges do not establish a 64 KiB binary loopback or sustained throughput |
| Physical hot-plug, restart, sleep and Intel runtime | NOT RUN |

No firmware was flashed, staged, installed or rebooted during communication validation. Board identities, complete logs, and other device details are retained outside the public repository. The installation uses local development signing, not a notarized distributable release. SIP and system extension validation remain enabled.

## Defects found and corrected

The original implementation mapped serial queues in `Start()`. The system then requested another set of queues when a client opened a port. The driver kept writing to the old data buffer: one failing capture contained 426 UART bytes, including 412 nonzero bytes at the USB side, while the application received 426 zero bytes. `ConnectQueues` now maps the actual buffers returned on each open, and `DisconnectQueues` releases the corresponding views. After the fix, UART0 delivers readable ESP-IDF logs at its actual 460800 baud and H6 Batch Loader completes a board-status exchange.

The original ring helper also wrapped the published producer/consumer counters at the ring capacity. The native interface uses monotonic 32-bit counters. Only physical addresses now wrap at the buffer size, and regression cases cover long-running indices and 32-bit overflow.

A separate disconnect crash was traced to cancelling a DriverKit timer with a null completion block. Cancellation now has a non-null handler and retains the timer's owned reference until that handler runs. The baud-rate hook invokes the local UART implementation, activation initializes both UART FIFOs and explicitly clears hardware flow control while preserving modem outputs, and CH348 silicon version 0x8a or later receives the vendor's independent packet-upload initialization. Numeric configuration-acknowledgement and transfer counters support diagnosis without storing UART payloads in IOKit.

Earlier H2Loader attempts timed out with the faulty receive queues. UART6 and UART7 also initially had no received data. With known-working boards kept on those channels, both raw capture and concurrent status exchanges succeeded on the already-installed build 11, without a further driver change. The exact cause of those earlier two-channel timeouts has not been isolated; no channel-specific workaround is claimed.

Additional attempts, including repeat CLI checks after the successful UART6/UART7 exchange, reported `UNAVAILABLE` while H6 Batch Loader held the ports exclusively. Those are contention results, not communication failures or successful reconnect tests. The GUI continued to show the same UART6/UART7 boards connected.

The GUI also retained a previous identity for UART5, but a fresh status request on that row timed out. That pending request was cancelled, leaving UART6 and UART7 connected. The cached UART5 identity is excluded from independent acceptance; only the UART6/UART7 board fixtures were fixed for this final check.

## Reproduce

```sh
scripts/test.sh
python3 scripts/verify-ports.py --expected-build 11 --statistics
python3 scripts/serial-probe.py
python3 scripts/serial-probe.py --port /dev/cu.CH34820131000-6 \
    --port /dev/cu.CH34820131000-7 --baud 460800 --read-seconds 8
```

Close an existing serial client's connection before running the API probe, since serial applications may hold an exclusive lock. Statistics are numeric snapshots published at service start and serial close; no UART payload is stored in the registry.

A physical loopback remains an optional separate qualification using `serial-probe.py --port <actual-path> --loopback`. It sends arbitrary binary data and requires the selected channel's board to be disconnected and its TX/RX pins joined. No loopback pass is claimed here.

## Remaining acceptance

1. Independently record every channel with a fixed fixture, then qualify simultaneous sustained traffic, flow control, modem outputs and RX/TX backpressure. Current results are smoke tests and include the operator-reported UART0–UART5 check.
2. Physically unplug/reconnect the adapter, restart macOS and test sleep/wake. Confirm that all eight ports return without an installer or bridge process.
3. Qualify Intel runtime and other macOS versions.
4. Obtain production transport grants and distribution signing/notarization before publishing an installable release for other machines.

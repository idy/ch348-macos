# Validation

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
| Existing GUI client | PASS: the unmodified H6 Batch Loader connects on UART5, UART6 and UART7, displays the attached boards' identities and active App versions, and completes a subsequent status refresh |
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

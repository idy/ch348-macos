# CH348 macOS serial driver

[![Build and test](https://github.com/idy/ch348-macos/actions/workflows/ci.yml/badge.svg)](https://github.com/idy/ch348-macos/actions/workflows/ci.yml)

Native DriverKit driver for WCH CH348 USB to eight UART adapters (`1a86:55d9`). This project targets normal `IOSerialBSDClient` ports usable by existing POSIX serial clients, including H2Loader, without client modifications. It does not create PTYs or modify another application's device enumerator.

**Status: eight native serial ports are verified, with communication smoke-test evidence across UART0–UART7.** The operator tested UART0–UART5 by moving the same working ESP32-S3 board between channels. Independent tests on UART6 and UART7 receive readable ESP-IDF logs and complete concurrent, read-only H2Loader status exchanges at 460800/8N1. The unmodified H6 Batch Loader also connects through the native ports. See [current validation](VALIDATION.md) for the measured results and remaining qualification.

The extension and installer compile for both `arm64` and `x86_64`. Intel runtime, physical loopback, hot-plug, sleep, and reboot acceptance remain untested. Host protocol and ring-buffer tests pass with AddressSanitizer and UndefinedBehaviorSanitizer.

## Architecture

`CH348Device` matches the exact USB VID/PID, owns the complete device and its single multiplexed USB interface, and creates eight `CH348Port` child services through `IOService::Create`. Each port subclasses `IOUserSerial` and publishes its own serial service. Its `ConnectQueues` and `DisconnectQueues` hooks map and release the actual buffers selected when a client opens or closes the port. Ring indices are monotonic 32-bit counters; only physical buffer offsets are masked. The CH348 wire protocol belongs to `Protocol/`; the DriverKit classes use the same encoders and decoders tested on the host.

The device owns one asynchronous data receive request and one asynchronous status request. Outgoing data is scheduled fairly across active UARTs and advances the serial queue only after both the USB write and the UART-empty status complete. An uncompleted transfer has a three-second deadline. Disconnect aborts I/O and terminates the child services. A newly inserted matching device should be matched by macOS automatically after persistent driver activation; physical hot-plug behavior still needs qualification.

Callout names are `/dev/cu.CH348<usb-location>-0` through `-7`, with corresponding `/dev/tty.*` nodes. All eight names have been observed at USB locations `00100000` and `20131000`. Moving the adapter to another USB port can change the location component.

## Requirements

- macOS 14 or later and a full Xcode installation with the DriverKit SDK.
- [XcodeGen](https://github.com/yonaskolb/XcodeGen) to generate the Xcode project from `project.yml`.
- A paid Apple Developer team with DriverKit development, USB transport development, Serial family, and host System Extension installation entitlements in Apple-issued provisioning profiles. Distribution additionally requires Apple-approved device/vendor transport grants.

The bundle identifiers are `com.idy.ch348-macos` (installer) and `com.idy.ch348-macos.driver` (driver). `CH348_DEVELOPMENT_TEAM` selects the signing team when building. Development certificates alone do not grant DriverKit entitlements. Apple describes the application and profile requirements in [Requesting Entitlements for DriverKit Development](https://developer.apple.com/documentation/driverkit/requesting-entitlements-for-driverkit-development).

## Build and install

Run the host tests and build without signing:

```sh
scripts/test.sh
scripts/build.sh --unsigned
```

This produces `build/Build/Products/Debug/CH348.app`, containing the native `.dext`. The unsigned build is useful for compilation checks and cannot be treated as an installable driver.

For a local development installation, use Apple's documented development USB entitlement and explicitly opt in:

```sh
CH348_DEVELOPMENT_TEAM=YOUR_TEAM_ID scripts/build.sh --development
scripts/install.sh --development
```

`Driver/Development.entitlements` uses `idVendor=*` in the development signature, as required by [Apple's current DriverKit signing flow](https://developer.apple.com/forums/thread/809202). This grants a broader USB transport capability to the development process. The IOKit matching dictionary and the driver's own identity check both remain restricted to CH348 `1a86:55d9`. The installer rejects this signature unless `--development` is supplied. This mode is for registered development Macs, not a generally distributable release.

The signed build first provisions the concrete **My Mac (DriverKit)** destination, then embeds the extension into the installer. This ensures that the driver's profile includes the current Mac as well as the expected USB/Serial entitlements. Profiles that omit this Mac are rejected before installation.

For an appropriately approved non-development USB grant, keep `Driver/Driver.entitlements` and use:

```sh
CH348_DEVELOPMENT_TEAM=YOUR_TEAM_ID scripts/build.sh
scripts/install.sh
```

The installer script first validates the signatures, profile expiration, bundle IDs, signing teams, and required entitlements. It then copies the app to `/Applications/CH348.app` and requests activation using Apple's System Extensions framework. The global `/Applications` directory is required; macOS rejects activation from `~/Applications` with `OSSystemExtensionErrorDomain` code 3. If the script cannot write there, copy the signed app using Finder and open it. Complete any macOS approval prompt. Keep the app installed because it contains the registered extension. To remove the driver, open the app and choose **Uninstall**.

No script changes SIP, boot security, NVRAM, system extension developer mode, or USB device firmware. If normal signing or activation fails, resolve the reported account/profile/approval problem before proceeding.

## Verify eight native ports

After successful activation, connect one CH348 and run:

```sh
scripts/verify-ports.py
```

This queries `IOSerialBSDClient` through IOKit, prints the actual callout paths, and succeeds only when it finds eight CH348 ports. `--expected-build 11` also verifies the build actually serving every port; extension registration can finish while a previous driver process is still serving the connected device. `--statistics` includes counters snapshotted at service start and serial close. It never opens a UART or sends commands to an attached board. Existing serial applications should then enumerate the same native services; do not use the presence of a USB device or a successful build as proof of serial registration.

To exercise the native open and custom-baud APIs without transmitting payloads:

```sh
python3 scripts/serial-probe.py
```

To receive raw serial data without transmitting payloads, select the actual ports and baud rate:

```sh
python3 scripts/serial-probe.py --port /dev/cu.CH34820131000-6 \
    --port /dev/cu.CH34820131000-7 --baud 460800 --read-seconds 8
```

Selected ports are captured concurrently. The report includes byte counts and a SHA-256 digest; an idle port can legitimately return zero bytes. Add `--output-dir /path/to/private/captures` to retain binary captures for diagnosis. Close other clients first, since applications such as H6 Batch Loader hold exclusive connections. A busy-port result is not a failed UART exchange.

For a physical loopback, disconnect the selected UART from its board and connect **that same channel's TX to RX**. Use the actual path returned by enumeration:

```sh
python3 scripts/serial-probe.py --port /dev/cu.CH34820131000-0 --loopback
```

This opt-in test sends 64 KiB of binary data, compares every received byte, rejects missing/extra/corrupt bytes, and reports a SHA-256 digest. It must be used with the loopback fixture, because it deliberately transmits arbitrary binary data. The probe does not issue modem-control ioctls or board commands. An unsuccessful protocol handshake alone cannot distinguish a driver defect from UART configuration or board-side problems; inspect raw serial data and line-status counters as well.

UART settings implement 1200–6000000 baud, 5–8 data bits, one/two stop bits, and none/odd/even parity. Hardware flow control, programmable latency, and mark/space parity currently return `kIOReturnUnsupported`. CH348Q's UART4–UART7 have no DTR/RTS implementation and return unsupported for modem-output programming. Activation/deactivation preserve the modem pins; explicit modem-control requests for supported channels are implemented separately. These behaviors require hardware qualification before relying on them for production use.

## Protocol references

- [WCH CH348 product information](https://www.wch.cn/products/CH348.html).
- [WCH's Linux CH9344/CH348 driver](https://github.com/WCHSoftGroup/ch9344ser_linux).
- [Community Linux CH348 driver](https://github.com/xdarklight/ch348).
- [Apple SerialDriverKit](https://developer.apple.com/documentation/serialdriverkit).

The protocol implementation here is original code based on the observable packet format; the project does not vendor the GPL Linux drivers or Apple's SDK source.

## License

[MIT](LICENSE).

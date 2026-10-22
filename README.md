# CH348 macOS serial driver

[![Build and test](https://github.com/idy/ch348-macos/actions/workflows/ci.yml/badge.svg)](https://github.com/idy/ch348-macos/actions/workflows/ci.yml)

Native DriverKit driver for WCH CH348 USB to eight UART adapters (`1a86:55d9`). This project targets normal `IOSerialBSDClient` ports usable by existing POSIX serial clients, including H2Loader, without client modifications. It does not create PTYs or modify another application's device enumerator.

**Status: development build; not installed or hardware-qualified.** The DriverKit extension and installer compile for both `arm64` and `x86_64`. Protocol and ring-buffer tests pass with AddressSanitizer and UndefinedBehaviorSanitizer. Native enumeration and serial I/O still require a correctly provisioned installation and hardware acceptance. See [current validation](VALIDATION.md).

## Architecture

`CH348Device` matches the exact USB VID/PID, owns the complete device and its single multiplexed USB interface, and creates eight `CH348Port` child services through `IOService::Create`. Each port subclasses `IOUserSerial`, connects the system-provided RX/TX queues, and publishes its own serial service. The CH348 wire protocol belongs to `Protocol/`; the DriverKit classes use the same encoders and decoders tested on the host.

The device owns one asynchronous data receive request and one asynchronous status request. Outgoing data is scheduled fairly across active UARTs and advances the serial queue only after both the USB write and the UART-empty status complete. An uncompleted transfer has a three-second deadline. Disconnect aborts I/O and terminates the child services. A newly inserted matching device should be matched by macOS automatically after a successful persistent driver activation; hot-plug behavior remains unverified until that installation is available.

The intended callout names are `/dev/cu.CH348<usb-location>-0` through `-7`, with corresponding `/dev/tty.*` nodes. These names describe the implementation's requested naming, not observed hardware results.

## Requirements

- macOS 14 or later and a full Xcode installation with the DriverKit SDK.
- [XcodeGen](https://github.com/yonaskolb/XcodeGen) to generate the Xcode project from `project.yml`.
- An Apple Developer team with DriverKit, USB transport for `1a86:55d9`, Serial family, and host System Extension installation entitlements in Apple-issued provisioning profiles.

The bundle identifiers are `com.idy.ch348-macos` (installer) and `com.idy.ch348-macos.driver` (driver). `CH348_DEVELOPMENT_TEAM` selects the signing team when building. Development certificates alone do not grant DriverKit entitlements. Apple describes the application and profile requirements in [Requesting Entitlements for DriverKit Development](https://developer.apple.com/documentation/driverkit/requesting-entitlements-for-driverkit-development).

## Build and install

Run the host tests and build without signing:

```sh
scripts/test.sh
scripts/build.sh --unsigned
```

This produces `build/Build/Products/Debug/CH348.app`, containing the native `.dext`. The unsigned build is useful for compilation checks and cannot be treated as an installable driver.

After signing authorization is configured, build and install:

```sh
CH348_DEVELOPMENT_TEAM=YOUR_TEAM_ID scripts/build.sh
scripts/install.sh
```

The installer script first validates the signatures, profile expiration, bundle IDs, signing teams, and required entitlements. It then copies the app to `~/Applications/CH348.app` and requests activation using Apple's System Extensions framework. Complete any macOS approval prompt. Keep the app installed because it contains the registered extension. To remove the driver, open the app and choose **Uninstall**.

No script changes SIP, boot security, NVRAM, system extension developer mode, or USB device firmware. If normal signing or activation fails, resolve the reported account/profile/approval problem before proceeding.

## Verify eight native ports

After successful activation, connect one CH348 and run:

```sh
scripts/verify-ports.py
```

This queries `IOSerialBSDClient` through IOKit, prints the actual callout paths, and succeeds only when it finds eight CH348 ports. It never opens a UART or sends commands to an attached board. Existing serial applications should then enumerate the same native services; do not use the presence of a USB device or a successful build as proof of serial registration.

UART settings implement 1200–6000000 baud, 5–8 data bits, one/two stop bits, and none/odd/even parity. Hardware flow control, programmable latency, and mark/space parity currently return `kIOReturnUnsupported`. CH348Q's UART4–UART7 have no DTR/RTS implementation and return unsupported for modem-output programming. Activation/deactivation preserve the modem pins; explicit modem-control requests for supported channels are implemented separately. These behaviors require hardware qualification before relying on them for production use.

## Protocol references

- [WCH CH348 product information](https://www.wch.cn/products/CH348.html).
- [WCH's Linux CH9344/CH348 driver](https://github.com/WCHSoftGroup/ch9344ser_linux).
- [Community Linux CH348 driver](https://github.com/xdarklight/ch348).
- [Apple SerialDriverKit](https://developer.apple.com/documentation/serialdriverkit).

The protocol implementation here is original code based on the observable packet format; the project does not vendor the GPL Linux drivers or Apple's SDK source.

## License

[MIT](LICENSE).

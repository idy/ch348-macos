#!/usr/bin/env python3
"""Exercise native serial APIs, or a deliberately wired TX/RX loopback."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import fcntl
import glob
import hashlib
import json
import os
from pathlib import Path
import select
import struct
import sys
import termios
import time


def configure(fd, baud):
    settings = termios.tcgetattr(fd)
    settings[0] = settings[1] = settings[3] = 0
    settings[2] &= ~(termios.CSIZE | termios.PARENB | termios.CSTOPB |
                     termios.CCTS_OFLOW | termios.CRTS_IFLOW)
    settings[2] |= termios.CS8 | termios.CLOCAL | termios.CREAD
    settings[4] = settings[5] = termios.B9600
    settings[6][termios.VMIN] = settings[6][termios.VTIME] = 0
    termios.tcsetattr(fd, termios.TCSANOW, settings)
    # IOSSIOSPEED takes a native speed_t (unsigned long), including on arm64.
    fcntl.ioctl(fd, 0x80085402, struct.pack("L", baud))


def loopback(fd, size, timeout):
    expected = bytes(((i * 73) ^ (i >> 8) ^ 0xA5) & 255 for i in range(size))
    received = bytearray()
    written = 0
    deadline = time.monotonic() + timeout
    termios.tcflush(fd, termios.TCIFLUSH)
    while written < size or len(received) < size:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError(f"loopback timeout: wrote {written}, received {len(received)} of {size}")
        # Keep less than one system RX ring in flight, exercising ring wrap
        # over many windows without deliberately overrunning the receiver.
        pending = written - len(received)
        writable = [fd] if written < size and pending < 4096 else []
        readers, writers, _ = select.select([fd], writable, [], remaining)
        if fd in writers:
            try:
                written += os.write(fd, expected[written:written + min(1024, 4096 - pending)])
            except BlockingIOError:
                pass
        if fd in readers:
            try:
                data = os.read(fd, 8192)
            except BlockingIOError:
                continue
            start = len(received)
            if data != expected[start:start + len(data)]:
                raise ValueError(f"loopback data mismatch at or after byte {start}")
            received.extend(data)
    # Reject duplicated or delayed trailing data, rather than accepting only
    # the matching prefix of a corrupt receive stream.
    if select.select([fd], [], [], 0.05)[0] and os.read(fd, 8192):
        raise ValueError("unexpected bytes after the loopback payload")
    return {"transmitted_bytes": written, "received_bytes": len(received),
            "sha256": hashlib.sha256(received).hexdigest()}


def capture(fd, seconds):
    data = bytearray()
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        remaining = max(0, deadline - time.monotonic())
        if select.select([fd], [], [], remaining)[0]:
            try:
                chunk = os.read(fd, 65536)
            except BlockingIOError:
                continue
            if not chunk:
                raise OSError("serial endpoint closed during capture")
            data.extend(chunk)
            if len(data) > 16 * 1024 * 1024:
                raise ValueError("capture exceeded 16 MiB; use a shorter interval")
    return bytes(data)


def probe(port, args):
    result = {"port": port, "baud": args.baud, "format": "8N1",
              "mode": "physical-loopback" if args.loopback else
                      "passive-receive" if args.read_seconds else "native-api"}
    fd = None
    original = None
    try:
        fd = os.open(port, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        original = termios.tcgetattr(fd)
        configure(fd, args.baud)
        if args.loopback:
            result.update(loopback(fd, args.bytes, args.timeout))
        if args.read_seconds:
            termios.tcflush(fd, termios.TCIFLUSH)
            data = capture(fd, args.read_seconds)
            result.update(received_bytes=len(data), nonzero_bytes=sum(v != 0 for v in data),
                          ascii_bytes=sum(32 <= v < 127 or v in (9, 10, 13) for v in data),
                          sha256=hashlib.sha256(data).hexdigest(), hex_prefix=data[:32].hex())
            if args.output_dir:
                directory = Path(args.output_dir)
                directory.mkdir(parents=True, exist_ok=True)
                filename = f"{Path(port).name}-{args.baud}-{time.time_ns()}.bin"
                output = directory / filename
                with output.open("xb") as stream:
                    stream.write(data)
                result["capture_path"] = str(output.resolve())
        result["result"] = "PASS"
    except (OSError, ValueError, TimeoutError) as error:
        result.update(result="FAIL", error=str(error))
    finally:
        if fd is not None:
            if original is not None:
                try:
                    termios.tcsetattr(fd, termios.TCSANOW, original)
                except OSError as error:
                    result.update(result="FAIL", restore_error=str(error))
            os.close(fd)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", action="append", help="callout path; repeat for multiple ports")
    parser.add_argument("--baud", type=int, default=460800)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--loopback", action="store_true",
                      help="send binary data; requires a disconnected board and physical TX/RX jumper")
    mode.add_argument("--read-seconds", type=float, default=0,
                      help="passively receive raw bytes on all selected ports concurrently; send nothing")
    parser.add_argument("--output-dir", help="save passive captures as binary files in this directory")
    parser.add_argument("--bytes", type=int, default=65536)
    parser.add_argument("--timeout", type=float, default=10)
    args = parser.parse_args()
    if sys.platform != "darwin":
        parser.error("this probe uses macOS IOSSIOSPEED")
    if (not 1200 <= args.baud <= 6000000 or not 1 <= args.bytes <= 1048576 or
            args.timeout <= 0 or not 0 <= args.read_seconds <= 60):
        parser.error("invalid baud, payload size, or timeout")
    if args.loopback and not args.port:
        parser.error("--loopback requires an explicit --port with a physical TX/RX jumper")
    if args.output_dir and not args.read_seconds:
        parser.error("--output-dir requires --read-seconds")
    ports = args.port or sorted(glob.glob("/dev/cu.CH348*"))
    if not ports:
        parser.error("no CH348 callout ports found")
    if args.read_seconds:
        with ThreadPoolExecutor(max_workers=min(8, len(ports))) as pool:
            results = list(pool.map(lambda port: probe(port, args), ports))
    else:
        results = [probe(port, args) for port in ports]
    print(json.dumps(results, indent=2))
    return 0 if all(row["result"] == "PASS" for row in results) else 1


if __name__ == "__main__":
    sys.exit(main())

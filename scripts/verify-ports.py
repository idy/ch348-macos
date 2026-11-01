#!/usr/bin/env python3
"""Enumerate real IOSerialBSDClient callout ports without opening any UART."""
import argparse
import json
import plistlib
import re
import subprocess
import sys


def entries(value):
    if isinstance(value, dict):
        if "IOCalloutDevice" in value:
            yield value
        for child in value.values():
            yield from entries(child)
    elif isinstance(value, list):
        for child in value:
            yield from entries(child)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-build", type=int, help="also verify the build actually serving each port")
    parser.add_argument("--statistics", action="store_true", help="include driver counters from the last close")
    args = parser.parse_args()
    raw = subprocess.check_output(["ioreg", "-r", "-c", "IOSerialBSDClient", "-a", "-l"])
    services = plistlib.loads(raw) if raw.strip() else []
    ports = sorted({entry["IOCalloutDevice"] for entry in entries(services)
                    if entry["IOCalloutDevice"].startswith("/dev/cu.CH348")})
    devices = {}
    errors = []
    if not ports:
        errors.append("No native CH348 serial ports found")
    for port in ports:
        match = re.fullmatch(r"/dev/cu\.CH348([0-9a-f]{8})-([0-7])", port)
        if match is None:
            errors.append(f"Unexpected CH348 port name: {port}")
            continue
        location, channel = match.groups()
        devices.setdefault(location, []).append(int(channel))
    for location, channels in devices.items():
        missing = sorted(set(range(8)) - set(channels))
        if missing:
            errors.append(f"CH348 at USB location {location} is missing channels: {missing}")

    raw = subprocess.check_output(["ioreg", "-r", "-c", "CH348Port", "-a", "-l"])
    drivers = plistlib.loads(raw) if raw.strip() else []
    builds = {}
    statistics = {}
    for driver in drivers:
        for child in entries(driver):
            port = child["IOCalloutDevice"]
            if port not in ports:
                continue
            builds[port] = driver.get("CH348DriverBuild")
            statistics[port] = {key: value for key, value in driver.items()
                                if key.startswith("CH348")}
    result = {"native_serial_ports": ports, "count": len(ports),
              "devices": devices, "runtime_builds": builds}
    if args.statistics:
        result["statistics"] = statistics
    if args.expected_build is not None:
        result["expected_build"] = args.expected_build
        for port in ports:
            if builds.get(port) != args.expected_build:
                errors.append(f"Runtime build mismatch for {port}: expected "
                              f"{args.expected_build}, found {builds.get(port)}")
    result["errors"] = errors
    print(json.dumps(result, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())

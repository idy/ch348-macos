#!/usr/bin/env python3
"""Enumerate real IOSerialBSDClient callout ports without opening any UART."""
import argparse
import json
import plistlib
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


parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--expected-build", type=int, help="also verify the build actually serving each port")
parser.add_argument("--statistics", action="store_true", help="include driver counters from the last close")
args = parser.parse_args()
raw = subprocess.check_output(["ioreg", "-r", "-c", "IOSerialBSDClient", "-a", "-l"])
services = plistlib.loads(raw) if raw.strip() else []
ports = sorted({entry["IOCalloutDevice"] for entry in entries(services)
                if entry["IOCalloutDevice"].startswith("/dev/cu.CH348")})
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
result = {"native_serial_ports": ports, "count": len(ports), "runtime_builds": builds}
if args.statistics:
    result["statistics"] = statistics
valid = len(ports) == 8
if args.expected_build is not None:
    valid = valid and all(builds.get(port) == args.expected_build for port in ports)
    result["expected_build"] = args.expected_build
print(json.dumps(result, indent=2))
sys.exit(0 if valid else 1)

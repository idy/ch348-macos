#!/usr/bin/env python3
"""Enumerate real IOSerialBSDClient callout ports without opening any UART."""
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


raw = subprocess.check_output(["ioreg", "-r", "-c", "IOSerialBSDClient", "-a", "-l"])
ports = sorted({entry["IOCalloutDevice"] for entry in entries(plistlib.loads(raw))
                if entry["IOCalloutDevice"].startswith("/dev/cu.CH348")})
print(json.dumps({"native_serial_ports": ports, "count": len(ports)}, indent=2))
sys.exit(0 if len(ports) == 8 else 1)

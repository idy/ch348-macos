#!/usr/bin/env python3
"""Validate Apple-issued profiles before offering a DriverKit installation."""
from datetime import datetime, timezone
from pathlib import Path
import fnmatch
import json
import plistlib
import subprocess
import sys


def grants_ch348(items, allow_development_wildcard=False):
    if not isinstance(items, list):
        return False
    for item in items:
        if not isinstance(item, dict):
            continue
        vendor = item.get("idVendor")
        if vendor != 0x1A86 and not (allow_development_wildcard and vendor == "*"):
            continue
        if item.get("idProduct", 0x55D9) == 0x55D9:
            return True
    return False


def permits_device(profile, identifier):
    return profile.get("ProvisionsAllDevices") is True or identifier in profile.get("ProvisionedDevices", [])


def validate(app):
    hardware = json.loads(subprocess.check_output(
        ["system_profiler", "SPHardwareDataType", "-json"]))["SPHardwareDataType"][0]
    device = hardware.get("provisioning_UDID", hardware.get("platform_UUID"))
    if not device:
        raise ValueError("Cannot determine this Mac's provisioning identifier")
    extension = app / "Contents/Library/SystemExtensions/com.idy.ch348-macos.driver.dext"
    for bundle, required in [
        (app, {"com.apple.developer.system-extension.install": True}),
        (extension, {"com.apple.developer.driverkit": True,
                     "com.apple.developer.driverkit.family.serial": True}),
    ]:
        subprocess.run(["codesign", "--verify", "--strict", str(bundle)], check=True)
        profile = bundle / ("embedded.provisionprofile" if bundle == extension
                            else "Contents/embedded.provisionprofile")
        if not profile.is_file():
            raise ValueError(f"Missing Apple-issued provisioning profile: {profile}")
        decoded = subprocess.run(["security", "cms", "-D", "-i", str(profile)],
                                 check=True, capture_output=True).stdout
        metadata = plistlib.loads(decoded)
        if not permits_device(metadata, device):
            raise ValueError(f"Provisioning profile does not include this Mac: {bundle.name}")
        entitlements = metadata.get("Entitlements", {})
        signed = subprocess.run(["codesign", "-d", "--entitlements", ":-", str(bundle)],
                                check=True, capture_output=True).stdout
        actual = plistlib.loads(signed)
        info_file = bundle / ("Info.plist" if bundle == extension else "Contents/Info.plist")
        info = plistlib.loads(info_file.read_bytes())
        team = actual.get("com.apple.developer.team-identifier")
        if not team or team not in metadata.get("TeamIdentifier", []):
            raise ValueError(f"Signature and profile teams differ: {bundle.name}")
        identifier = f"{team}.{info['CFBundleIdentifier']}"
        allowed = entitlements.get("application-identifier",
                                   entitlements.get("com.apple.application-identifier", ""))
        if not fnmatch.fnmatchcase(identifier, allowed):
            raise ValueError(f"Profile does not match the bundle ID: {bundle.name}")
        expiration = metadata.get("ExpirationDate")
        if not expiration or expiration.replace(tzinfo=timezone.utc) <= datetime.now(timezone.utc):
            raise ValueError(f"Expired provisioning profile: {bundle.name}")
        for key, value in required.items():
            if entitlements.get(key) != value or actual.get(key) != value:
                raise ValueError(f"Profile does not grant {key}: {bundle.name}")
        if bundle == extension:
            usb = entitlements.get("com.apple.developer.driverkit.transport.usb", [])
            # Apple development profiles can grant all USB vendor IDs; the
            # driver's own signature must still restrict access to this VID/PID.
            if not grants_ch348(usb, allow_development_wildcard=True) or not grants_ch348(
                    actual.get("com.apple.developer.driverkit.transport.usb", [])):
                raise ValueError("Profile does not grant the CH348 USB transport")
    print("Signing profiles validated; macOS activation approval is still required.")


if __name__ == "__main__":
    try:
        if len(sys.argv) != 2:
            raise ValueError("Usage: check-signing.py /path/to/CH348.app")
        validate(Path(sys.argv[1]).resolve())
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        sys.exit(str(error))

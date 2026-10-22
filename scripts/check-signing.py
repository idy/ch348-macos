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


def usb_signature_matches(profile_usb, signature_usb, allow_development=False):
    wildcard = [{"idVendor": "*"}]
    if signature_usb == wildcard:
        return allow_development and profile_usb == wildcard
    return (isinstance(profile_usb, list) and isinstance(signature_usb, list)
            and len(signature_usb) == 1 and grants_ch348(signature_usb)
            and signature_usb[0] in profile_usb)


def validate(app, allow_development=False):
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
            signature_usb = actual.get("com.apple.developer.driverkit.transport.usb", [])
            if not usb_signature_matches(usb, signature_usb, allow_development):
                raise ValueError("USB signature does not match the profile. Development wildcard builds require explicit --development consent.")
            personality = info.get("IOKitPersonalities", {}).get("CH348", {})
            if personality.get("idVendor") != 0x1A86 or personality.get("idProduct") != 0x55D9:
                raise ValueError("Driver matching must remain restricted to CH348 1a86:55d9")
            if signature_usb == [{"idVendor": "*"}] and metadata.get("ProvisionsAllDevices"):
                raise ValueError("Development USB wildcard requires a device-scoped development profile")
    print("Signing profiles validated; macOS activation approval is still required.")


if __name__ == "__main__":
    try:
        args = sys.argv[1:]
        allow_development = "--development" in args
        args = [arg for arg in args if arg != "--development"]
        if len(args) != 1:
            raise ValueError("Usage: check-signing.py [--development] /path/to/CH348.app")
        validate(Path(args[0]).resolve(), allow_development)
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        sys.exit(str(error))

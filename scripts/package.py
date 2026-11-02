#!/usr/bin/env python3
"""Build and verify an unsigned PKG containing the universal CH348 app."""
import argparse
import hashlib
from pathlib import Path
import plistlib
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ID = "com.idy.ch348-macos.pkg"


def bundle_info(bundle, identifier, app=False):
    contents = bundle / "Contents" if app else bundle
    info = plistlib.loads((contents / "Info.plist").read_bytes())
    if info.get("CFBundleIdentifier") != identifier:
        raise ValueError(f"Unexpected bundle identifier: {bundle}")
    executable = info.get("CFBundleExecutable", "")
    if not executable or Path(executable).name != executable:
        raise ValueError(f"Invalid bundle executable: {bundle}")
    binary = contents / "MacOS" / executable if app else contents / executable
    architectures = subprocess.check_output(["lipo", "-archs", str(binary)], text=True).split()
    if set(architectures) != {"arm64", "x86_64"}:
        raise ValueError(f"Expected arm64 and x86_64 in {binary}; rebuild with scripts/build.sh --unsigned")
    signature = subprocess.run(["codesign", "-dvv", str(bundle)], capture_output=True, text=True)
    if signature.returncode == 0:
        if "Signature=adhoc" not in signature.stderr:
            raise ValueError(f"Expected an unsigned or ad-hoc signed bundle: {bundle}")
    elif "not signed at all" not in signature.stderr:
        raise ValueError(f"Cannot inspect bundle signature: {signature.stderr.strip()}")
    return info


def verify_package(package, source, expanded, version):
    subprocess.run(["pkgutil", "--expand-full", str(package), str(expanded)], check=True)
    metadata = ET.parse(expanded / "PackageInfo").getroot()
    if (metadata.get("identifier") != PACKAGE_ID or metadata.get("version") != version
            or metadata.get("install-location") != "/" or metadata.get("relocatable") != "false"
            or metadata.find("scripts") is not None):
        raise ValueError("Unexpected package metadata or installation scripts")
    restored = expanded / "Payload/Applications/CH348.app"
    originals = {path.relative_to(source): path for path in source.rglob("*")
                 if path.is_file() or path.is_symlink()}
    copies = {path.relative_to(restored): path for path in restored.rglob("*")
              if path.is_file() or path.is_symlink()}
    if originals.keys() != copies.keys():
        raise ValueError("Package payload does not match the app's file list")
    for name, original in originals.items():
        copy = copies[name]
        if original.is_symlink():
            if not copy.is_symlink() or original.readlink() != copy.readlink():
                raise ValueError(f"Package symlink mismatch: {name}")
        elif (copy.is_symlink() or original.read_bytes() != copy.read_bytes()
              or stat.S_IMODE(original.stat().st_mode) != stat.S_IMODE(copy.stat().st_mode)):
            raise ValueError(f"Package file content or permissions mismatch: {name}")
    print(f"Verified {len(originals)} packaged files, symlinks and permissions.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--unsigned", action="store_true", required=True,
                        help="explicitly create an unsigned development preview, not a distribution installer")
    parser.add_argument("--app", type=Path, default=ROOT / "build/Build/Products/Debug/CH348.app",
                        help="universal unsigned app produced by scripts/build.sh --unsigned")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "build/packages")
    args = parser.parse_args()
    app = args.app.resolve()
    if not app.is_dir():
        raise ValueError(f"App not found: {app}; run scripts/build.sh --unsigned first")
    if any(path.suffix in {".provisionprofile", ".mobileprovision"} for path in app.rglob("*")):
        raise ValueError("Unsigned packages must not include provisioning profiles; rebuild without signing")
    info = bundle_info(app, "com.idy.ch348-macos", app=True)
    driver = app / "Contents/Library/SystemExtensions/com.idy.ch348-macos.driver.dext"
    driver_info = bundle_info(driver, "com.idy.ch348-macos.driver")
    version = str(info.get("CFBundleShortVersionString", ""))
    build = str(info.get("CFBundleVersion", ""))
    if not re.fullmatch(r"[0-9]+(?:\.[0-9]+){0,2}", version) or not re.fullmatch(r"[0-9]+", build):
        raise ValueError("Package version and build must be numeric")
    if any(info[key] != driver_info.get(key) for key in ("CFBundleShortVersionString", "CFBundleVersion")):
        raise ValueError("App and driver versions must match")
    name = f"CH348-{version}-build{build}-macos-universal-unsigned.pkg"
    package_version = f"{version}.{build}"
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="ch348-pkg-") as temporary:
        work = Path(temporary)
        root = work / "root"
        staged = root / "Applications/CH348.app"
        staged.parent.mkdir(parents=True)
        # Package the build's files and modes without local Finder or quarantine metadata.
        subprocess.run(["ditto", "--norsrc", "--noextattr", "--noacl", "--noqtn",
                        str(app), str(staged)], check=True)
        components = work / "components.plist"
        subprocess.run(["pkgbuild", "--analyze", "--root", str(root), str(components)], check=True)
        settings = plistlib.loads(components.read_bytes())
        for bundle in settings:
            bundle["BundleIsRelocatable"] = False
        components.write_bytes(plistlib.dumps(settings))
        package = work / name
        subprocess.run(["pkgbuild", "--root", str(root), "--component-plist", str(components),
                        "--identifier", PACKAGE_ID, "--version", package_version,
                        "--install-location", "/", "--ownership", "recommended", str(package)], check=True)
        verify_package(package, app, work / "expanded", package_version)
        checksum = work / "SHA256SUMS"
        checksum.write_text(f"{hashlib.sha256(package.read_bytes()).hexdigest()}  {name}\n")
        shutil.move(str(package), str(output / name))
        shutil.move(str(checksum), str(output / "SHA256SUMS"))
    print(f"Unsigned package: {output / name}")
    print(f"Checksums: {output / 'SHA256SUMS'}")
    print("The app and PKG are not distribution-signed or notarized; DriverKit activation requires valid signing.")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, KeyError, subprocess.CalledProcessError) as error:
        sys.exit(str(error))
